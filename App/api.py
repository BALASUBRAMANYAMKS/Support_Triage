"""FastAPI backend with mock-login roles and server-side ticket permissions."""
from __future__ import annotations
import csv, io, json
from datetime import datetime, timedelta, time as dtime
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import yaml
from . import db
from .rules import compute_priority
from .triage import triage, triage_batch
from .retrieval import RetrievalService

ROOT=__import__('pathlib').Path(__file__).resolve().parents[1]
app=FastAPI(title='Support Ticket Triage API',version='0.1.0')
_retrieval=None

class LoginRequest(BaseModel): user_id:str
class TicketCreateRequest(BaseModel):
    short_description:str=Field(min_length=1,max_length=120)
    description:str=Field(min_length=1)
    affected_ci:str|None=None
    impact_hint:Literal["I can't work","I can work with difficulty","Just a question"]|None=None
    ticket_type:Literal['Incident','Service Request']='Incident'
    channel:Literal['Portal','Chatbot','Phone','Email']='Portal'
    requester_id:str|None=None
class PatchTicketRequest(BaseModel):
    short_description:str|None=None
    description:str|None=None
    category:str|None=None
    subcategory:str|None=None
    affected_ci:str|None=None
    impact:Literal['High','Medium','Low']|None=None
    urgency:Literal['High','Medium','Low']|None=None
    priority:Literal['P1','P2','P3','P4']|None=None
    assignment_group:str|None=None
    assigned_to:str|None=None
    status:Literal['New','Assigned','In Progress','Pending','Resolved','Closed','Cancelled']|None=None
    pending_reason:Literal['Awaiting User','Awaiting Vendor','Awaiting Change']|None=None
    resolution_code:Literal['Solved (Permanent Fix)','Solved (Workaround)','User Error / Training','Not Reproducible','Duplicate','Cancelled by User']|None=None
    resolution_notes:str|None=None
    reason:str|None=None
    expected_updated_at:str|None=None
class CommentRequest(BaseModel): body:str=Field(min_length=1,max_length=4000); visibility:Literal['public','internal']='public'
class CancelRequest(BaseModel): reason:Literal['Duplicate','Raised by mistake','No longer needed','Spam / test']
class DeleteRequest(BaseModel): confirmation_ticket_id:str; reason:str=Field(min_length=3)
class OverrideRequest(BaseModel): field:str; value:str|int|float|None; reason:str=Field(min_length=3)
class BatchRequest(BaseModel): tickets:list[dict]
class ChatRequest(BaseModel): session_id:str|None=None; message:str=Field(min_length=1); confirm_ticket:bool=False


def retrieval_service():
    global _retrieval
    if _retrieval is None: _retrieval=RetrievalService()
    return _retrieval


def current_user(x_user_id:str|None=Header(default=None)):
    if not x_user_id: raise HTTPException(401,'Select a user using the mock login.')
    user=db.get_user(x_user_id)
    if not user: raise HTTPException(401,'Unknown mock user.')
    return user

def require(user,roles):
    if user['role'] not in roles: raise HTTPException(403,'This action is not allowed for your role.')

def owned(ticket,user): return ticket and ticket.get('requester',{}).get('requester_id')==user['user_id']

def accessible(ticket,user):
    if not ticket:return False
    if user['role']=='employee': return owned(ticket,user)
    if user['role']=='manager': return True
    return ticket.get('assignment_group') in (user.get('assignment_group'),'Service Desk L1')

def ensure_ticket(ticket_id,user):
    ticket=db.get_ticket(ticket_id)
    if not ticket or not accessible(ticket,user): raise HTTPException(404,"I can't find that ticket under your name.")
    return ticket

