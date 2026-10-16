import copy
import json
from decimal import Decimal
import jsonschema
from .common import ROOT, read, require
from .scoring import score


def obj(props, required=None):
    return {'type':'object','properties':props,'required':required or list(props),'additionalProperties':False}


def arr(item): return {'type':'array','items':item}
S={'type':'string','minLength':1};B={'type':'boolean'};STRINGS=arr(S)
POS=obj({'id':S,'verdict':B,'reason':S,'quotes':STRINGS,'unresolved_contradictions':STRINGS})
NEG=obj({'id':S,'verdict':B,'reason':S,'quotes':STRINGS,'core_dependency':B,'dependency_chain':S,'counterfactual':S})
PROOF=obj({'original_threshold':{'type':'number'},'corrected_threshold':{'type':'number'},'test_value':{'type':'number'},'operator':{'enum':['gt','ge','lt','le']},'unit':S,'source_value':S})
ERROR=obj({'id':S,'claim_ids':STRINGS,'original_negative_id':{'type':['string','null']},
    'severity':{'enum':['MINOR','MATERIAL','CORE']},'reason':S,'correction_unit':S,'quotes':STRINGS,
    'scope_positive_ids':STRINGS,'affected_positive_ids':STRINGS,'causal_credit_positive_ids':STRINGS,
    'causal_credit_reason':S,'dependency_chain':S,'counterfactual':S,'unaffected_conclusions':STRINGS,
    'role':{'enum':['decision_threshold','calculation_input','supporting_detail','no_downstream_use']},
    'threshold_proof':{'anyOf':[{'type':'null'},PROOF]}})
SCHEMA=obj({'status':{'enum':['complete','incomplete']},'missing_requirements':arr(S),
    'positive':arr(POS),'negative':arr(NEG),
    'fact_reviews':arr(obj({'claim_id':S,'actionable':B,'error_id':{'type':['string','null']},'reason':S,'quotes':STRINGS})),
    'fact_errors':arr(ERROR)})


