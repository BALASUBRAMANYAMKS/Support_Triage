"""Deterministic rules that constrain model judgements."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PRIORITY_MATRIX={
 ('High','High'):'P1',('High','Medium'):'P2',('High','Low'):'P3',
 ('Medium','High'):'P2',('Medium','Medium'):'P3',('Medium','Low'):'P4',
 ('Low','High'):'P3',('Low','Medium'):'P4',('Low','Low'):'P4'
}
URGENCY_RAISE={'High':'High','Medium':'High','Low':'Medium'}


def load_taxonomy():
    return json.loads((ROOT/'schemas'/'taxonomy.json').read_text(encoding='utf-8-sig'))


def compute_priority(impact: str, urgency: str) -> str:
    return PRIORITY_MATRIX[(impact,urgency)]


def assignment_group(category: str | None, taxonomy: dict | None=None) -> str | None:
    taxonomy=taxonomy or load_taxonomy()
    for item in taxonomy['categories']:
        if item['name']==category: return item['default_assignment_group']
    return taxonomy['fallback_assignment_group']


def apply_business_rules(category: str | None, impact: str | None, urgency: str | None,
                         is_vip: bool, confidence: float, missing_information: list[str],
                         best_kb_score: float | None, taxonomy: dict | None=None) -> dict:
    taxonomy=taxonomy or load_taxonomy(); applied=['impact_urgency_matrix']
    if category=='Out of scope':
        return {'impact':None,'urgency':None,'priority':None,'assignment_group':None,'action':'redirect','rules_applied':['out_of_scope_redirect']}
    impact=impact if impact in ('High','Medium','Low') else 'Low'
    urgency=urgency if urgency in ('High','Medium','Low') else 'Medium'
    if is_vip:
        urgency=URGENCY_RAISE[urgency]; applied.append('vip_urgency_adjustment')
    priority=compute_priority(impact,urgency)
    if category=='Security':
        if priority in ('P3','P4'):
            priority='P2'; applied.append('security_priority_floor')
        group='Security Operations (SOC)'; action='escalate'; applied.append('security_escalation')
    else:
        group=assignment_group(category,taxonomy)
        if confidence < .6 and (category is None or group is None):
            group=taxonomy['fallback_assignment_group']; applied.append('low_confidence_fallback')
        if priority=='P1': action='escalate'
        elif missing_information: action='request_clarification'
        elif priority in ('P3','P4') and best_kb_score is not None and best_kb_score>=.35:
            action='auto_resolve'
        else: action='route'
    if confidence < .6: applied.append('human_review_threshold')
    return {'impact':impact,'urgency':urgency,'priority':priority,'assignment_group':group,'action':action,'rules_applied':applied}
