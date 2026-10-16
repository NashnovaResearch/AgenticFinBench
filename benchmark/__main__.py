"""Resume-safe, per-question pipeline. No model calls before input/preflight validation."""
import argparse
import asyncio
import csv
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path
from fincarat.extract.continuation import extract_with_continuation
from fincarat.extract.schema import ClaimExtractionRequest, ExtractionMode, AnswerUnitAnchor
from .common import ROOT, VERSION, dataset, digest, read, require, save, sha
from .transport import Backend, ModelRoutingError
from . import audit, quality
from .isolation import probe


def inputs(path, questions):
    text=path.read_text()
    rows=json.loads(text) if text.lstrip().startswith('[') else [json.loads(x) for x in text.splitlines() if x.strip()]
    require(isinstance(rows,list) and rows,'Answers must be a nonempty JSON array or JSONL')
    result=[];ids=set()
    for row in rows:
        qid=row['id'];require(qid in questions and qid not in ids,'Unknown/duplicate question ID: '+qid);ids.add(qid)
        require(isinstance(row['answer'],str) and row['answer'].strip(),'Empty answer: '+qid)
        if 'question' in row:require(row['question']==questions[qid]['question'],'Question text mismatch: '+qid)
        trace=row.get('trace')
        if 'trace_file' in row:
            require(trace is None,'Use trace or trace_file, not both')
            trace=read((path.parent/row['trace_file']).resolve())
        require(trace is None or isinstance(trace,(dict,list)),'Trace must be object/array/null')
        result.append(dict(id=qid,question=questions[qid]['question'],answer=row['answer'],trace=trace,answer_generated_at=row.get('answer_generated_at')))
    return result


