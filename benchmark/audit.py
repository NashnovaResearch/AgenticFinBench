"""One official DSH Agent session for all frozen claims in one answer."""
import asyncio
import json
import os
import re
import shutil
import signal
import time
import jsonschema
from .common import ROOT, read, save, sha, require
from .isolation import command


def strings(v, path=''):
    if isinstance(v,str): yield {'path':path,'text':v}
    elif isinstance(v,(dict,list)):
        for k,x in (v.items() if isinstance(v,dict) else enumerate(v)):
            yield from strings(x,path+'/'+str(k).replace('~','~0').replace('/','~1'))


def validate(result, qid, claims):
    jsonschema.validate(result,read(ROOT/'prompts/v3/result-schema.json'))
    require(result['case_id']==qid,'Wrong case ID')
    require(len(result['items'])==len(claims),'Missing or duplicate claims')
    require({c['claim_id']:c['claim_text'] for c in claims}=={c['claim_id']:c['claim_text'] for c in result['items']},'Changed claim IDs or text')
    return result


def recover(work, qid, claims):
    receipt=work.parent/'frozen-inputs.json'
    if not receipt.exists():return None
    if not all((work/n).is_file() and sha((work/n).read_bytes())==h for n,h in read(receipt).items()):return None
    decoder=json.JSONDecoder()
    for p in sorted(work.rglob('*.json')):
        if p.name in ['trace.json','case.json','claims.json','trace-strings.json','trace-index.json','result-schema.json']:continue
        text=p.read_text(errors='replace')
        for match in re.finditer(r'\{',text):
            try:
                v,_=decoder.raw_decode(text,match.start())
                return validate(v,qid,claims)
            except (ValueError,TypeError,KeyError,jsonschema.ValidationError): pass
    return None


def stats(result):
    items=result['items'];n=len(items)
    supported=sum('supported' in (i['trace_verdict'],i['factual_verdict']) for i in items)
    contradicted=sum(i['factual_verdict']=='contradicted' for i in items)
    unresolved=sum(i['factual_verdict']=='unresolved' for i in items)
    default=sum('supported' not in (i['trace_verdict'],i['factual_verdict']) and i['factual_verdict']=='unresolved' for i in items)
    return {'claim_count':n,'evidence_supported':supported,'evidence_support_rate':supported/n if n else None,
            'fact_contradicted':contradicted,'factual_contradiction_rate':contradicted/n if n else None,
            'unresolved':unresolved,'user_default_pass_count':default,
            'policy_pass_rate':(supported+default)/n if n else None}


async def run(case, claims, config, key, folder):
    work=folder/'workspace';work.mkdir(parents=True,exist_ok=True)
    save(work/'case.json',{'case_id':case['id'],'question':case['question'],'answer':case['answer'],
        'answer_generated_at':case.get('answer_generated_at'),'trace_provided':case['trace'] is not None})
    save(work/'claims.json',claims)
    save(work/'trace.json',case['trace'] if case['trace'] is not None else {'trace_missing':True})
    save(work/'trace-strings.json',list(strings(case['trace'])))
    save(work/'trace-index.json',[])
    shutil.copyfile(ROOT/'prompts/v3/result-schema.json',work/'result-schema.json')
    skill=work/'.agents/skills/audit-frozen-claims/SKILL.md';skill.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'prompts/v3/SKILL.md',skill)
    frozen={str(p.relative_to(work)):sha(p.read_bytes()) for p in work.rglob('*') if p.is_file()}
    save(folder/'frozen-inputs.json',frozen)
    shutil.copyfile(ROOT/'prompts/v3/search-budget.mjs',work/'search-budget.mjs')
    patch=(ROOT/'prompts/v3/runtime.patch.yml').read_text().replace('deepseek-v4-flash',config['audit_model'])
    patch+='\n- insert:\n    - id: audit-search-budget\n      name: file:///work/search-budget.mjs\n'
    (work/'runtime.patch.yml').write_text(patch)
    prompt=(ROOT/'prompts/v3/prompt.txt').read_text().replace('{count}',str(len(claims)))
    prompt+='\nMissing Trace means trace_verdict=incomplete; still verify facts. Explicit factual conflicts must be examined even if Trace supports them. Save completed judgments incrementally to result-checkpoint.json; final complete JSON to result.json. Stop external collection at 19 minutes, finish within 25 minutes. Never fabricate a verdict to meet a deadline.'
    save(work/'budget-clock.json',{'started_at_ms':int(time.time()*1000)})
    argv=['/opt/node','/opt/dsh/node_modules/@deepseek-ai/dsh/dist/cli.mjs','--profile','headless','--patch','/work/runtime.patch.yml',prompt]
    # Resolve official package bin instead of assuming an implementation filename.
    pkg=read(ROOT/'.runtime/node_modules/@deepseek-ai/dsh/package.json')
    entry=pkg['bin'];entry=entry.get('dsh') if isinstance(entry,dict) else entry
    argv[1]='/opt/dsh/node_modules/@deepseek-ai/dsh/'+entry
    cmd,env=command(folder,argv)
    env.update(DEEPSEEK_API_KEY=key,DEEPSEEK_BASE_URL=config['gateway'],DEEPSEEK_SEARCH_BASE_URL=config['gateway'])
    p=None
    try:
        with (folder/'stdout.log').open('wb') as out,(folder/'stderr.log').open('wb') as err:
            p=await asyncio.create_subprocess_exec(*cmd,env=env,stdout=out,stderr=err,start_new_session=True)
            started=time.monotonic()
            while p.returncode is None:
                try:await asyncio.wait_for(asyncio.shield(p.wait()),timeout=5)
                except asyncio.TimeoutError:pass
                if time.monotonic()-started>config['audit_timeout']:raise TimeoutError('v3 25-minute hard deadline')
                if time.monotonic()-started>300 and time.time()-(folder/'stderr.log').stat().st_mtime>300:
                    import zstandard
                    events=[]
                    try:
                        for z in (folder/'dsh-home').rglob('*.zstd'):
                            with z.open('rb') as stream, zstandard.ZstdDecompressor().stream_reader(stream) as r:
                                events.extend(json.loads(line) for line in r.read().decode().split('\n') if line.strip())
                    except (ValueError,zstandard.ZstdError):events=[]
                    last=max(events,key=lambda e:e.get('time',0)) if events else {}
                    if last.get('type')=='web/deepseek-search-llm-request' and time.time()-last.get('time',time.time()*1000)/1000>300:
                        raise TimeoutError('Search stalled without an event for 300 seconds')
        require(all(sha((work/n).read_bytes())==h for n,h in frozen.items()),'Agent changed frozen input')
        result=recover(work,case['id'],claims)
        require(result is not None,'DSH did not save a complete valid result; checkpoint retained')
        return result
    finally:
        if p and p.returncode is None:
            os.killpg(p.pid,signal.SIGTERM)
            try:await asyncio.wait_for(p.wait(),15)
            except asyncio.TimeoutError:
                os.killpg(p.pid,signal.SIGKILL);await p.wait()
