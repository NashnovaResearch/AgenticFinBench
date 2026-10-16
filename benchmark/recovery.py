"""Explicit, offline recovery of complete extractor responses after transport fixes."""
from fincarat.extract.parser import parse_claim_jsonl
from fincarat.extract.schema import ClaimExtractionRequest, ExtractionMode, AnswerUnitAnchor
from fincarat.extract.continuation import merge_extracted_claims
from .common import ROOT, read, sha, digest, require


def extraction_request(case):
    return ClaimExtractionRequest(mode=ExtractionMode.EXTRACT,query_id=case['id'],query=case['question'],answer=case['answer'],answer_sha256=sha(case['answer'].encode()),answer_units=(AnswerUnitAnchor(unit_id='U001',text=case['answer'],start=0,end=len(case['answer'])),))


def extract_from(previous, case, config):
    old=read(previous/'manifest.json')['binding']
    require(old['cases'].get(case['id'])==digest(case),'Recovery input/Trace binding mismatch')
    for k in ['extract_model','gateway','max_tokens']:
        require(old['config'][k]==config[k],'Recovery extractor configuration changed: '+k)
    require(old['files']['prompts/claim_extractor_v3.txt']==sha((ROOT/'prompts/claim_extractor_v3.txt').read_bytes()),'Recovery extractor prompt changed')
    req=extraction_request(case)
    for p in sorted((previous/'cases'/case['id']/'extract').glob('attempt-*/request-*-response.json')):
        r=read(p);request=read(p.with_name(p.name.replace('-response.json','.json')))
        if r['finish_reason']!='stop':continue
        if request['model']!=config['extract_model']:continue
        if request['messages'][0]['content']!=(ROOT/'prompts/claim_extractor_v3.txt').read_text():continue
        # Only full first-round extraction is recoverable here; a continuation
        # alone must never be mistaken for a complete answer slate.
        if read_payload(request['messages'][1]['content'])!=req.model_dump(mode='json'):continue
        allowed=set(config['response_model_aliases'].get(config['extract_model'],[]))|{config['extract_model']}
        if not set(r['response_models']) or not set(r['response_models'])<=allowed:continue
        parsed=parse_claim_jsonl(r['content'],request=req,model=config['extract_model'])
        if parsed.status.value!='complete':continue
        claims=[x.model_dump(mode='json') for x in merge_extracted_claims(case['id'],parsed.claims)]
        return {'complete':True,'claims':claims,'factual_claims':[x for x in claims if x.get('enters_factual_denominator',True)],'rounds':[],
            'recovered':{'response_sha256':sha(p.read_bytes()),'source_manifest_sha256':sha((previous/'manifest.json').read_bytes()),'paid_calls':0}}
    raise ValueError('No complete, compatible extractor response to recover')


def read_payload(text):
    import json
    return json.loads(text)
