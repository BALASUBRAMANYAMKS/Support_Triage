"""Grounded employee chatbot with own-ticket tools and confirmed ticket handoff."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import yaml

from . import db
from .llm_client import generate
from .pii import mask_sensitive_text

ROOT = Path(__file__).resolve().parents[1]
TICKET_RE = re.compile(r'\b(?:INC|REQ)\d{7}\b', re.I)
OUT_OF_SCOPE = (
    'leave days', 'payroll', 'salary', 'bonus', 'travel', 'hotel',
    'vacation', 'facilities', 'office supplies'
)
SECURITY = (
    'phishing', 'lost phone', 'lost device', 'stolen device',
    'suspicious login', 'malware', 'data exposure'
)
FOLLOW_UP_MARKERS = (
    'i tried everything', 'tried everything', 'still not working',
    'not working', 'does not work', "doesn't work", 'did not work',
    "didn't work", 'nothing works', 'still broken', 'same issue',
    'same problem', 'it still fails', 'still failing',
)


def _cfg():
    return yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8-sig'))


def _status_text(ticket):
    status = ticket.get('status')
    if status == 'New':
        return 'Received'
    if status == 'Assigned':
        return f"With the {ticket.get('assignment_group') or 'support'} team"
    if status == 'In Progress':
        return 'Being worked on'
    if status == 'Pending' and ticket.get('pending_reason') == 'Awaiting User':
        return 'Waiting for your reply'
    if status == 'Pending':
        return 'On hold, waiting on a third party'
    if status == 'Resolved':
        return 'Fixed: please confirm'
    return status or 'Status unavailable'


def _own_ticket(ticket_id, user_id):
    ticket = db.get_ticket(ticket_id)
    return ticket if ticket and ticket.get('requester', {}).get('requester_id') == user_id else None


def _status_answer(ticket):
    comments = db.comments_for(ticket['ticket_id'], False)
    if comments:
        comment = comments[-1]
        author = (
            'you'
            if comment.get('author_id') == ticket.get('requester', {}).get('requester_id')
            else f"{comment.get('author_name') or comment.get('author_id')}"
                 f" ({comment.get('author_role') or 'support user'})"
        )
        latest = f"Latest public comment from {author}: {comment['body']}"
    else:
        latest = 'There are no public comments yet.'
    group = ticket.get('assignment_group') or 'the service desk'
    assignee = ticket.get('assigned_to')
    handling = f"{group} (assigned to {assignee})" if assignee else group
    status = ticket.get('status')

    if status in ('Closed', 'Cancelled'):
        closed_at = ticket.get('closed_at') or ticket.get('cancelled_at')
        closed = f" on {closed_at}" if closed_at else ''
        outcome = ticket.get('resolution_notes') or ticket.get('resolution_code')
        result = f" Resolution: {outcome}." if outcome else ''
        return (
            f"{ticket['ticket_id']} is {status} with {handling}{closed}."
            f"{result} This ticket is no longer being worked. If the issue "
            f"continues, raise a new ticket. {latest}"
        )

    if status == 'Resolved':
        resolved_at = ticket.get('resolved_at')
        resolved = f" on {resolved_at}" if resolved_at else ''
        outcome = ticket.get('resolution_notes') or ticket.get('resolution_code')
        result = f" Resolution: {outcome}." if outcome else ''
        return (
            f"{ticket['ticket_id']} is resolved{resolved} by {handling}."
            f"{result} Please confirm the fix, or contact support to reopen "
            f"it if the issue remains. {latest}"
        )

    due = ticket.get('sla_resolution_due')
    resolution = (
        f"The current resolution target is {due}."
        if due else 'The resolution target will be set after triage.'
    )
    pending = (
        ' IT is waiting for your reply; add a public comment to continue.'
        if ticket.get('status') == 'Pending'
        and ticket.get('pending_reason') == 'Awaiting User'
        else (
            f" The ticket is pending ({ticket.get('pending_reason') or 'awaiting follow-up'})."
            if status == 'Pending' else ''
        )
    )
    return (
        f"{ticket['ticket_id']} is {_status_text(ticket)} with {handling}."
        f"{pending} {resolution} {latest}"
    )


def _ticket_context(message, history):
    """Attach a vague failure follow-up to only the immediately preceding issue."""
    text = message.strip()
    low = text.casefold()
    if any(marker in low for marker in FOLLOW_UP_MARKERS):
        ignored = {
            'yes', 'yes please', 'no', 'not now', 'thanks', 'thank you',
            'raise a ticket', 'create a ticket', 'make a ticket',
        }
        for item in reversed(history):
            if item.get('role') != 'user':
                continue
            previous = (item.get('content') or '').strip()
            if not previous or previous.casefold() in ignored:
                continue
            if any(marker in previous.casefold() for marker in FOLLOW_UP_MARKERS):
                continue
            return f"{previous}\n\nFollow-up: {text}", previous
    return text, text


def _make_preview(user, message, history, retrieval):
    context, issue_title = _ticket_context(message, history)
    summary = mask_sensitive_text(context)
    title = re.sub(r'\s+', ' ', mask_sensitive_text(issue_title)).strip()[:120]
    title = title or 'IT support request'

    ticket = {
        'ticket_id': 'INC0000000',
        'ticket_type': 'Incident',
        'channel': 'Chatbot',
        'created_at': '2026-10-24T09:00:00+05:30',
        'requester': {
            'requester_id': user['user_id'],
            'name': user['name'],
            'email': user['email'],
            'department': user['department'],
            'location': user['location'],
            'job_title': user['job_title'],
            'is_vip': bool(user['is_vip']),
        },
        'short_description': title,
        'description': summary,
        'category': None,
        'subcategory': None,
        'affected_ci': None,
        'impact': None,
        'urgency': None,
        'priority': None,
        'assignment_group': None,
        'assigned_to': None,
        'status': 'New',
        'pending_reason': None,
        'sla_response_due': None,
        'sla_resolution_due': None,
        'first_response_at': None,
        'resolved_at': None,
        'closed_at': None,
        'sla_breached': False,
        'resolution_code': None,
        'resolution_notes': None,
        'work_notes': [],
        'kb_references': [],
        'duplicate_of': None,
        'reassignment_count': 0,
        'reopen_count': 0,
        'csat_score': None,
        'tags': ['chatbot'],
    }

    try:
        from .triage import triage
        decision = triage(ticket, retrieval)
    except Exception:
        decision = None

    return {'ticket': ticket, 'decision': decision}


def _offer_ticket(user, message, history, retrieval, state):
    """Save a ticket draft so the user's confirmation can submit it."""
    context, _ = _ticket_context(message, history)
    if context.strip() == message.strip():
        # A generic failure without an issue context must not become a guessed
        # ticket for an arbitrary queue.
        generic = any(marker in message.casefold() for marker in FOLLOW_UP_MARKERS)
        if generic or len(message.strip().split()) < 5:
            state['pending_ticket'] = None
            return (
                "I’m not sure which issue you mean yet. Please describe the "
                "affected app or device and what is failing, and I’ll use that "
                "to answer or prepare the right ticket."
            )
    state['pending_ticket'] = _make_preview(user, message, history, retrieval)
    return (
        "I couldn't find a reliable answer in the published employee "
        "knowledge base. I prepared a ticket draft below. Review it and "
        "confirm if you want me to submit it."
    )