def _add_business_minutes(start,amount):
    cur=start; left=amount
    while left>0:
        if cur.weekday()>=5:
            day=cur.date()+timedelta(days=7-cur.weekday()); cur=datetime.combine(day,dtime(9),cur.tzinfo)
        elif cur.hour<9: cur=cur.replace(hour=9,minute=0,second=0,microsecond=0)
        elif cur.hour>=17:
            day=cur.date()+timedelta(days=1)
            while day.weekday()>=5: day+=timedelta(days=1)
            cur=datetime.combine(day,dtime(9),cur.tzinfo)
        available=int((datetime.combine(cur.date(),dtime(17),cur.tzinfo)-cur).total_seconds()//60)
        step=min(left,max(1,available)); cur+=timedelta(minutes=step); left-=step
    return cur

def _set_sla(ticket):
    if not ticket.get('priority'):
        ticket['sla_response_due']=ticket['sla_resolution_due']=None; return
    targets={'P1':(15,240),'P2':(30,480),'P3':(240,3*8*60),'P4':(8*60,5*8*60)}
    created=datetime.fromisoformat(ticket['created_at']); response,resolution=targets[ticket['priority']]
    ticket['sla_response_due']=_add_business_minutes(created,response).isoformat(timespec='seconds')
    ticket['sla_resolution_due']=_add_business_minutes(created,resolution).isoformat(timespec='seconds')

def _set_priority(ticket):
    if ticket.get('impact') and ticket.get('urgency'):
        ticket['priority']=compute_priority(ticket['impact'],ticket['urgency'])
        _set_sla(ticket)

def _create_ticket(data,user,requester):
    tid=db.next_ticket_id(data.ticket_type); created=datetime.now().astimezone().isoformat(timespec='seconds')
    ticket={'ticket_id':tid,'ticket_type':data.ticket_type,'channel':data.channel,'created_at':created,
      'requester':{k:requester[k] for k in ('user_id','name','email','department','location','job_title','is_vip')}|{'requester_id':requester['user_id']},
      'short_description':data.short_description,'description':data.description+(f'\nEmployee impact hint: {data.impact_hint}' if data.impact_hint else ''),'category':None,'subcategory':None,'affected_ci':data.affected_ci,
      'impact':None,'urgency':None,'priority':None,'assignment_group':None,'assigned_to':None,'status':'New','pending_reason':None,
      'sla_response_due':None,'sla_resolution_due':None,'first_response_at':None,'resolved_at':None,'closed_at':None,'sla_breached':False,
      'resolution_code':None,'resolution_notes':None,'work_notes':[],'kb_references':[],'duplicate_of':None,'reassignment_count':0,'reopen_count':0,'csat_score':None,'tags':['portal']}
    decision=triage(ticket,retrieval_service())
    ticket.update({k:decision[k] for k in ('category','subcategory','affected_ci','impact','urgency','priority','assignment_group','kb_references')})
    if decision['needs_human_review'] or decision['action']=='redirect': ticket['status']='New'
    else: ticket['status']='Assigned'
    _set_sla(ticket); db.save_ticket(ticket,created_by=user['user_id']); db.save_decision(tid,decision)
    return ticket

def _refresh_sla(ticket):
    now=datetime.now().astimezone(); breached=bool(ticket.get('sla_breached'))
    response_due=ticket.get('sla_response_due')
    if response_due:
        due=datetime.fromisoformat(response_due)
        first_response=datetime.fromisoformat(ticket['first_response_at']) if ticket.get('first_response_at') else now
        breached=breached or first_response>due
    resolution_due=ticket.get('sla_resolution_due')
    if resolution_due:
        due=datetime.fromisoformat(resolution_due)
        if ticket.get('resolved_at'):
            breached=breached or datetime.fromisoformat(ticket['resolved_at'])>due
        elif ticket.get('status') not in ('Closed','Cancelled','Pending'):
            breached=breached or now>due
    if breached!=bool(ticket.get('sla_breached')):
        old=bool(ticket.get('sla_breached')); ticket['sla_breached']=breached
        db.add_audit(ticket['ticket_id'],'sla_breached',old,breached,'system','SLA deadline crossed')
        return db.save_ticket(ticket)
    return ticket
@app.on_event('startup')
def startup(): db.init_db()

@app.get('/health')
def health(): return {'status':'ok','app':'Support Ticket Triage'}

@app.get('/login/options')
def login_options():
    db.init_db(); return db.users_for_login()

@app.post('/login')
def login(payload:LoginRequest):
    db.init_db(); user=db.get_user(payload.user_id)
    if not user: raise HTTPException(404,'User not found')
    return {k:user[k] for k in ('user_id','name','role','assignment_group')}

@app.get('/me')
def me(user=Header(default=None,alias='X-User-ID')):
    return current_user(user)

@app.get('/tickets')
def list_ticket_route(status:str|None=None,priority:str|None=None,group:str|None=None,assigned_to_me:bool=False,unassigned:bool=False,category:str|None=None,search:str|None=None,assigned_to:str|None=None,from_date:str|None=None,to_date:str|None=None,sla_at_risk:bool=False,breached:bool=False,page:int=1,page_size:int=25,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); rows=[]; now=datetime.now().astimezone()
    decisions={}
    accepted_ids=set()
    overridden_ids=set()
    if actor['role'] in ('agent','manager'):
        decisions={r['ticket_id']:json.loads(r['decision_json']) for r in db.all_decisions()}
        accepted_ids=db.accepted_triage_ticket_ids()
        overridden_ids={r['ticket_id'] for r in db.all_overrides()}
    for t in db.list_tickets():
        t=_refresh_sla(t)
        if not accessible(t,actor): continue
        if actor['role'] in ('agent','manager'):
            t['triage_decision']=decisions.get(t['ticket_id'])
            if t['triage_decision'] and t['ticket_id'] in accepted_ids:
                t['triage_decision']['needs_human_review']=False
                t['triage_decision']['human_reviewed']=True
            elif t['triage_decision'] and t['ticket_id'] in overridden_ids:
                t['triage_decision']['needs_human_review']=False
                t['triage_decision']['human_reviewed']=True
                t['triage_decision']['review_outcome']='overridden'
        if actor['role']=='agent' and not group and t.get('assignment_group') not in (actor.get('assignment_group'),'Service Desk L1'): continue
        if status and status!='Open' and t.get('status')!=status: continue
        if status=='Open' and t.get('status') in ('Resolved','Closed','Cancelled'): continue
        if priority and t.get('priority') not in priority.split(','): continue
        if group and t.get('assignment_group')!=group: continue
        if assigned_to_me and t.get('assigned_to')!=actor['name']: continue
        if assigned_to and t.get('assigned_to')!=assigned_to: continue
        if unassigned and t.get('assigned_to'): continue
        if category and t.get('category')!=category: continue
        if search and search.casefold() not in (t.get('ticket_id','')+' '+t.get('short_description','')+' '+t.get('description','')).casefold(): continue
        created_day=(t.get('created_at') or '')[:10]
        if from_date and created_day<from_date: continue
        if to_date and created_day>to_date: continue
        if breached and (not t.get('sla_breached') or t.get('status') in ('Resolved','Closed','Cancelled','Pending')): continue
        if sla_at_risk:
            due=t.get('sla_resolution_due')
            if not due or t.get('status')=='Pending': continue
            begin=datetime.fromisoformat(t['created_at']); target=datetime.fromisoformat(due); span=max(1,(target-begin).total_seconds())
            if target<=now or (target-now).total_seconds()/span>=.25: continue
        rows.append(t)
    rows.sort(key=lambda t:(t.get('sla_resolution_due') or '9999',t.get('created_at','')))
    page=max(1,page); page_size=max(1,min(page_size,100)); start=(page-1)*page_size
    return {'items':rows[start:start+page_size],'total':len(rows),'page':page,'page_size':page_size}

@app.post('/tickets')
def create_ticket_route(payload:TicketCreateRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user)
    if actor['role']=='employee':
        if payload.requester_id and payload.requester_id!=actor['user_id']: raise HTTPException(403,'Employees can only create their own tickets.')
        requester=actor
    else:
        require(actor,('agent','manager'))
        if not payload.requester_id: raise HTTPException(400,'Choose the employee who reported the issue.')
        requester=db.get_user(payload.requester_id)
        if not requester or requester['role']!='employee': raise HTTPException(400,'Requester must be an employee.')
    return _create_ticket(payload,actor,requester)

@app.get('/tickets/{ticket_id}')
def ticket_detail(ticket_id:str,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); ticket=ensure_ticket(ticket_id,actor); ticket=_refresh_sla(ticket)
    ticket['comments']=db.comments_for(ticket_id,include_internal=actor['role']!='employee')
    ticket['audit_trail']=db.audit_for(ticket_id) if actor['role']!='employee' else []
    ticket['triage_decision']=db.decision_for(ticket_id) if actor['role']!='employee' else None
    ticket['overrides']=db.overrides_for(ticket_id) if actor['role']!='employee' else []
    if ticket['triage_decision'] and db.triage_was_accepted(ticket_id):
        ticket['triage_decision']['needs_human_review']=False
        ticket['triage_decision']['human_reviewed']=True
    elif ticket['triage_decision'] and ticket['overrides']:
        ticket['triage_decision']['needs_human_review']=False
        ticket['triage_decision']['human_reviewed']=True
        ticket['triage_decision']['review_outcome']='overridden'
    return ticket

@app.patch('/tickets/{ticket_id}')
def update_ticket(ticket_id:str,payload:PatchTicketRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); ticket=ensure_ticket(ticket_id,actor); changes=payload.model_dump(exclude_unset=True); reason=changes.pop('reason',None); expected=changes.pop('expected_updated_at',None)
    previous_status=ticket.get('status'); previous_group=ticket.get('assignment_group'); previous_assignee=ticket.get('assigned_to')
    if expected and expected!=ticket.get('updated_at'): raise HTTPException(409,'Ticket changed since it was opened. Reload before saving.')
    if actor['role']=='employee':
        allowed=owned(ticket,actor) and ((ticket['status']=='New' and set(changes).issubset({'short_description','description'})) or (ticket['status']=='Resolved' and changes=={'status':'In Progress'}))
        if not allowed: raise HTTPException(403,'Employees can edit their description only while the ticket is New.')
    else: require(actor,('agent','manager'))
    if changes.get('assigned_to') and (
        changes['assigned_to'] != ticket.get('assigned_to')
        or changes.get('assignment_group', ticket.get('assignment_group')) != ticket.get('assignment_group')
    ):
        target_group=changes.get('assignment_group',ticket.get('assignment_group'))
        matching_agent=any(
            person.get('role')=='agent'
            and person.get('name')==changes['assigned_to']
            and person.get('assignment_group')==target_group
            for person in db.users_for_login()
        )
        if not matching_agent:
            raise HTTPException(400,'Choose an agent who belongs to the selected assignment group, or leave the ticket unassigned in that group queue.')
    for field in ('category','priority','assignment_group'):
        if field in changes and changes[field]!=ticket.get(field) and not reason: raise HTTPException(400,f'A reason is required to change {field}.')
    if 'impact' in changes or 'urgency' in changes:
        ticket.update({k:v for k,v in changes.items() if k in ('impact','urgency')}); _set_priority(ticket)
    if 'status' in changes:
        new=changes['status']; old=ticket['status']
        if new=='Cancelled': raise HTTPException(400,'Use the cancel action so a cancel reason is recorded.')
        transitions={'New':{'Assigned','Cancelled'},'Assigned':{'In Progress','Pending','Resolved','Cancelled'},'In Progress':{'Pending','Resolved','Cancelled'},'Pending':{'In Progress','Resolved'},'Resolved':{'Closed','In Progress'},'Closed':set(),'Cancelled':set()}
        if new!=old and new not in transitions.get(old,set()): raise HTTPException(400,f'Invalid status transition: {old} to {new}.')
        if new!=old and new=='Resolved' and (not changes.get('resolution_notes',ticket.get('resolution_notes')) or not changes.get('resolution_code',ticket.get('resolution_code'))): raise HTTPException(400,'Resolution code and notes are required to resolve a ticket.')
        if new=='Pending' and not changes.get('pending_reason',ticket.get('pending_reason')): raise HTTPException(400,'Pending reason is required.')
        if new!=old and old=='Resolved' and new=='In Progress':
            previous_reopen_count=ticket.get('reopen_count',0)
            resolved=datetime.fromisoformat(ticket['resolved_at']) if ticket.get('resolved_at') else datetime.now().astimezone()-timedelta(days=4)
            if datetime.now().astimezone()-resolved>timedelta(days=3): raise HTTPException(400,'The three-day reopen window has passed.')
            ticket['reopen_count']+=1
            db.add_audit(ticket_id,'reopen_count',previous_reopen_count,ticket['reopen_count'],actor['user_id'],'Ticket reopened')
        if new=='Pending':
            ticket['pending_reason']=changes.get('pending_reason')
            ticket['status']='Pending'
        if new!=old and new=='Resolved': ticket['resolved_at']=datetime.now().astimezone().isoformat(timespec='seconds')
        if new!=old and new=='Closed': ticket['closed_at']=datetime.now().astimezone().isoformat(timespec='seconds')
    old_group=ticket.get('assignment_group')
    for field,value in changes.items():
        if field in ('impact','urgency'): continue
        if field=='status' and value=='Pending': continue
        if field in ticket: ticket[field]=value
    if 'assignment_group' in changes and changes['assignment_group']!=old_group:
        old_count=ticket.get('reassignment_count',0); ticket['reassignment_count']=old_count+1
        db.add_audit(ticket_id,'reassignment_count',old_count,ticket['reassignment_count'],actor['user_id'],reason)
    if ticket.get('status')=='Pending' and ticket.get('pending_reason'): pass
    if ticket.get('status')=='Resolved' and not ticket.get('resolved_at'): ticket['resolved_at']=datetime.now().astimezone().isoformat(timespec='seconds')
    for field,value in changes.items():
        old=db.get_ticket(ticket_id).get(field)
        if old!=value: db.add_audit(ticket_id,field,old,value,actor['user_id'],reason)
    saved=db.save_ticket(ticket,created_by=actor['user_id'])
    requester_id=ticket.get('requester',{}).get('requester_id')
    if requester_id and requester_id!=actor['user_id']:
        updates=[]
        if ticket.get('status')!=previous_status:
            updates.append(f"status changed to {ticket['status']}")
        if ticket.get('assignment_group')!=previous_group:
            updates.append(f"moved to {ticket.get('assignment_group') or 'an unassigned queue'}")
        if ticket.get('assigned_to')!=previous_assignee:
            updates.append(f"assigned to {ticket.get('assigned_to') or 'the team queue'}")
        if updates:
            from .db import connect,now
            message=('Your ticket has been marked resolved. Please review the update and rate the outcome.'
                     if ticket.get('status')=='Resolved' and previous_status!='Resolved'
                     else 'Ticket update: '+', '.join(updates)+'.')
            with connect() as con:
                con.execute('INSERT INTO notifications(user_id,ticket_id,text,created_at) VALUES(?,?,?,?)',(requester_id,ticket_id,message,now()))
    return saved

@app.post('/tickets/{ticket_id}/comments')
def add_ticket_comment(ticket_id:str,payload:CommentRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); ticket=ensure_ticket(ticket_id,actor)
    if actor['role']=='employee' and (not owned(ticket,actor) or payload.visibility!='public'): raise HTTPException(403,'Employees can add public comments only to their own tickets.')
    if actor['role'] not in ('employee','agent','manager'): raise HTTPException(403,'Not allowed.')
    comment_id=db.add_comment(ticket_id,actor['user_id'],payload.visibility,payload.body)
    if actor['role'] in ('agent','manager') and payload.visibility=='public' and not ticket.get('first_response_at'):
        timestamp=datetime.now().astimezone().isoformat(timespec='seconds')
        ticket['first_response_at']=timestamp
        db.add_audit(ticket_id,'first_response_at',None,timestamp,actor['user_id'],'First public support response')
        _set_ticket=db.save_ticket(ticket,created_by=actor['user_id'])
    if payload.visibility=='public':
        requester_id=ticket['requester']['requester_id']
        if requester_id!=actor['user_id']:
            from .db import connect,now
            with connect() as con: con.execute('INSERT INTO notifications(user_id,ticket_id,text,created_at) VALUES(?,?,?,?)',(requester_id,ticket_id,'New public comment on '+ticket_id,now()))
    db.add_audit(ticket_id,'comment',None,comment_id,actor['user_id'],'Comment added')
    return {'comment_id':comment_id}

@app.post('/tickets/{ticket_id}/cancel')
def cancel_ticket(ticket_id:str,payload:CancelRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); ticket=ensure_ticket(ticket_id,actor)
    if actor['role']=='employee' and (not owned(ticket,actor) or ticket['status'] not in ('New','Assigned')): raise HTTPException(403,'You can cancel your own ticket only while it is New or Assigned.')
    if actor['role'] not in ('employee','agent','manager'): raise HTTPException(403,'Not allowed.')
    old=ticket['status']; ticket['status']='Cancelled'; ticket['cancel_reason']=payload.reason; ticket['cancelled_at']=datetime.now().astimezone().isoformat(timespec='seconds')
    db.add_audit(ticket_id,'status',old,'Cancelled',actor['user_id'],payload.reason); db.add_audit(ticket_id,'cancel_reason',None,payload.reason,actor['user_id'],payload.reason); db.add_audit(ticket_id,'cancelled_at',None,ticket['cancelled_at'],actor['user_id'],payload.reason); return db.save_ticket(ticket,created_by=actor['user_id'])

@app.delete('/tickets/{ticket_id}')
def permanently_delete(ticket_id:str,payload:DeleteRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); require(actor,('manager',)); ticket=db.get_ticket(ticket_id)
    if not ticket or ticket['status']!='Cancelled': raise HTTPException(404,'Only a cancelled ticket can be permanently deleted.')
    if payload.confirmation_ticket_id!=ticket_id: raise HTTPException(400,'Typed ticket ID does not match.')
    # Remove the source from the persistent ticket collection as well as SQLite.
    try: retrieval_service().collections['tickets'].delete(where={'source_id':ticket_id})
    except Exception: pass
    db.delete_cancelled(ticket_id,actor['user_id'],payload.reason); return {'deleted':ticket_id}

@app.post('/tickets/{ticket_id}/accept-triage')
def accept_triage(ticket_id:str,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); require(actor,('agent','manager')); ticket=ensure_ticket(ticket_id,actor)
    decision=db.decision_for(ticket_id)
    if not decision: raise HTTPException(404,'No triage decision is stored for this ticket.')
    old=dict(ticket)
    decision['needs_human_review']=False
    decision['human_reviewed']=True
    decision['reviewed_by']=actor['user_id']
    decision['reviewed_at']=datetime.now().astimezone().isoformat(timespec='seconds')
    decision['review_outcome']='accepted'
    db.save_decision(ticket_id,decision)
    db.add_audit(ticket_id,'triage_review','Needs review','Reviewed',actor['user_id'],'Accepted AI triage')
    for field in ('category','subcategory','affected_ci','impact','urgency','priority','assignment_group','kb_references'):
        ticket[field]=decision.get(field)
    if decision.get('category')=='Security':
        ticket['assignment_group']='Security Operations (SOC)'
        if ticket.get('priority') in ('P3','P4'): ticket['priority']='P2'
    if ticket.get('status')=='New' and decision.get('action')!='redirect': ticket['status']='Assigned'
    _set_sla(ticket)
    for field in ('category','subcategory','affected_ci','impact','urgency','priority','assignment_group','kb_references','status'):
        if old.get(field)!=ticket.get(field): db.add_audit(ticket_id,field,old.get(field),ticket.get(field),actor['user_id'],'Accepted AI triage')
    db.save_ticket(ticket,created_by=actor['user_id'])
    return ticket


@app.post('/tickets/{ticket_id}/override')
def override_ticket(ticket_id:str,payload:OverrideRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); require(actor,('agent','manager')); ticket=ensure_ticket(ticket_id,actor)
    if ticket.get('status') in ('Resolved','Closed','Cancelled'):
        raise HTTPException(400,'Overrides are disabled for resolved, closed, or cancelled tickets.')
    allowed={'category','subcategory','impact','urgency','priority','assignment_group','action'}
    if payload.field not in allowed: raise HTTPException(400,'That field cannot be overridden.')
    decision=db.decision_for(ticket_id) or {}; ai_value=decision.get(payload.field)
    taxonomy=json.loads((ROOT/'schemas'/'taxonomy.json').read_text(encoding='utf-8-sig'))
    allowed_values={
        'category':{c['name'] for c in taxonomy['categories']},
        'subcategory':{sub for c in taxonomy['categories'] for sub in c.get('subcategories',[])},
        'impact':{'High','Medium','Low'},
        'urgency':{'High','Medium','Low'},
        'priority':{'P1','P2','P3','P4'},
        'assignment_group':{c['default_assignment_group'] for c in taxonomy['categories']}|{taxonomy['fallback_assignment_group']},
        'action':{'route','request_clarification','escalate','auto_resolve','redirect'},
    }
    if payload.value not in allowed_values[payload.field]:
        choices=', '.join(sorted(allowed_values[payload.field]))
        raise HTTPException(400,f"Invalid {payload.field} value. Choose one of: {choices}.")
    db.save_override(ticket_id,payload.field,ai_value,payload.value,actor['user_id'],payload.reason)
    if payload.field in ('impact','urgency'): ticket[payload.field]=payload.value; _set_priority(ticket)
    elif payload.field in ticket: ticket[payload.field]=payload.value
    decision[payload.field]=payload.value
    if payload.field in ('impact','urgency'):
        decision['priority']=ticket.get('priority')
    decision['needs_human_review']=False
    decision['human_reviewed']=True
    decision['review_outcome']='overridden'
    decision['reviewed_by']=actor['user_id']
    decision['reviewed_at']=datetime.now().astimezone().isoformat(timespec='seconds')
    db.save_decision(ticket_id,decision)
    db.add_audit(ticket_id,payload.field,ai_value,payload.value,actor['user_id'],payload.reason)
    db.save_ticket(ticket,created_by=actor['user_id']); return {'ticket_id':ticket_id,'field':payload.field,'ai_value':ai_value,'agent_value':payload.value}

@app.post('/triage/batch')
def batch_triage(payload:BatchRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); require(actor,('agent','manager'))
    return {'decisions':triage_batch(payload.tickets,retrieval_service())}

@app.get('/insights')
def insights(user=Header(default=None,alias='X-User-ID'),group:str|None=None,category:str|None=None,priority:str|None=None,start_date:str|None=None,end_date:str|None=None):
    actor=current_user(user); require(actor,('agent','manager'))
    if actor['role']=='agent' and not group: group=actor.get('assignment_group')
    today=datetime.now().astimezone().date(); start=datetime.fromisoformat(start_date).date() if start_date else today-timedelta(days=29); end=datetime.fromisoformat(end_date).date() if end_date else today
    rows=[_refresh_sla(t) for t in db.list_tickets()]; rows=[t for t in rows if (not group or t.get('assignment_group')==group) and (not category or t.get('category')==category) and (not priority or t.get('priority')==priority) and start.isoformat()<=(t.get('created_at') or '')[:10]<=(end.isoformat())]
    opened=[t for t in rows if t.get('status') not in ('Resolved','Closed','Cancelled')]
    def at_risk(t):
        due=t.get('sla_resolution_due')
        if not due or t.get('status')=='Pending': return False
        begin=datetime.fromisoformat(t['created_at']); target=datetime.fromisoformat(due); now=datetime.now().astimezone()
        span=max(1,(target-begin).total_seconds()); return target>now and (target-now).total_seconds()/span<.25
    by_status={state:sum(t.get('status')==state for t in rows) for state in ('New','Assigned','In Progress','Pending','Resolved','Closed','Cancelled')}
    by_category={}
    for t in rows: by_category[t.get('category') or 'Unclassified']=by_category.get(t.get('category') or 'Unclassified',0)+1
    grouped={}; unassigned={}; agents={}; week_start=today-timedelta(days=today.weekday())
    for t in rows:
        g=t.get('assignment_group') or 'Unassigned'; grouped.setdefault(g,{'P1':0,'P2':0,'P3':0,'P4':0})
        if t.get('status') not in ('Resolved','Closed','Cancelled') and t.get('priority') in grouped[g]: grouped[g][t['priority']]+=1
        if t.get('status') not in ('Resolved','Closed','Cancelled') and not t.get('assigned_to'):
            item=unassigned.setdefault(g,{'count':0,'oldest_created_at':t.get('created_at')}); item['count']+=1
            if t.get('created_at','')<item['oldest_created_at']: item['oldest_created_at']=t.get('created_at')
        name=t.get('assigned_to')
        if name:
            a=agents.setdefault(name,{'group':g,'open':0,'p1_p2':0,'at_risk':0,'breached':0,'pending':0,'resolved_this_week':0,'resolution_hours':[]})
            if t.get('status') not in ('Resolved','Closed','Cancelled'):
                a['open']+=1; a['p1_p2']+=int(t.get('priority') in ('P1','P2')); a['at_risk']+=int(at_risk(t)); a['breached']+=int(bool(t.get('sla_breached')) and t.get('status')!='Pending'); a['pending']+=int(t.get('status')=='Pending')
            resolved=t.get('resolved_at')
            if resolved:
                rd=datetime.fromisoformat(resolved)
                if rd.date()>=week_start: a['resolved_this_week']+=1
                a['resolution_hours'].append(max(0,(rd-datetime.fromisoformat(t['created_at'])).total_seconds()/3600))
    for a in agents.values():
        vals=a.pop('resolution_hours'); a['average_resolution_hours']=round(sum(vals)/len(vals),2) if vals else None
    unassigned_rows=[]
    for g,item in unassigned.items():
        age=max(0,(today-datetime.fromisoformat(item['oldest_created_at']).date()).days); unassigned_rows.append({'group':g,'count':item['count'],'oldest_age_days':age})
    dates=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    created_counts={d:0 for d in dates}; resolved_counts={d:0 for d in dates}
    for t in rows:
        d=(t.get('created_at') or '')[:10]
        if d in created_counts: created_counts[d]+=1
        d=(t.get('resolved_at') or '')[:10]
        if d in resolved_counts: resolved_counts[d]+=1
    compliance={p:{'resolved':0,'within_sla':0} for p in ('P1','P2','P3','P4')}
    age_bins={'under_1_day':0,'1_to_3_days':0,'3_to_7_days':0,'over_7_days':0}
    for t in rows:
        if t.get('priority') in compliance and t.get('resolved_at') and t.get('sla_resolution_due'):
            c=compliance[t['priority']]; c['resolved']+=1; c['within_sla']+=int(t['resolved_at']<=t['sla_resolution_due'])
        if t in opened:
            age=(datetime.now().astimezone()-datetime.fromisoformat(t['created_at'])).total_seconds()/86400
            key='under_1_day' if age<1 else '1_to_3_days' if age<3 else '3_to_7_days' if age<7 else 'over_7_days'; age_bins[key]+=1
    for c in compliance.values(): c['percent']=round(100*c['within_sla']/c['resolved'],1) if c['resolved'] else None
    sessions=db.chat_sessions(); since=datetime.now().astimezone()-timedelta(days=7); recent=[s for s in sessions if datetime.fromisoformat(s['started_at']).astimezone()>=since]
    deflection=round(sum(s.get('outcome')=='deflected' for s in recent)/len(recent),3) if recent else 0.0
    decisions=db.all_decisions(); override_tickets={r['ticket_id'] for r in db.all_overrides() if r['field'] in ('category','priority','assignment_group')}
    agreement=round(sum(d['ticket_id'] not in override_tickets for d in decisions)/len(decisions),3) if decisions else 0.0
    ratings=[t.get('csat_score') for t in rows if t.get('csat_score') is not None]
    kpis={'csat_average':round(sum(ratings)/len(ratings),2) if ratings else None,'csat_responses':len(ratings),'open':len(opened),'unassigned':sum(x['count'] for x in unassigned.values()),'p1_p2_open':sum(t.get('priority') in ('P1','P2') for t in opened),'at_risk':sum(at_risk(t) for t in opened),'breached':sum(bool(t.get('sla_breached')) and t.get('status') not in ('Resolved','Closed','Cancelled','Pending') for t in rows),'resolved_today':sum((t.get('resolved_at') or '')[:10]==today.isoformat() for t in rows),'deflection_rate':deflection,'ai_agreement':agreement}
    return {'date_range':{'start':start.isoformat(),'end':end.isoformat()},'kpis':kpis,'tickets_by_status':by_status,'category_mix':by_category,'who_is_handling_what':agents,'workload_by_group':grouped,'unassigned_by_group':unassigned_rows,'created_vs_resolved':{'dates':dates,'created':[created_counts[d] for d in dates],'resolved':[resolved_counts[d] for d in dates]},'sla_compliance':compliance,'ticket_aging':age_bins}

@app.get('/export/tickets.csv')
def export_csv(user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); require(actor,('agent','manager'))
    output=io.StringIO(); fields=['ticket_id','short_description','priority','category','assignment_group','assigned_to','status','created_at','sla_resolution_due']
    writer=csv.DictWriter(output,fieldnames=fields); writer.writeheader()
    for row in db.list_tickets():
        row=_refresh_sla(row)
        if accessible(row,actor): writer.writerow({k:row.get(k) for k in fields})
    output.seek(0); return StreamingResponse(iter([output.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=tickets.csv'})

@app.post('/chat')
def chat_route(payload:ChatRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user)
    if actor['role']!='employee': raise HTTPException(403,'The employee chatbot is available to employees.')
    from .chatbot import chat
    return chat(actor,payload.message,payload.session_id,payload.confirm_ticket,retrieval_service())

class CSATRequest(BaseModel):
    score:int=Field(ge=1,le=5)

@app.post('/tickets/{ticket_id}/csat')
def submit_csat(ticket_id:str,payload:CSATRequest,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user); ticket=ensure_ticket(ticket_id,actor)
    if actor['role']!='employee' or not owned(ticket,actor): raise HTTPException(403,'Only the requester can rate this ticket.')
    if ticket.get('status') not in ('Resolved','Closed'): raise HTTPException(400,'You can rate a ticket after it is resolved.')
    if ticket.get('csat_score') is not None: raise HTTPException(409,'A rating has already been recorded for this ticket.')
    ticket['csat_score']=payload.score
    db.add_audit(ticket_id,'csat_score',None,payload.score,actor['user_id'],'Employee satisfaction rating')
    db.save_ticket(ticket,created_by=actor['user_id'])
    return {'ticket_id':ticket_id,'csat_score':payload.score}

@app.get('/notifications')
def list_notifications(unread_only:bool=False,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user)
    return db.notifications_for(actor['user_id'],unread_only)

@app.post('/notifications/{notification_id}/read')
def read_notification(notification_id:int,user=Header(default=None,alias='X-User-ID')):
    actor=current_user(user)
    if not db.mark_notification_read(notification_id,actor['user_id']): raise HTTPException(404,'Notification not found.')
    return {'read':True,'notification_id':notification_id}
