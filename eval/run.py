"""Run held-out triage, retrieval and chatbot evaluation during final integration only.
Run from repository root: python -m eval.run
"""
from __future__ import annotations
import csv, json, re
from datetime import datetime, timezone
from pathlib import Path
from App import db
from App.chatbot import chat
from App.retrieval import RetrievalService
from App.triage import triage_batch
import json
from urllib.error import URLError
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def ratio(n,d): return round(n/d,4) if d else 0.0


def main():
    # This script intentionally reads the isolated held-out labels only when explicitly run.
    db.init_db(); retrieval=RetrievalService()
    tickets=jsonl(ROOT/'data'/'test'/'tickets_test.jsonl')
    gold=jsonl(ROOT/'data'/'test'/'gold_labels.jsonl')
    questions=jsonl(ROOT/'data'/'test'/'chatbot_questions.jsonl')
    predictions=triage_batch(tickets,retrieval)
    by_id={x['ticket_id']:x for x in gold}
    correct={k:0 for k in ('category','subcategory','priority_exact','priority_within_one','routing','action','duplicate')}
    edge={}; security_total=security_correct=0
    priority_order={'P1':1,'P2':2,'P3':3,'P4':4}
    for pred in predictions:
        truth=by_id[pred['ticket_id']]
        checks={
          'category':pred.get('category')==truth.get('category'),
          'subcategory':pred.get('subcategory')==truth.get('subcategory'),
          'priority_exact':pred.get('priority')==truth.get('priority'),
          'priority_within_one':(pred.get('priority') in priority_order and truth.get('priority') in priority_order and abs(priority_order[pred['priority']]-priority_order[truth['priority']])<=1) or pred.get('priority')==truth.get('priority'),
          'routing':pred.get('assignment_group')==truth.get('assignment_group'),
          'action':pred.get('action')==truth.get('action'),
          'duplicate':pred.get('duplicate_of')==truth.get('duplicate_of')
        }
        for name,passed in checks.items(): correct[name]+=int(passed)
        tag=truth.get('edge_case','unknown'); slot=edge.setdefault(tag,{'total':0,'passed':0}); slot['total']+=1; slot['passed']+=int(all(checks.values()))
        if tag=='security': security_total+=1; security_correct+=int(pred.get('assignment_group')=='Security Operations (SOC)' and pred.get('action')=='escalate')
    triage_metrics={
      'triage_category_accuracy':ratio(correct['category'],len(predictions)),
      'triage_subcategory_accuracy':ratio(correct['subcategory'],len(predictions)),
      'triage_priority_exact':ratio(correct['priority_exact'],len(predictions)),
      'triage_priority_within_one':ratio(correct['priority_within_one'],len(predictions)),
      'triage_routing_accuracy':ratio(correct['routing'],len(predictions)),
      'triage_action_accuracy':ratio(correct['action'],len(predictions)),
      'duplicate_precision':ratio(sum(bool(x.get('duplicate_of')) and x.get('duplicate_of')==by_id[x['ticket_id']].get('duplicate_of') for x in predictions),sum(bool(x.get('duplicate_of')) for x in predictions)),
      'duplicate_recall':ratio(sum(bool(x.get('duplicate_of')) and x.get('duplicate_of')==by_id[x['ticket_id']].get('duplicate_of') for x in predictions),sum(bool(x.get('duplicate_of')) for x in gold)),
      'security_recall':ratio(security_correct,security_total),
      'valid_output_rate':ratio(sum(bool(x.get('ticket_id')) for x in predictions),len(tickets))
    }
    write_path=ROOT/'eval'/'triage_predictions.jsonl'
    write_path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in predictions),encoding='utf-8')

    retrieval_rows=[]
    for q in questions:
        results=retrieval.chatbot(q['question'],5)
        ids=[x['metadata'].get('source_id') for x in results]
        expected=q.get('expected_kb_ids',[])
        rank=next((i+1 for i,item in enumerate(ids) if item in expected),None)
        retrieval_rows.append((expected,rank))
    for t,label in zip(tickets,gold):
        results=retrieval.triage_kb(t['short_description']+' '+t['description'],5)
        ids=[x['metadata'].get('source_id') for x in results]
        expected=label.get('expected_kb_ids',[])
        rank=next((i+1 for i,item in enumerate(ids) if item in expected),None)
        retrieval_rows.append((expected,rank))
    answerable=[rank for expected,rank in retrieval_rows if expected]
    retrieval_metrics={'retrieval_hit_at_5':ratio(sum(rank is not None for expected,rank in retrieval_rows if expected),len(answerable)),
                       'retrieval_mrr':ratio(sum(1/rank for expected,rank in retrieval_rows if expected and rank),len(answerable))}
    ablation_rows={'dense_only':[],'hybrid':[],'hybrid_reranked':[]}
    for question in questions:
        expected=question.get('expected_kb_ids',[])
        if not expected: continue
        stages=retrieval.ablation(question['question'])
        for stage,items in stages.items():
            ids=[x['metadata'].get('source_id') for x in items]
            rank=next((i+1 for i,item in enumerate(ids) if item in expected),None)
            ablation_rows[stage].append(rank)
    for stage,ranks in ablation_rows.items():
        retrieval_metrics[f'ablation_{stage}_hit_at_5']=ratio(sum(x is not None for x in ranks),len(ranks))
        retrieval_metrics[f'ablation_{stage}_mrr']=ratio(sum(1/x for x in ranks if x),len(ranks))

    employee=db.get_user('EMP0001')
    chatbot_rows=[]
    for question in questions:
        response=chat(employee,question['question'],retrieval=retrieval)
        citations={c['kb_id'] for c in response.get('citations',[])}
        refused=bool(re.search(r"couldn't find|can't provide|couldn't verify|can't find a reliable|cannot answer",response['reply'],re.I))
        expected=set(question.get('expected_kb_ids',[]))
        chatbot_rows.append({'question_id':question['question_id'],'expected':question,'response':response,'citation_correct':bool(expected & citations) if expected else None,'refused':refused,'ticket_preview':bool(response.get('ticket_preview'))})
    answerable=[x for x in chatbot_rows if x['expected'].get('answerable') and not x['expected'].get('should_raise_ticket')]
    unanswerable=[x for x in chatbot_rows if not x['expected'].get('answerable') and not x['expected'].get('should_raise_ticket')]
    handoff=[x for x in chatbot_rows if x['expected'].get('should_raise_ticket')]
    refused=[x for x in chatbot_rows if x['refused']]
    handoff_metrics={'chatbot_citation_correctness':ratio(sum(x['citation_correct'] for x in answerable),len(answerable)),
       'chatbot_refusal_recall':ratio(sum(x['refused'] for x in unanswerable),len(unanswerable)),
       'chatbot_refusal_precision':ratio(sum(x['expected'].get('answerable') is False for x in refused),len(refused)),
       'chatbot_ticket_handoff':ratio(sum(x['ticket_preview'] for x in handoff),len(handoff))}
    chatbot_path=ROOT/'eval'/'chatbot_predictions.jsonl'
    chatbot_path.write_text(''.join(json.dumps({'question_id':x['question_id'],'reply':x['response']['reply'],'citations':x['response'].get('citations',[]),'expected_kb_ids':x['expected'].get('expected_kb_ids',[]),'refused':x['refused'],'ticket_preview':x['ticket_preview']},ensure_ascii=False)+'\n' for x in chatbot_rows),encoding='utf-8')

    metrics={**triage_metrics,**retrieval_metrics,**handoff_metrics}
    timestamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    out=ROOT/'eval_results.csv'; exists=out.exists() and out.stat().st_size>0
    with out.open('a',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=['run_at',*metrics.keys()])
        if not exists: writer.writeheader()
        writer.writerow({'run_at':timestamp,**metrics})
    report=ROOT/'EVAL_REPORT.md'
    report.write_text('# Evaluation report\n\n'
      f'Run: {timestamp}\n\n'
      'Gold labels were read only by this evaluation command and were not used for ingestion or few-shot prompts.\n\n'
      '## Metrics\n\n| Metric | Result |\n|---|---:|\n'+''.join(f'| {k} | {v:.1%} |\n' for k,v in metrics.items())+
      '\n## Edge-case triage\n\n| Edge case | Passed / total |\n|---|---:|\n'+''.join(f"| {k} | {v['passed']} / {v['total']} |\n" for k,v in sorted(edge.items()))+
      '\n## Ablation\n\n| Stage | Hit@5 | MRR |\n|---|---:|---:|\n'+''.join(f"| {stage} | {ratio(sum(x is not None for x in ranks),len(ranks)):.1%} | {ratio(sum(1/x for x in ranks if x),len(ranks)):.3f} |\n" for stage,ranks in ablation_rows.items())+
      '\n## Failure analysis\n\nDocument at least three concrete failures, why each happened, and the fix. Manually inspect ten chatbot answers for groundedness.\n',encoding='utf-8')
    print('Evaluation complete:',metrics)
    print('Per-edge-case results:',edge)

if __name__=='__main__': main()
