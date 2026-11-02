"""SQLite store for synthetic tickets, users, decisions, comments and audit history."""
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]

def database_path():
    cfg=yaml.safe_load((ROOT/'config.yaml').read_text(encoding='utf-8-sig'))
    path=ROOT/cfg['app']['database_path']; path.parent.mkdir(parents=True,exist_ok=True); return path

def connect():
    con=sqlite3.connect(database_path(),timeout=30); con.row_factory=sqlite3.Row; con.execute('PRAGMA foreign_keys=ON'); return con

def now(): return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')

def init_db():
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY,name TEXT,email TEXT,department TEXT,location TEXT,job_title TEXT,is_vip INTEGER,role TEXT,assignment_group TEXT);
        CREATE TABLE IF NOT EXISTS tickets(ticket_id TEXT PRIMARY KEY,requester_id TEXT,payload_json TEXT NOT NULL,created_by TEXT,updated_at TEXT NOT NULL,cancel_reason TEXT,cancelled_at TEXT);
        CREATE TABLE IF NOT EXISTS comments(comment_id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id TEXT NOT NULL,author_id TEXT NOT NULL,visibility TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id TEXT NOT NULL,field TEXT NOT NULL,old_value TEXT,new_value TEXT,changed_by TEXT NOT NULL,changed_at TEXT NOT NULL,reason TEXT);
        CREATE TABLE IF NOT EXISTS triage_decisions(ticket_id TEXT PRIMARY KEY,decision_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS overrides(id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id TEXT NOT NULL,field TEXT NOT NULL,ai_value TEXT,agent_value TEXT,agent_id TEXT NOT NULL,reason TEXT,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chat_sessions(session_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,started_at TEXT NOT NULL,messages_json TEXT NOT NULL,outcome TEXT,feedback TEXT);
        CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,ticket_id TEXT NOT NULL,text TEXT NOT NULL,read INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
        ''')
        data=json.loads((ROOT/'data'/'users.json').read_text(encoding='utf-8-sig'))
        roster=[u for group in ('employees','agents','managers') for u in data[group]]
        for u in roster:
            con.execute('''INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                  name=excluded.name,email=excluded.email,department=excluded.department,
                  location=excluded.location,job_title=excluded.job_title,is_vip=excluded.is_vip,
                  role=excluded.role,assignment_group=excluded.assignment_group''',
                (u['user_id'],u['name'],u['email'],u['department'],u['location'],u['job_title'],int(u['is_vip']),u['role'],u.get('assignment_group')))
        roster_ids=[u['user_id'] for u in roster]
        placeholders=','.join('?' for _ in roster_ids)
        con.execute(f'DELETE FROM users WHERE user_id NOT IN ({placeholders})',roster_ids)
        if con.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]==0:
            path=ROOT/'data'/'tickets_history.jsonl'
            with path.open(encoding='utf-8-sig') as source:
                for line in source:
                    t=json.loads(line); ts=t['created_at']
                    con.execute('INSERT OR IGNORE INTO tickets(ticket_id,requester_id,payload_json,created_by,updated_at) VALUES(?,?,?,?,?)',(t['ticket_id'],t['requester']['requester_id'],json.dumps(t,ensure_ascii=False),t['requester']['requester_id'],t.get('closed_at') or ts))

def get_user(user_id):
    with connect() as con:
        row=con.execute('SELECT * FROM users WHERE user_id=?',(user_id,)).fetchone()
        return dict(row) if row else None

def users_for_login():
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT user_id,name,role,department,job_title,assignment_group FROM users ORDER BY role,name')]

def get_ticket(ticket_id):
    with connect() as con:
        row=con.execute('SELECT payload_json,updated_at,created_by,cancel_reason,cancelled_at FROM tickets WHERE ticket_id=?',(ticket_id,)).fetchone()
        if not row:return None
        result=json.loads(row['payload_json']); result.update({k:row[k] for k in ('updated_at','created_by','cancel_reason','cancelled_at')})
        return result

def save_ticket(ticket,created_by=None,reason=None):
    ts=now(); ticket=dict(ticket); ticket['updated_at']=ts
    requester_id=(ticket.get('requester') or {}).get('requester_id')
    with connect() as con:
        existing=con.execute('SELECT 1 FROM tickets WHERE ticket_id=?',(ticket['ticket_id'],)).fetchone()
        con.execute('''INSERT INTO tickets(ticket_id,requester_id,payload_json,created_by,updated_at,cancel_reason,cancelled_at)
          VALUES(?,?,?,?,?,?,?) ON CONFLICT(ticket_id) DO UPDATE SET requester_id=excluded.requester_id,payload_json=excluded.payload_json,updated_at=excluded.updated_at,cancel_reason=excluded.cancel_reason,cancelled_at=excluded.cancelled_at''',
          (ticket['ticket_id'],requester_id,json.dumps(ticket,ensure_ascii=False),created_by or ticket.get('created_by'),ts,ticket.get('cancel_reason'),ticket.get('cancelled_at')))
        if not existing and created_by:
            con.execute('INSERT INTO audit_log(ticket_id,field,old_value,new_value,changed_by,changed_at,reason) VALUES(?,?,?,?,?,?,?)',(ticket['ticket_id'],'created','',ticket['ticket_id'],created_by,ts,'Ticket created'))
    return ticket

def next_ticket_id(ticket_type):
    prefix='INC' if ticket_type=='Incident' else 'REQ'
    with connect() as con:
        rows=con.execute('SELECT ticket_id FROM tickets WHERE ticket_id LIKE ?',(prefix+'%',)).fetchall()
    max_num=max((int(r['ticket_id'][3:]) for r in rows if r['ticket_id'][3:].isdigit()),default=0)
    return f'{prefix}{max_num+1:07d}'

def list_tickets():
    with connect() as con:
        rows=con.execute('SELECT payload_json,updated_at,created_by,cancel_reason,cancelled_at FROM tickets').fetchall()
    results=[]
    for row in rows:
        item=json.loads(row['payload_json']); item.update({k:row[k] for k in ('updated_at','created_by','cancel_reason','cancelled_at')}); results.append(item)
    return results

def add_audit(ticket_id,field,old_value,new_value,changed_by,reason=None):
    with connect() as con:
        con.execute('INSERT INTO audit_log(ticket_id,field,old_value,new_value,changed_by,changed_at,reason) VALUES(?,?,?,?,?,?,?)',(ticket_id,field,json.dumps(old_value,ensure_ascii=False),json.dumps(new_value,ensure_ascii=False),changed_by,now(),reason))

def audit_for(ticket_id):
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM audit_log WHERE ticket_id=? ORDER BY changed_at,id',(ticket_id,))]


def triage_was_accepted(ticket_id):
    with connect() as con:
        return con.execute(
            "SELECT 1 FROM audit_log WHERE ticket_id=? AND reason='Accepted AI triage' LIMIT 1",
            (ticket_id,),
        ).fetchone() is not None


def accepted_triage_ticket_ids():
    with connect() as con:
        return {r['ticket_id'] for r in con.execute(
            "SELECT DISTINCT ticket_id FROM audit_log WHERE reason='Accepted AI triage'"
        )}

def add_comment(ticket_id,author_id,visibility,body):
    with connect() as con:
        cur=con.execute('INSERT INTO comments(ticket_id,author_id,visibility,body,created_at) VALUES(?,?,?,?,?)',(ticket_id,author_id,visibility,body,now()))
        return cur.lastrowid

def comments_for(ticket_id,include_internal=False):
    with connect() as con:
        sql=("SELECT c.*,COALESCE(u.name,c.author_id) AS author_name,u.role AS author_role "
             "FROM comments c LEFT JOIN users u ON u.user_id=c.author_id WHERE c.ticket_id=?")
        if not include_internal:
            sql += " AND c.visibility='public'"
        sql += ' ORDER BY c.created_at,c.comment_id'
        return [dict(r) for r in con.execute(sql,(ticket_id,))]

def save_decision(ticket_id,decision):
    with connect() as con:
        con.execute('INSERT INTO triage_decisions(ticket_id,decision_json,created_at) VALUES(?,?,?) ON CONFLICT(ticket_id) DO UPDATE SET decision_json=excluded.decision_json,created_at=excluded.created_at',(ticket_id,json.dumps(decision,ensure_ascii=False),now()))

def decision_for(ticket_id):
    with connect() as con:
        row=con.execute('SELECT decision_json FROM triage_decisions WHERE ticket_id=?',(ticket_id,)).fetchone()
        return json.loads(row['decision_json']) if row else None

def save_override(ticket_id,field,ai_value,agent_value,agent_id,reason):
    with connect() as con:
        con.execute('INSERT INTO overrides(ticket_id,field,ai_value,agent_value,agent_id,reason,created_at) VALUES(?,?,?,?,?,?,?)',(ticket_id,field,json.dumps(ai_value),json.dumps(agent_value),agent_id,reason,now()))

def overrides_for(ticket_id):
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM overrides WHERE ticket_id=? ORDER BY created_at,id',(ticket_id,))]

def delete_cancelled(ticket_id,actor,reason):
    with connect() as con:
        con.execute('INSERT INTO audit_log(ticket_id,field,old_value,new_value,changed_by,changed_at,reason) VALUES(?,?,?,?,?,?,?)',(ticket_id,'permanent_delete',ticket_id,'[deleted]',actor,now(),reason))
        con.execute('DELETE FROM tickets WHERE ticket_id=?',(ticket_id,))
        con.execute('DELETE FROM comments WHERE ticket_id=?',(ticket_id,))
        con.execute('DELETE FROM triage_decisions WHERE ticket_id=?',(ticket_id,))
        con.execute('DELETE FROM overrides WHERE ticket_id=?',(ticket_id,))
        con.execute('DELETE FROM notifications WHERE ticket_id=?',(ticket_id,))


def get_chat_session(session_id,user_id):
    with connect() as con:
        row=con.execute('SELECT * FROM chat_sessions WHERE session_id=? AND user_id=?',(session_id,user_id)).fetchone()
        if not row:return None
        item=dict(row); item['state']=json.loads(item.pop('messages_json')); return item

def save_chat_session(session_id,user_id,state,outcome=None,feedback=None):
    with connect() as con:
        con.execute('INSERT INTO chat_sessions(session_id,user_id,started_at,messages_json,outcome,feedback) VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET messages_json=excluded.messages_json,outcome=COALESCE(excluded.outcome,chat_sessions.outcome),feedback=COALESCE(excluded.feedback,chat_sessions.feedback)',(session_id,user_id,now(),json.dumps(state,ensure_ascii=False),outcome,feedback))

def chat_sessions():
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM chat_sessions')]


def all_decisions():
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM triage_decisions')]

def all_overrides():
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM overrides')]

# user follow-up feature helpers

def notifications_for(user_id, unread_only=False):
    with connect() as con:
        query='SELECT * FROM notifications WHERE user_id=?'
        if unread_only: query += ' AND read=0'
        query += ' ORDER BY created_at DESC,id DESC'
        return [dict(r) for r in con.execute(query,(user_id,))]

def mark_notification_read(notification_id,user_id):
    with connect() as con:
        cur=con.execute('UPDATE notifications SET read=1 WHERE id=? AND user_id=?',(notification_id,user_id))
        return cur.rowcount > 0
