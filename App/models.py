"""Pydantic v2 records aligned with the frozen JSON contracts."""
from __future__ import annotations
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictRecord(BaseModel):
    model_config=ConfigDict(extra='forbid')

class Requester(StrictRecord):
    requester_id:str
    name:str
    email:str
    department:Literal['Finance','HR','Sales','Engineering','Operations','Legal','Leadership']
    location:Literal['Chennai','Bengaluru','Pune','Hyderabad','Noida']
    job_title:str
    is_vip:bool

class WorkNote(StrictRecord):
    timestamp:datetime
    author:str
    note:str

class TicketRecord(StrictRecord):
    ticket_id:str=Field(pattern=r'^(INC|REQ)[0-9]{7}$')
    ticket_type:Literal['Incident','Service Request']
    channel:Literal['Portal','Email','Chatbot','Phone']
    created_at:datetime
    requester:Requester
    short_description:str=Field(min_length=1,max_length=120)
    description:str=Field(min_length=1)
    category:str|None
    subcategory:str|None
    affected_ci:str|None
    impact:Literal['High','Medium','Low']|None
    urgency:Literal['High','Medium','Low']|None
    priority:Literal['P1','P2','P3','P4']|None
    assignment_group:str|None
    assigned_to:str|None
    status:Literal['New','Assigned','In Progress','Pending','Resolved','Closed','Cancelled']
    pending_reason:Literal['Awaiting User','Awaiting Vendor','Awaiting Change']|None
    sla_response_due:datetime|None
    sla_resolution_due:datetime|None
    first_response_at:datetime|None
    resolved_at:datetime|None
    closed_at:datetime|None
    sla_breached:bool
    resolution_code:Literal['Solved (Permanent Fix)','Solved (Workaround)','User Error / Training','Not Reproducible','Duplicate','Cancelled by User']|None
    resolution_notes:str|None
    work_notes:list[WorkNote]
    kb_references:list[str]
    duplicate_of:str|None
    reassignment_count:int=Field(ge=0)
    reopen_count:int=Field(ge=0)
    csat_score:int|None=Field(default=None,ge=1,le=5)
    tags:list[str]

    @model_validator(mode='after')
    def ticket_id_matches_type(self):
        expected='INC' if self.ticket_type=='Incident' else 'REQ'
        if not self.ticket_id.startswith(expected): raise ValueError('ticket_id prefix must match ticket_type')
        return self

class KBArticleRecord(StrictRecord):
    kb_id:str=Field(pattern=r'^KB[0-9]{4}$')
    title:str
    category:str
    subcategory:str
    applies_to:list[str]
    audience:Literal['end_user','agent']
    body:str
    keywords:list[str]
    version:int=Field(ge=1)
    status:Literal['Published','Retired']
    last_reviewed:date
    superseded_by:str|None=None

    @model_validator(mode='after')
    def body_has_required_sections(self):
        for heading in ('## Symptoms','## Cause','## Resolution','## When to raise a ticket'):
            if heading not in self.body: raise ValueError(f'Missing KB section: {heading}')
        if self.status=='Retired' and not self.superseded_by: raise ValueError('Retired articles must point to a successor')
        return self


def validate_ticket_taxonomy(record:TicketRecord,taxonomy:dict):
    if record.category is None:
        if record.status!='New': raise ValueError('Only untriaged New tickets may omit category labels')
        return
    if record.category=='Out of scope': return
    category=next((c for c in taxonomy['categories'] if c['name']==record.category),None)
    if not category: raise ValueError(f'Unknown category: {record.category}')
    if record.subcategory not in category['subcategories']: raise ValueError(f'Unknown subcategory: {record.subcategory}')
    valid_groups={c['default_assignment_group'] for c in taxonomy['categories']}|{taxonomy['fallback_assignment_group']}
    if record.assignment_group and record.assignment_group not in valid_groups: raise ValueError(f'Unknown assignment group: {record.assignment_group}')