def chat(user, message, session_id=None, confirm_ticket=False, retrieval=None):
    from .retrieval import RetrievalService

    retrieval = retrieval or RetrievalService()
    session_id = session_id or str(uuid.uuid4())
    saved = db.get_chat_session(session_id, user['user_id'])
    state = saved['state'] if saved else {'history': [], 'pending_ticket': None}
    history = state.get('history', [])
    pending = state.get('pending_ticket')
    text = message.strip()
    low = text.casefold()
    citations = []
    outcome = None

    # A ticket is only created after an explicit confirmation of the preview.
    if pending and (
        confirm_ticket
        or low in ('yes', 'yes please', 'confirm', 'create it', 'submit')
        or low.startswith('yes, confirm')
    ):
        from .api import TicketCreateRequest, _create_ticket

        draft = pending['ticket']
        request = TicketCreateRequest(
            short_description=draft['short_description'],
            description=draft['description'],
            affected_ci=draft.get('affected_ci'),
            ticket_type=draft['ticket_type'],
            channel='Chatbot',
            requester_id=user['user_id'],
        )
        ticket = _create_ticket(request, user, user)
        state['pending_ticket'] = None
        reply = (
            f"Your ticket {ticket['ticket_id']} has been created and sent "
            f"for triage. It is currently {_status_text(ticket)}."
        )
        outcome = 'ticket_created'

    elif any(term in low for term in (
        'that worked', 'it worked', 'fixed now', 'that fixed it', 'problem solved'
    )):
        reply = 'Glad that fixed it. I logged this as resolved by self-service.'
        outcome = 'deflected'

    elif any(term in low for term in OUT_OF_SCOPE):
        reply = (
            "I can help with IT issues, but this looks like an HR, payroll, "
            "travel or facilities request. Please use your usual internal "
            "channel for that request; I won't create an IT ticket."
        )

    elif TICKET_RE.search(text):
        ticket_id = TICKET_RE.search(text).group(0).upper()
        ticket = _own_ticket(ticket_id, user['user_id'])
        reply = _status_answer(ticket) if ticket else "I can't find that ticket under your name."

    elif any(term in low for term in ('my open tickets', 'my tickets', 'any open ticket')):
        tickets = [
            ticket for ticket in db.list_tickets()
            if ticket.get('requester', {}).get('requester_id') == user['user_id']
            and ticket.get('status') not in ('Closed', 'Cancelled')
        ]
        reply = (
            'You have no open tickets.'
            if not tickets
            else 'Your open tickets: ' + '; '.join(
                f"{ticket['ticket_id']} {ticket['short_description']} — "
                f"{_status_text(ticket)}"
                for ticket in tickets[:10]
            )
        )

    elif pending and (low.startswith('no') or low.startswith('not now')):
        state['pending_ticket'] = None
        reply = (
            'Okay, I will not create a ticket. You can keep trying the steps '
            'or ask me another IT question.'
        )

    elif (
        any(term in low for term in (
            'raise a ticket', 'create a ticket', 'make a ticket',
            'still not working', 'talk to an agent'
        ))
        or any(term in low for term in SECURITY)
    ):
        preview = _make_preview(user, text, history, retrieval)
        state['pending_ticket'] = preview
        if any(term in low for term in SECURITY):
            reply = (
                'For safety, do not click the message or approve an unexpected '
                'sign-in. If a device is lost, lock it using the approved device '
                'portal. I prepared a Security ticket; please confirm before I '
                'submit it.'
            )
        else:
            reply = (
                'I prepared this ticket for you. Please review the summary and '
                'confirm if you want me to submit it.'
            )
        outcome = 'abandoned'

    else:
        retrieved = retrieval.chatbot(text, 5)
        threshold = float(_cfg()['retrieval']['chatbot_refusal_threshold'])

        if not retrieved or retrieved[0].get('rerank_score', -999) < threshold:
            reply = _offer_ticket(user, text, history, retrieval, state)
            outcome = 'abandoned'
        else:
            sources = []
            for item in retrieved:
                source_id = item['metadata'].get('source_id')
                title = item['metadata'].get('title') or source_id
                sources.append({
                    'id': source_id,
                    'title': title,
                    'text': item['text'],
                })

            context = '\n'.join(
                f"[{source['id']} {source['title']}]\n{source['text']}"
                for source in sources
            )
            turns = '\n'.join(
                f"{item['role']}: {mask_sensitive_text(item['content'])}"
                for item in history[-12:]
            )
            system = (ROOT / 'Prompts' / 'chat_system.md').read_text(
                encoding='utf-8-sig'
            )
            prompt = (
                f"{system}\nRecent conversation:\n{turns}\n"
                f"Question: {mask_sensitive_text(text)}\nKnowledge:\n{context}"
            )

            try:
                result = generate(
                    prompt,
                    params={'temperature': 0.2, 'max_tokens': 700},
                )
                reply = result.content.strip()
                allowed = {source['id'] for source in sources}
                mentioned = set(re.findall(r'\bKB\d{4}\b', reply))
                citations = []
                seen_citations = set()

                for source in sources:
                    kb_id = source['id']
                    if kb_id in mentioned and kb_id not in seen_citations:
                        citations.append({
                            'kb_id': kb_id,
                            'title': source['title'],
                         })
                        seen_citations.add(kb_id)

                if mentioned - allowed:
                    reply = _offer_ticket(user, text, history, retrieval, state)
                    citations = []
                    outcome = 'abandoned'
                elif not citations:
                    reply = _offer_ticket(user, text, history, retrieval, state)
                    outcome = 'abandoned'
                else:
                    outcome = None

            except Exception:
                reply = _offer_ticket(user, text, history, retrieval, state)
                outcome = 'abandoned'

    history.extend([
        {'role': 'user', 'content': text},
        {'role': 'assistant', 'content': reply},
    ])
    state['history'] = history[-12:]
    db.save_chat_session(session_id, user['user_id'], state, outcome)

    response = {
        'session_id': session_id,
        'reply': reply,
        'citations': citations,
    }
    if state.get('pending_ticket'):
        response['ticket_preview'] = state['pending_ticket']

    return response