def evaluate(raw, rubric, answer, audit):
    jsonschema.validate(raw,SCHEMA)
    require(raw['status']=='complete' and not raw['missing_requirements'],'Quality judgment incomplete')
    ps={p['id']:p for p in rubric['positive']};ns={n['id']:n for n in rubric['negative']}
    for typ,expected in [('positive',ps),('negative',ns)]:
        require(len(raw[typ])==len(expected) and {x['id'] for x in raw[typ]}==set(expected),'Missing/duplicate rubric judgments')
    def quotes(x, mandatory=False):
        require(not mandatory or bool(x['quotes']),'Missing answer witness')
        require(all(q in answer for q in x['quotes']),'Quote is not verbatim answer text')
    pv={p['id']:p['verdict'] for p in raw['positive']}
    nv={n['id']:n['verdict'] for n in raw['negative']}
    for p in raw['positive']:
        quotes(p)
        require(all(q in answer for q in p['unresolved_contradictions']),'Invented contradiction witness')
        require(not p['unresolved_contradictions'] or not p['verdict'],'Unresolved contradiction cannot pass')
    effective=copy.deepcopy(rubric)
    en={n['id']:n for n in effective['negative']}
    for n in raw['negative']:
        quotes(n,n['verdict'])
        require(not n['core_dependency'] or n['verdict'],'Untriggered negative cannot be core')
        if n['core_dependency']:en[n['id']]['score_cap']=min(en[n['id']]['score_cap'] or 100,60)
    eligible={a['claim_id']:a for a in audit['items'] if a['factual_verdict']=='contradicted'}
    reviews={f['claim_id']:f for f in raw['fact_reviews']}
    require(len(reviews)==len(raw['fact_reviews']) and reviews.keys()==eligible.keys(),'Every factual contradiction needs review, including Trace-supported conflicts')
    errors={e['id']:e for e in raw['fact_errors']}
    require(len(errors)==len(raw['fact_errors']) and not (set(errors)&(set(ps)|set(ns))),'Duplicate error IDs')
    roots=set();claimed=set();credits=set();extras=[]
    for f in reviews.values():
        quotes(f,True)
        require((f['error_id'] in errors) if f['actionable'] else f['error_id'] is None,'Invalid fact disposition')
    for eid,e in errors.items():
        quotes(e,True)
        require(e['correction_unit'] not in roots,'Duplicate correction unit');roots.add(e['correction_unit'])
        require(bool(e['claim_ids']) and len(set(e['claim_ids']))==len(e['claim_ids']) and set(e['claim_ids'])<=eligible.keys(),'Invalid fact claim IDs')
        require(not claimed.intersection(e['claim_ids']),'Fact counted more than once');claimed.update(e['claim_ids'])
        require(all(reviews[c]['actionable'] and reviews[c]['error_id']==eid for c in e['claim_ids']),'Review/error mismatch')
        for key in ['scope_positive_ids','affected_positive_ids','causal_credit_positive_ids']:
            require(len(set(e[key]))==len(e[key]) and set(e[key])<=ps.keys(),'Invalid positive links')
        scope=set(e['scope_positive_ids']);affected=set(e['affected_positive_ids']);credit=set(e['causal_credit_positive_ids'])
        require(credit<=affected<=scope,'Credit/affected/scope mismatch')
        require(not any(pv[k] for k in affected),'Affected full positive predicate still passes')
        require(not credits.intersection(credit),'Duplicate positive loss credit');credits.update(credit)
        require((not scope) if e['severity']=='MINOR' else bool(scope),'Severity/task scope mismatch')
        require(bool(e['unaffected_conclusions']),'Missing unaffected-path assessment')
        if e['role']=='decision_threshold':
            p=e['threshold_proof'];require(p is not None,'Threshold proof missing')
            require(any(p['source_value'] in q for q in e['quotes']),'Threshold not grounded in source quote')
            require(Decimal(p['source_value'])==Decimal(str(p['original_threshold'])),'Invented original threshold')
            compare={'gt':lambda a,b:a>b,'ge':lambda a,b:a>=b,'lt':lambda a,b:a<b,'le':lambda a,b:a<=b}[p['operator']]
            require(compare(p['test_value'],p['original_threshold'])!=compare(p['test_value'],p['corrected_threshold']),'Threshold counterexample does not flip classification')
        else:require(e['threshold_proof'] is None,'Non-threshold cannot invent threshold proof')
        original=e['original_negative_id']
        if original is not None:
            require(original in ns and nv[original],'Untriggered original owner')
            if e['severity']=='CORE':en[original]['score_cap']=min(en[original]['score_cap'] or 100,60)
        else:
            # Active original roots own their positive-loss credits first.
            original_credit={p for n in effective['negative'] if nv[n['id']] for p in n['overlap_positive_ids']}
            credit-=original_credit
            effective['negative'].append(dict(id=eid,criterion=e['reason'],penalty_points={'MINOR':3,'MATERIAL':12,'CORE':25}[e['severity']],score_cap=60 if e['severity']=='CORE' else None,
                dedup_group='fact:'+e['correction_unit'],overlap_positive_ids=sorted(credit),invalidates_positive_ids=sorted(affected)))
            extras.append(dict(id=eid,verdict=True,reason=e['reason']))
    require(claimed=={f['claim_id'] for f in reviews.values() if f['actionable']},'Orphan fact/error review')
    judgments={'positive':raw['positive'],'negative':raw['negative']+extras}
    arithmetic=score(judgments,effective)
    # Independent Decimal recomputation of totals catches scorer integration drift.
    base=sum((Decimal(str(p['weight'])) for p in effective['positive'] if pv[p['id']]),Decimal(0))
    triggered={x['id'] for x in judgments['negative'] if x['verdict']};groups={};caps=[Decimal(100)]
    for n in effective['negative']:
        if n['id'] not in triggered:continue
        g=groups.setdefault(n['dedup_group'],[Decimal(0),set()]);g[0]=max(g[0],Decimal(str(n['penalty_points'])));g[1].update(n['overlap_positive_ids'])
        if n['score_cap'] is not None:caps.append(Decimal(str(n['score_cap'])))
    penalty=sum((max(Decimal(0),v[0]-sum((Decimal(str(ps[k]['weight'])) for k in v[1] if not pv[k]),Decimal(0))) for v in groups.values()),Decimal(0))
    expected=min(max(Decimal(0),base-penalty),min(caps))
    require(abs(float(expected)-arithmetic['score'])<1e-8,'Independent arithmetic mismatch')
    return {'judgment':raw,'effective_rubric':effective,'arithmetic':arithmetic,'independent_score':float(expected)}


async def run(case,rubric,audit,backend,config,feedback=''):
    payload={'question':case['question'],'answer':case['answer'],'rubric':rubric,'audit':audit,'output_schema':SCHEMA}
    if feedback:payload['validation_feedback']=feedback
    text=await backend.complete(model=config['quality_model'],system_prompt=(ROOT/'prompts/quality.txt').read_text(),
        user_prompt=json.dumps(payload,ensure_ascii=False),temperature=0,max_tokens=config['max_tokens'])
    text=text.strip()
    if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
    return evaluate(json.loads(text),rubric,case['answer'],audit)