def source_hashes():
    paths=[ROOT/'config.json',ROOT/'requirements.txt',ROOT/'package-lock.json']
    for sub in ['benchmark','fincarat','prompts','data']:
        paths.extend(p for p in (ROOT/sub).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    return {str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sorted(paths)}


async def main(args):
    questions,rubrics=dataset();cases=inputs(args.answers.resolve(),questions)
    if args.ids:
        selected=set(args.ids.split(','));require(selected<={c['id'] for c in cases},'Selected ID has no answer')
        cases=[c for c in cases if c['id'] in selected]
    if args.limit:cases=cases[:args.limit]
    config=read(args.config);require(config['gateway']=='https://api.ikuncode.cc/v1','This release supports the verified ikuncode adapter only')
    for n in ['extract_concurrency','audit_concurrency','quality_concurrency','max_attempts','extract_max_rounds','max_tokens','request_timeout']:
        require(type(config[n]) is int and config[n]>0,'Invalid configuration: '+n)
    require(config['audit_timeout']==1500,'v3 fixed research19m/hard25m policy requires audit_timeout=1500')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    from importlib.metadata import version
    runtime={n:version(n) for n in ['openai','pydantic','jsonschema','zstandard','python-dotenv']}
    binding={'runtime':runtime,'version':VERSION,'config':config,'files':source_hashes(),'cases':{c['id']:digest(c) for c in cases},'dataset_count':500,'selected_count':len(cases)}
    if (out/'manifest.json').exists():require(read(out/'manifest.json')['binding']==binding,'Run inputs/config/code changed; choose a NEW --out directory')
    else:save(out/'manifest.json',{'binding':binding,'created_at':time.time()})
    for c in cases:save(out/'inputs'/f"{c['id']}.json",c)
    if args.check:
        print(json.dumps({'validated':len(cases),'dataset':500,'paid_calls':0,'version':VERSION}));return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env',override=False)
    key=os.environ.get('IKUNCODE_DEEPSEEK_API_KEY','');require(bool(key),'Missing IKUNCODE_DEEPSEEK_API_KEY; fill .env')
    # Fail before extraction if CLI / private filesystem cannot run.
    require((ROOT/'.runtime/node_modules/@deepseek-ai/dsh/package.json').exists(),'Missing DSH runtime: use ./run.sh')
    save(out/'isolation-preflight.json',probe(out/'isolation-preflight'))
    sems={s:asyncio.Semaphore(config[k]) for s,k in [('extract','extract_concurrency'),('audit','audit_concurrency'),('quality','quality_concurrency')]}
    active={s:0 for s in sems};states={};done={}
    def report():
        stagecounts={s:sum(s in x.get('completed',[]) for x in states.values()) for s in sems}
        scores=[x['quality_score'] for x in done.values()]
        summary={'version':VERSION,'selected':len(cases),'dataset_count':500,'completed':len(done),
            'failed':sum(x['status']=='failed' for x in states.values()),'stages':stagecounts,'active':active.copy(),
            'mean_quality_score':sum(scores)/len(scores) if scores else None,'mean_denominator':len(scores),
            'final':len(done)==len(cases),'updated_at':time.time(),'questions':[done[k] for k in sorted(done)]}
        counts=sum(x['claim_count'] for x in done.values())
        summary['evidence_claim_count']=counts
        for n,d in [('evidence_support_rate','evidence_supported'),('factual_contradiction_rate','fact_contradicted'),('policy_pass_rate','policy_pass_count')]:
            summary[n]=sum(x[d] for x in done.values())/counts if counts else None
        save(out/'summary.json',summary)
        save(out/'progress.json',{'active':active,'cases':states,'updated_at':time.time()})
        with (out/'scores.csv').open('w',newline='') as f:
            fields=['id','quality_score','claim_count','evidence_support_rate','factual_contradiction_rate','policy_pass_rate','unresolved']
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(summary['questions'])
    async def run_case(c):
        qid=c['id'];base=out/'cases'/qid;base.mkdir(parents=True,exist_ok=True)
        state=states[qid]={'status':'queued','completed':[]}
        results={}
        try:
            for stage in ['extract','audit','quality']:
                dest=base/(stage+'.json')
                # Hash checked against manifest, result receipt protects cached artifacts.
                if dest.exists():
                    receipt=read(base/(stage+'-receipt.json'))
                    require(receipt['run_binding_sha256']==digest(binding) and receipt['result_sha256']==sha(dest.read_bytes()),'Cached result changed: '+str(dest))
                    results[stage]=read(dest)
                    state['completed'].append(stage);report();continue
                if stage=='extract' and args.recover_from:
                    from .recovery import extract_from
                    results[stage]=extract_from(args.recover_from.resolve(),c,config)
                    save(dest,results[stage]);save(base/(stage+'-receipt.json'),{'result_sha256':sha(dest.read_bytes()),'run_binding_sha256':digest(binding)})
                    state['completed'].append(stage);report();continue
                async with sems[stage]:
                    active[stage]+=1;state['status']=stage;report()
                    try:
                        attempts=base/stage;attempts.mkdir(exist_ok=True)
                        previous=sorted(attempts.glob('attempt-*'))
                        budget=1 if stage=='audit' else config['max_attempts']
                        feedback=''
                        for old in reversed(previous):
                            accepted=old/'accepted.json'
                            if accepted.exists():
                                results[stage]=read(accepted);break
                        # Recover complete saved audit before any new call.
                        if stage=='audit' and previous:
                            value=audit.recover(previous[-1]/'workspace',qid,results['extract']['factual_claims'])
                            if value is not None:results[stage]=value
                        for attempt_n in range(len(previous)+1,budget+1):
                            if stage in results:break
                            folder=attempts/f'attempt-{attempt_n:02d}';folder.mkdir()
                            backend=None
                            try:
                                if stage=='audit':
                                    results[stage]=await audit.run(c,results['extract']['factual_claims'],config,key,folder)
                                else:
                                    backend=Backend(key,config,folder)
                                    if stage=='extract':
                                        req=ClaimExtractionRequest(mode=ExtractionMode.EXTRACT,query_id=qid,query=c['question'],answer=c['answer'],answer_sha256=sha(c['answer'].encode()),
                                            answer_units=(AnswerUnitAnchor(unit_id='U001',text=c['answer'],start=0,end=len(c['answer'])),))
                                        r=await extract_with_continuation(backend,request=req,system_prompt=(ROOT/'prompts/claim_extractor_v3.txt').read_text(),
                                            model=config['extract_model'],temperature=0,max_tokens=config['max_tokens'],max_rounds=config['extract_max_rounds'])
                                        value={'complete':r.complete,'claims':[x.model_dump(mode='json') for x in r.claims],'rounds':list(r.rounds),'stall_reason':r.stall_reason}
                                        save(folder/'extraction.json',value);require(r.complete,'Extraction incomplete; partial claims retained')
                                        value['factual_claims']=[x for x in value['claims'] if x.get('enters_factual_denominator',True)]
                                        results[stage]=value
                                    else:results[stage]=await quality.run(c,rubrics[qid],results['audit'],backend,config,feedback)
                                save(folder/'accepted.json',results[stage])
                            except Exception as ex:
                                feedback=str(ex).replace(key,'[REDACTED]');save(folder/'failure.json',{'error':feedback,'time':time.time()})
                                # Routing/authentication/config errors are deterministic: no paid repetition.
                                from openai import AuthenticationError,PermissionDeniedError,BadRequestError,NotFoundError
                                if isinstance(ex,(AuthenticationError,PermissionDeniedError,BadRequestError,NotFoundError,ModelRoutingError)):raise
                            finally:
                                if backend:await backend.close()
                        require(stage in results,stage+' attempt budget exhausted: '+feedback)
                        save(dest,results[stage]);save(base/(stage+'-receipt.json'),{'result_sha256':sha(dest.read_bytes()),'run_binding_sha256':digest(binding)})
                        state['completed'].append(stage)
                    finally:active[stage]-=1;report()
            stats=audit.stats(results['audit']);stats['policy_pass_count']=stats['evidence_supported']+stats['user_default_pass_count']
            row={'id':qid,'quality_score':results['quality']['arithmetic']['score'],**stats}
            done[qid]=row;state['status']='complete';save(base/'score.json',row)
            print(f"{qid}: quality={row['quality_score']:.2f}, facts={stats['claim_count']}, contradicted={stats['fact_contradicted']}",flush=True)
        except Exception as ex:
            state.update(status='failed',error=str(ex).replace(key,'[REDACTED]'))
            print(qid+': FAILED '+state['error'][:300],file=sys.stderr,flush=True)
        finally:report()
    async def heartbeat():
        while True:
            await asyncio.sleep(30);report()
            print(json.dumps({'complete':len(done),'selected':len(cases),'active':active}),flush=True)
    pulse=asyncio.create_task(heartbeat())
    try:await asyncio.gather(*(run_case(c) for c in cases))
    finally:pulse.cancel()
    s=read(out/'summary.json')
    print(json.dumps({k:s[k] for k in ['completed','selected','failed','mean_quality_score','mean_denominator','final']},ensure_ascii=False))
    return 0 if s['final'] else 1


def cli():
    p=argparse.ArgumentParser(description='500题：原子抽取 → v3 Agent → 正负项/事实影响质量评分')
    p.add_argument('--answers',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config.json');p.add_argument('--ids');p.add_argument('--limit',type=int,default=0)
    p.add_argument('--recover-from',type=Path,help='Explicitly recover compatible complete extractor responses without another call')
    p.add_argument('--check',action='store_true',help='Validate data/input without model calls')
    args=p.parse_args();require(args.limit>=0,'--limit cannot be negative')
    try:code=asyncio.run(main(args))
    except Exception as ex:
        key=os.environ.get('IKUNCODE_DEEPSEEK_API_KEY','')
        message=str(ex).replace(key,'[REDACTED]') if key else str(ex)
        print('ERROR: '+message,file=sys.stderr);code=1
    raise SystemExit(code)

if __name__=='__main__':cli()
