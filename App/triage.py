"""Single-ticket and batch triage with grounded evidence and safe fallback."""
from __future__ import annotations
import json, math, re, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
import yaml
from .llm_client import generate
from .pii import mask_ticket_text, mask_sensitive_text
from .retrieval import RetrievalService
from .rules import apply_business_rules, load_taxonomy

ROOT=Path(__file__).resolve().parents[1]

class SimilarTicket(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ticket_id:str
    score:float=Field(ge=0,le=1)

class Meta(BaseModel):
    model_config=ConfigDict(extra='forbid')
    model:str
    fallback_used:bool
    latency_ms:int=Field(ge=0)
    prompt_hash:str

class TriageDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ticket_id:str
    category:str|None
    subcategory:str|None
    affected_ci:str|None
    impact:Literal['High','Medium','Low']|None
    impact_reason:str
    urgency:Literal['High','Medium','Low']|None
    urgency_reason:str
    priority:Literal['P1','P2','P3','P4']|None
    rules_applied:list[str]
    assignment_group:str|None
    action:Literal['auto_resolve','route','request_clarification','escalate','redirect']
    suggested_resolution:str|None
    kb_references:list[str]
    similar_tickets:list[SimilarTicket]
    duplicate_of:str|None
    sentiment:Literal['neutral','frustrated','positive']
    missing_information:list[str]
    confidence:float=Field(ge=0,le=1)
    needs_human_review:bool
    rationale:str=Field(max_length=300)
    meta:Meta


def _config(): return yaml.safe_load((ROOT/'config.yaml').read_text(encoding='utf-8-sig'))

def _json_block(value): return json.dumps(value,ensure_ascii=False,indent=2)

def _sigmoid(value):
    value=max(-30,min(30,float(value)))
    return 1/(1+math.exp(-value))

def _score01(item):
    score=item.get('rerank_score')
    if score is None: return 0.0
    return max(0.0,min(1.0,_sigmoid(score)))

def _decision_confidence(raw_confidence,similar,kb_results,category):
    model_score=max(0.0,min(1.0,float(raw_confidence or 0.0)))
    retrieval_score=_score01(kb_results[0]) if kb_results else (_score01(similar[0]) if similar else 0.0)
    categories=[item.get('metadata',{}).get('category') for item in similar[:5]]
    categories=[x for x in categories if x]
    agreement=sum(x==category for x in categories)/len(categories) if categories else 0.0
    return round(.5*model_score+.3*retrieval_score+.2*agreement,3)

def _evidence(results):
    return [{'id':x['metadata'].get('source_id'),'section':x['metadata'].get('section'),'text':x['text'],'score':round(_score01(x),4)} for x in results]

def _allowed_values(taxonomy):
    return [{'category':c['name'],'subcategories':c['subcategories'],'example_cis':c['example_cis']} for c in taxonomy['categories']]

def _make_prompt(ticket,taxonomy,similar,kb):
    system=(ROOT/'Prompts'/'triage_system.md').read_text(encoding='utf-8-sig')
    return f"""{system}
TAXONOMY:\n{_json_block(_allowed_values(taxonomy))}
RETRIEVED_SIMILAR_TICKETS:\n{_json_block(_evidence(similar))}
RETRIEVED_KB_CHUNKS:\n{_json_block(_evidence(kb))}
<TICKET_DATA>\n{_json_block(ticket)}\n</TICKET_DATA>"""

def _safe_default(ticket,taxonomy,similar,error,meta=None):
    neighbor=next((x.get('metadata',{}).get('category') for x in similar if x.get('metadata',{}).get('category') in {c['name'] for c in taxonomy['categories']}),None)
    category=neighbor
    category_obj=next((c for c in taxonomy['categories'] if c['name']==category),None)
    return {
      'ticket_id':ticket['ticket_id'],'category':category,'subcategory':None,'affected_ci':None,
      'impact':'Low','impact_reason':'Safe fallback used after invalid model output or provider failure.',
      'urgency':'Medium','urgency_reason':'Safe fallback priority is P3 pending human review.',
      'priority':'P3','rules_applied':['safe_fallback'],'assignment_group':taxonomy['fallback_assignment_group'],
      'action':'route','suggested_resolution':None,'kb_references':[],
      'similar_tickets':[{'ticket_id':x['metadata']['source_id'],'score':_score01(x)} for x in similar[:5] if x.get('metadata',{}).get('doc_type')=='ticket'],
      'duplicate_of':None,'sentiment':'neutral','missing_information':[],
      'confidence':0.0,'needs_human_review':True,'rationale':('Safe fallback: '+str(error))[:300],
      'meta':meta or {'model':'fallback','fallback_used':True,'latency_ms':0,'prompt_hash':''}
    }

def _log_decision(ticket,decision,similar,kb):
    path=ROOT/'logs'/'triage.jsonl'; path.parent.mkdir(parents=True,exist_ok=True)
    row={'request_id':str(uuid.uuid4()),'ticket_id':ticket['ticket_id'],'created_at':datetime.now(timezone.utc).isoformat(),
         'query':mask_sensitive_text(ticket.get('short_description','')+' '+ticket.get('description','')),
         'similar_ticket_ids':[x['metadata'].get('source_id') for x in similar],
         'similar_ticket_scores':[_score01(x) for x in similar],
         'retrieved_kb_ids':[x['metadata'].get('source_id') for x in kb],
         'retrieved_kb_scores':[_score01(x) for x in kb],
         'decision':decision}
    with path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')

def _find_duplicate(query,category,similar):
    words=set(re.findall(r"[a-z0-9]+",query.lower()))
    if len(words)<4: return None
    settings=_config()['triage']; best=None
    for item in similar:
        meta=item.get('metadata',{})
        if meta.get('doc_type')!='ticket' or not meta.get('source_id') or meta.get('category')!=category: continue
        other=set(re.findall(r"[a-z0-9]+",(item.get('text') or '').lower()))
        overlap=len(words & other)/max(1,min(len(words),len(other)))
        score=_score01(item)
        if overlap>=float(settings.get('duplicate_token_overlap',0.3)) and score>=float(settings.get('duplicate_score_threshold',0.85)):
            if best is None or score>best[0]: best=(score,meta['source_id'])
    return best[1] if best else None
def triage(ticket:dict,retrieval:RetrievalService|None=None)->dict:
    cfg=_config(); taxonomy=load_taxonomy(); retrieval=retrieval or RetrievalService()
    masked=mask_ticket_text(ticket)
    query=(masked.get('short_description','')+' '+masked.get('description','')).strip()
    similar=retrieval.similar_tickets(query,5)
    kb=retrieval.triage_kb(query,5)
    prompt=_make_prompt(masked,taxonomy,similar,kb)
    try:
        llm=generate(prompt,params={'json_mode':True,'temperature':0.0})
        raw=json.loads(llm.content)
        category=raw.get('category')
        if category!='Out of scope' and category not in {c['name'] for c in taxonomy['categories']}:
            raise ValueError('category is not in taxonomy')
        item=next((c for c in taxonomy['categories'] if c['name']==category),None)
        subcategory=raw.get('subcategory')
        if item and subcategory not in item['subcategories']:
            raise ValueError('subcategory is not in taxonomy')
        impact=raw.get('impact'); urgency=raw.get('urgency')
        if category!='Out of scope' and (impact not in ('High','Medium','Low') or urgency not in ('High','Medium','Low')):
            raise ValueError('impact or urgency is invalid')
        confidence=_decision_confidence(raw.get('confidence'),similar,kb,category)
        duplicate_of=_find_duplicate(query,category,similar)
        missing=raw.get('missing_information') or []
        best=_score01(kb[0]) if kb else None
        rules=apply_business_rules(category,impact,urgency,bool((ticket.get('requester') or {}).get('is_vip')),confidence,missing,best,taxonomy)
        kb_ids=[x['metadata']['source_id'] for x in kb if x.get('metadata',{}).get('doc_type')=='kb']
        retrieved_ticket_ids=[x['metadata']['source_id'] for x in similar if x.get('metadata',{}).get('doc_type')=='ticket']
        resolution=raw.get('suggested_resolution')
        if resolution:
            citations=re.findall(r'\b(?:KB|INC|REQ)\d{4,7}\b',resolution)
            invalid=set(citations)-set(kb_ids+retrieved_ticket_ids)
            if invalid: resolution=re.sub(r'\b(?:KB|INC|REQ)\d{4,7}\b','',resolution).strip()
        score_map={x['metadata']['source_id']:_score01(x) for x in similar if x.get('metadata',{}).get('doc_type')=='ticket'}
        decision={
          'ticket_id':ticket['ticket_id'],'category':category,'subcategory':subcategory if category!='Out of scope' else None,
          'affected_ci':raw.get('affected_ci') if category!='Out of scope' else None,
          'impact':rules['impact'],'impact_reason':str(raw.get('impact_reason',''))[:300],
          'urgency':rules['urgency'],'urgency_reason':str(raw.get('urgency_reason',''))[:300],
          'priority':rules['priority'],'rules_applied':rules['rules_applied'],'assignment_group':rules['assignment_group'],'action':rules['action'],
          'suggested_resolution':resolution,'kb_references':list(dict.fromkeys(kb_ids))[:5],
          'similar_tickets':[{'ticket_id':tid,'score':score} for tid,score in list(score_map.items())[:5]],
          'duplicate_of':duplicate_of,'sentiment':raw.get('sentiment') if raw.get('sentiment') in ('neutral','frustrated','positive') else 'neutral',
          'missing_information':[str(x) for x in missing], 'confidence':confidence,
          'needs_human_review':category=='Security' or confidence<float(cfg['triage']['category_confidence_threshold']) or duplicate_of is not None,
          'rationale':((('Potential duplicate of '+duplicate_of+'. ') if duplicate_of else '')+str(raw.get('rationale','')))[:300],
          'meta':{'model':llm.model,'fallback_used':llm.fallback_used,'latency_ms':llm.latency_ms,'prompt_hash':llm.prompt_hash}
        }
        if decision['action']=='redirect':
            decision['impact']=decision['urgency']=decision['priority']=None
        validated=TriageDecision.model_validate(decision).model_dump(mode='json')
    except Exception as exc:
        fallback=_safe_default(ticket,taxonomy,similar,f'{type(exc).__name__}: {exc}')
        validated=TriageDecision.model_validate(fallback).model_dump(mode='json')
    _log_decision(ticket,validated,similar,kb)
    return validated

def triage_batch(tickets:list[dict],retrieval:RetrievalService|None=None)->list[dict]:
    service=retrieval or RetrievalService(); results=[]
    for ticket in tickets:
        try: results.append(triage(ticket,service))
        except Exception as exc: results.append(_safe_default(ticket,load_taxonomy(),[],f'{type(exc).__name__}: {exc}'))
    return results
