import os
import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

API=os.getenv('SUPPORT_TRIAGE_API','http://127.0.0.1:8000')
st.set_page_config(page_title='Orbit Support',page_icon='✦',layout='wide')

import streamlit as st

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-dark: #080c14;
    --panel-base: rgba(18, 26, 41, 0.65);
    --panel-solid: #111726;
    --panel-border: rgba(255, 255, 255, 0.08);
    --panel-border-glow: rgba(45, 212, 191, 0.3);
    
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    
    --accent-teal: #2dd4bf;
    --accent-gold: #fbbf24;
    --accent-lavender: #c084fc;
    --accent-blue: #38bdf8;
    --accent-rose: #f43f5e;
}

/* Base Body & App Canvas */
html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Plus Jakarta Sans', sans-serif;
    -webkit-font-smoothing: antialiased;
    color: var(--text-primary);
    background-color: var(--bg-dark);
    background-image: 
        radial-gradient(circle at 85% 0%, rgba(192, 132, 252, 0.08) 0%, transparent 35%),
        radial-gradient(circle at 10% 20%, rgba(45, 212, 191, 0.08) 0%, transparent 30%),
        radial-gradient(circle at 50% 90%, rgba(56, 189, 248, 0.05) 0%, transparent 40%);
    background-attachment: fixed;
}

[data-testid="stHeader"] {
    background: transparent !important;
}

.block-container {
    max-width: 1350px;
    padding-top: 2rem;
    padding-bottom: 4rem;
}

.orbit-login-hero {
    max-width: 700px;
    margin: 3vh auto 2rem;
    text-align: center;
}
.orbit-login-mark {
    display: inline-grid;
    place-items: center;
    width: 54px;
    height: 54px;
    margin-bottom: 1rem;
    border: 1px solid rgba(45, 212, 191, 0.28);
    border-radius: 18px;
    color: var(--accent-teal);
    background: linear-gradient(145deg, rgba(45, 212, 191, 0.16), rgba(192, 132, 252, 0.14));
    box-shadow: 0 10px 36px rgba(45, 212, 191, 0.10);
    font-size: 1.8rem;
}
.orbit-login-eyebrow {
    color: var(--accent-teal);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.18em;
}
.orbit-login-hero h1 {
    margin: 0.45rem 0 0.25rem;
    color: var(--text-primary);
    font-size: clamp(2rem, 4vw, 3rem);
    font-weight: 800;
    letter-spacing: -0.055em;
}
.orbit-login-hero p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 1rem;
}
.orbit-login-footnote {
    padding-top: 1rem;
    color: var(--text-muted);
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-align: center;
}

/* =========================================================
   1. SURPRISING RADIO BUTTON TRANSFORMATION (Segmented Control)
   Transform horizontal radio buttons into sleek glowing pills
   ========================================================= */
div[role="radiogroup"] {
    display: flex;
    flex-direction: row;
    background: rgba(13, 20, 32, 0.8) !important;
    padding: 6px !important;
    border-radius: 14px !important;
    border: 1px solid var(--panel-border) !important;
    backdrop-filter: blur(12px);
    gap: 6px !important;
    width: fit-content;
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.4);
}

div[role="radiogroup"] label {
    background: transparent !important;
    border-radius: 10px !important;
    padding: 8px 18px !important;
    margin: 0 !important;
    cursor: pointer !important;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    border: 1px solid transparent !important;
}

/* Hide default radio circle completely */
div[role="radiogroup"] label > div:first-child {
    display: none !important;
}

/* Radio Option Text Styling */
div[role="radiogroup"] label div[data-testid="stMarkdownContainer"] p {
    color: var(--text-secondary) !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    letter-spacing: -0.01em;
}

/* Active Radio Button Pill Effect */
div[role="radiogroup"] label:has(input:checked) {
    background: linear-gradient(135deg, rgba(45, 212, 191, 0.2), rgba(56, 189, 248, 0.1)) !important;
    border: 1px solid rgba(45, 212, 191, 0.4) !important;
    box-shadow: 0 4px 15px rgba(45, 212, 191, 0.15) !important;
}

div[role="radiogroup"] label:has(input:checked) div[data-testid="stMarkdownContainer"] p {
    color: var(--accent-teal) !important;
    font-weight: 700 !important;
    text-shadow: 0 0 8px rgba(45, 212, 191, 0.3);
}

div[role="radiogroup"] label:hover {
    background: rgba(255, 255, 255, 0.04) !important;
}

/* =========================================================
   2. INTERACTIVE METRIC CARDS WITH GLOW ACCENTS
   ========================================================= */
[data-testid="stMetric"] {
    min-height: 110px;
    padding: 20px 22px;
    border: 1px solid var(--panel-border);
    border-radius: 18px;
    background: var(--panel-base);
    backdrop-filter: blur(16px);
    box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}

/* Subtly colored glowing edge triggers */
[data-testid="stMetric"]::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent-teal), transparent);
    opacity: 0.7;
}

[data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(2) [data-testid="stMetric"]::before {
    background: linear-gradient(90deg, transparent, var(--accent-lavender), transparent);
}

[data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(3) [data-testid="stMetric"]::before {
    background: linear-gradient(90deg, transparent, var(--accent-gold), transparent);
}

[data-testid="stMetric"]:hover {
    transform: translateY(-3px);
    border-color: var(--panel-border-glow);
    box-shadow: 0 16px 35px -10px rgba(45, 212, 191, 0.15);
}

[data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
    font-weight: 600;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

[data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-weight: 800;
    font-size: 1.9rem !important;
    letter-spacing: -0.03em;
}

/* =========================================================
   3. NEON EDGE BUTTONS
   ========================================================= */
.stButton > button,
.stFormSubmitButton > button,
[data-testid="stDownloadButton"] button {
    min-height: 44px;
    padding: 0.6rem 1.4rem;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    background: linear-gradient(180deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%);
    color: var(--text-primary) !important;
    font-weight: 600;
    font-size: 0.9rem;
    letter-spacing: -0.01em;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    transition: all 0.25s ease;
    backdrop-filter: blur(8px);
}

.stButton > button:hover,
.stFormSubmitButton > button:hover,
[data-testid="stDownloadButton"] button:hover {
    border-color: var(--accent-teal);
    color: var(--accent-teal) !important;
    box-shadow: 0 0 20px rgba(45, 212, 191, 0.25);
    transform: translateY(-2px);
}

/* Primary Button Styling */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #0d9488 0%, #0284c7 100%);
    border: none;
    box-shadow: 0 4px 20px rgba(45, 212, 191, 0.3);
}

.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #14b8a6 0%, #0369a1 100%);
    box-shadow: 0 6px 25px rgba(45, 212, 191, 0.45);
    color: #ffffff !important;
}

/* =========================================================
   4. SLEEK INPUT FIELDS & SELECT BOXES
   ========================================================= */
input, textarea, [data-baseweb="select"] > div {
    border: 1px solid var(--panel-border) !important;
    border-radius: 12px !important;
    background: rgba(13, 20, 32, 0.7) !important;
    color: var(--text-primary) !important;
    font-size: 0.925rem !important;
    backdrop-filter: blur(10px) !important;
    transition: all 0.2s ease !important;
}

input:focus, textarea:focus, [data-baseweb="select"] > div:focus-within {
    border-color: var(--accent-teal) !important;
    box-shadow: 0 0 0 3px rgba(45, 212, 191, 0.15) !important;
}

/* =========================================================
   5. EXPANDERS & CONTAINERS WITH GLASSMORPHISM
   ========================================================= */
[data-testid="stForm"],
[data-testid="stExpander"] {
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    background: var(--panel-base);
    backdrop-filter: blur(16px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

[data-testid="stExpander"]:hover {
    border-color: rgba(255, 255, 255, 0.15);
}

/* =========================================================
   6. CYBER CHAT MESSAGES
   ========================================================= */
[data-testid="stChatMessage"] {
    margin-bottom: 14px;
    padding: 16px 20px;
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    background: rgba(17, 24, 38, 0.6);
    backdrop-filter: blur(12px);
}

[data-testid="stChatMessage"]:nth-of-type(even) {
    background: rgba(24, 34, 52, 0.7);
    border-color: rgba(192, 132, 252, 0.2);
}

/* =========================================================
   7. CODE BLOCKS & TERMINAL CARDS
   ========================================================= */
[data-testid="stCodeBlock"] {
    border-radius: 14px;
    border: 1px solid var(--panel-border);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    font-family: 'JetBrains Mono', monospace;
}

/* Scrollbar Customization */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: var(--bg-dark);
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.15);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.25);
}

hr {
    border-color: var(--panel-border);
    margin: 2.5rem 0;
}
</style>
""", unsafe_allow_html=True)

def call(method,path,**kwargs):
    headers=dict(kwargs.pop('headers',{}))
    if st.session_state.get('user'): headers['X-User-ID']=st.session_state.user['user_id']
    try:
        r = httpx.request(method, API + path, headers=headers, timeout=90, **kwargs)

        try:
            payload = r.json()
        except ValueError:
            detail = (r.text or "").strip().replace("\n", " ")[:240]
            st.error(
                f"API returned a non-JSON response (HTTP {r.status_code}) "
                f"for {path}. Check that the Support Ticket Triage API is "
                f"running at {API}. {detail}"
            )
            return None

        if r.status_code >= 400:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            st.error(detail)
            return None

        return payload
    except httpx.RequestError as e:
        st.error(f"Cannot connect to the Support Ticket Triage API at {API}: {e}")
        return None

def ai_review_label(ticket):
    decision=ticket.get('triage_decision') or {}
    if decision.get('needs_human_review') or (decision.get('category')=='Security' and not decision.get('human_reviewed')):
        return 'Needs review'
    if decision.get('human_reviewed') and decision.get('review_outcome')=='overridden':
        return 'Reviewed with override'
    if decision.get('human_reviewed'):
        return 'Reviewed'
    return 'No review needed'

def employee_status(t):
    status=t.get('status')
    if status=='New': return 'Received'
    if status=='Assigned': return f"With the {t.get('assignment_group') or 'support'} team"
    if status=='In Progress': return 'Being worked on'
    if status=='Pending' and t.get('pending_reason')=='Awaiting User': return 'Waiting for your reply'
    if status=='Pending': return 'On hold, waiting on a third party'
    if status=='Resolved': return 'Fixed: please confirm'
    return status or 'Unknown'

def login():
    st.markdown('''
    <div class="orbit-login-hero">
      <div class="orbit-login-mark">✦</div>
      <div class="orbit-login-eyebrow">ORBIT · SUPPORT WORKSPACE</div>
      <h1>Good to see you.</h1>
      <p>One workspace for clearer, faster support.</p>
    </div>
    ''', unsafe_allow_html=True)
    people = call('GET', '/login/options')
    if not people:
        return
    left, center, right = st.columns([0.75, 1.5, 0.75])
    with center:
        with st.container(border=True):
            st.markdown('### Sign in')
            st.caption('Select your workspace identity to continue.')
            person = st.selectbox(
                'Name',
                people,
                format_func=lambda item: (
                    f"{item['name']} · {item.get('assignment_group') or item.get('department') or 'Department not set'}"
                    f" · {item.get('role', '').title()}"
                ),
                help='Choose the employee, support agent, or manager profile for this demo.',
                key='login-person',
            )
            st.text_input(
                'Password',
                type='password',
                placeholder='Optional for this demo',
                help='This demo login does not check passwords. You can leave this blank.',
                key='login-password',
            )
            profile_details = [person.get('role', '').title()]
            profile_department = person.get('assignment_group') or person.get('department')
            if profile_department:
                profile_details.append(profile_department)
            if person.get('job_title'):
                profile_details.append(person['job_title'])
            profile_details.append(person['user_id'])
            st.caption(' · '.join(profile_details))
            if st.button('Continue to Orbit  →', type='primary', use_container_width=True):
                signed_in = call('POST', '/login', json={'user_id': person['user_id']})
                if signed_in:
                    st.session_state.user = signed_in
                    st.rerun()
            st.markdown(
                '<div class="orbit-login-footnote">DEMO WORKSPACE&nbsp;&nbsp; · &nbsp;&nbsp;PASSWORD OPTIONAL</div>',
                unsafe_allow_html=True,
            )

def employee(user):
    st.sidebar.title('Orbit · Employee')
    st.sidebar.caption(f"Signed in as: {user['name']} ({user['user_id']})")
    page=st.sidebar.radio('Workspace',['Ask IT','Raise a ticket','My tickets'])
    if st.sidebar.button('Switch user'): st.session_state.clear(); st.rerun()
    if page=='Ask IT':
        st.title('Ask IT')
        st.caption('Answers come from published knowledge articles and include their sources.')
        st.session_state.setdefault('chat_messages',[]); st.session_state.setdefault('chat_session',None)
        for m in st.session_state.chat_messages:
            with st.chat_message(m['role']):
                st.write(m['text'])
                for c in m.get('citations',[]): st.caption(f"{c['kb_id']} · {c['title']}")
        latest=st.session_state.chat_messages[-1] if st.session_state.chat_messages else {}
        if latest.get('preview'):
            preview=latest['preview']; decision=preview.get('decision') or {}
            st.info(f"Ticket preview: {preview['ticket']['short_description']} · {decision.get('assignment_group') or 'No IT queue'} · {decision.get('priority') or 'Needs review'}")
            c1,c2=st.columns(2)
            if c1.button('Confirm and submit ticket'):
                result=call('POST','/chat',json={'session_id':st.session_state.chat_session,'message':'yes','confirm_ticket':True})
                if result: st.success(result['reply']); st.session_state.chat_messages.append({'role':'assistant','text':result['reply']}); st.rerun()
            if c2.button('Not now'):
                result=call('POST','/chat',json={'session_id':st.session_state.chat_session,'message':'no'})
                if result: st.session_state.chat_messages.append({'role':'assistant','text':result['reply']}); st.rerun()
        question=st.chat_input('Ask about an IT issue or your own ticket')
        if question:
            # Show the submitted query before the blocking API request begins.
            # Streamlit clears chat_input on submit, so render and persist the
            # user bubble immediately while the assistant is working.
            user_message={'role':'user','text':question}
            st.session_state.chat_messages.append(user_message)
            with st.chat_message('user'):
                st.write(question)
            with st.chat_message('assistant'):
                with st.spinner('Searching the knowledge base…'):
                    result=call('POST','/chat',json={'session_id':st.session_state.chat_session,'message':question})
            if result:
                st.session_state.chat_session=result['session_id']
                st.session_state.chat_messages.append({'role':'assistant','text':result['reply'],'citations':result.get('citations',[]),'preview':result.get('ticket_preview')})
                st.rerun()
    elif page=='Raise a ticket':
        st.title('Describe the issue')
        with st.form('raise'):
            ticket_type=st.selectbox('Request type',['Incident','Service Request'])
            title=st.text_input('Short description',max_chars=120); body=st.text_area('What happened?'); ci=st.text_input('App or device (optional)')
            hint=st.radio('How is this affecting your work?', ["I can't work","I can work with difficulty","Just a question"],horizontal=True)
            submit=st.form_submit_button('Triage request')
        if submit:
            result=call('POST','/tickets',json={'short_description':title,'description':body,'affected_ci':ci or None,'impact_hint':hint,'ticket_type':ticket_type,'channel':'Portal'})
            if result: st.success(f"{result['ticket_id']} · {result.get('priority') or 'Needs review'} · first response target {result.get('sla_response_due') or 'pending triage'}")
    else:
        st.title('My tickets')
        notifications=call('GET','/notifications',params={'unread_only':True}) or []
        unread_by_ticket={}
        for item in notifications:
            unread_by_ticket.setdefault(item['ticket_id'],[]).append(item)
            c1,c2=st.columns([5,1])
            c1.info(f"{item['text']} · {item['ticket_id']}")
            if c2.button('Mark read',key=f"notification-{item['id']}"):
                call('POST',f"/notifications/{item['id']}/read"); st.rerun()
        mine=[]
        page=1
        while True:
            rows=call('GET','/tickets',params={'page':page,'page_size':100})
            if not rows:
                break
            mine.extend(t for t in rows['items'] if t['requester']['requester_id']==user['user_id'])
            if page*rows['page_size']>=rows['total']:
                break
            page+=1
        if mine:
            for t in mine:
                has_unread=bool(unread_by_ticket.get(t['ticket_id']))
                update_marker=' · NEW UPDATE' if has_unread else ''
                with st.expander(f"{update_marker} {t['ticket_id']} · {t['short_description']} · {employee_status(t)}"):
                    st.write('Status:',employee_status(t),'| Team:',t.get('assignment_group') or 'Awaiting triage','| Expected resolution:',t.get('sla_resolution_due') or 'Pending triage')
                    detail=call('GET',f"/tickets/{t['ticket_id']}")
                    if detail:
                        st.caption('Public updates from the support team')
                        public_comments=detail.get('comments',[])
                        if public_comments:
                            for c in public_comments:
                                st.write(c['body'])
                                if c.get('created_at'): st.caption(c['created_at'])
                        else:
                            st.caption('No public updates yet. Internal support notes are not shown here.')
                    response=st.text_input('Public reply',key='reply'+t['ticket_id'])
                    if st.button('Send reply',key='send'+t['ticket_id']) and response:
                        call('POST',f"/tickets/{t['ticket_id']}/comments",json={'body':response,'visibility':'public'}); st.rerun()
                    if t['status'] in ('New','Assigned'):
                        why=st.selectbox('Cancel reason',['Duplicate','Raised by mistake','No longer needed','Spam / test'],key='employee-cancel-'+t['ticket_id'])
                        if st.button('Cancel this ticket',key='employee-cancel-button-'+t['ticket_id']): call('POST',f"/tickets/{t['ticket_id']}/cancel",json={'reason':why}); st.rerun()
                    if t['status']=='Resolved':
                        if t.get('csat_score') is None:
                            with st.form('csat-'+t['ticket_id']):
                                score=st.select_slider('How satisfied are you with the outcome?',options=[1,2,3,4,5],value=4,format_func=lambda n:['','Very dissatisfied','Dissatisfied','Neutral','Satisfied','Very satisfied'][n])
                                rate=st.form_submit_button('Send rating')
                            if rate:
                                result=call('POST',f"/tickets/{t['ticket_id']}/csat",json={'score':score})
                                if result: st.success('Thanks for your feedback.'); st.rerun()
                        else: st.caption(f"Your rating: {t['csat_score']} / 5")
                        if st.button('No, reopen ticket',key='reopen-'+t['ticket_id']): call('PATCH',f"/tickets/{t['ticket_id']}",json={'status':'In Progress'}); st.rerun()

def support(user):
    st.sidebar.title('Orbit · Support')
    st.sidebar.caption(f"Signed in as: {user['name']} ({user['user_id']})")
    if user.get('assignment_group'):
        st.sidebar.caption(f"Group: {user['assignment_group']}")
    page=st.sidebar.radio('Workspace',['Ticket queue','Create on behalf','Insights'],key='support_page')
    if st.sidebar.button('Switch user'): st.session_state.clear(); st.rerun()
    try:
        export_response=httpx.get(API+'/export/tickets.csv',headers={'X-User-ID':user['user_id']},timeout=30)
        if export_response.status_code==200:
            st.sidebar.download_button('Download tickets CSV',data=export_response.content,file_name='support_tickets.csv',mime='text/csv')
    except Exception:
        st.sidebar.caption('CSV export unavailable while the API is disconnected.')
    if page=='Ticket queue':
        st.title('Service desk queue')
        a,b,c,d=st.columns(4)
        status=a.selectbox('Status',['Open','All','New','Assigned','In Progress','Pending','Resolved','Closed','Cancelled'])
        priority=b.selectbox('Priority',['Any','P1','P2','P3','P4'])
        category=c.selectbox('Category',['Any','Access & Identity','Email & Collaboration','Hardware','Software & Applications','Network & Connectivity','Infrastructure','Security'])
        query=d.text_input('Search ID or text')
        groups=['Any','Service Desk L1','Identity & Access Mgmt (IAM)','Collaboration Support','Desktop Support','Application Support','Network Operations','Infrastructure Ops','Security Operations (SOC)']
        g1,g2,g3,g4=st.columns(4)
        group=g1.selectbox('Assignment group',groups)
        assigned=g2.checkbox('Assigned to me')
        unassigned=g3.checkbox('Unassigned')
        risk=g4.checkbox('SLA at risk')
        date_span=st.date_input('Created between',value=(__import__('datetime').date.today()-__import__('datetime').timedelta(days=29),__import__('datetime').date.today()))
        page_num=st.session_state.get('queue_page',1)
        preset=st.session_state.pop('queue_filters',{})
        params={'status':status if status not in ('All',) else None,'priority':priority if priority!='Any' else None,'category':category if category!='Any' else None,'search':query or None,'group':group if group!='Any' else None,'assigned_to_me':assigned,'unassigned':unassigned,'sla_at_risk':risk,'breached':False,'from_date':date_span[0].isoformat() if len(date_span)==2 else None,'to_date':date_span[1].isoformat() if len(date_span)==2 else None,'page':page_num,'page_size':25}
        params.update(preset)
        data=call('GET','/tickets',params={k:v for k,v in params.items() if v is not None and v is not False})
        if data:
            rows=data['items']; st.caption(f"{data['total']} ticket(s) · Page {data['page']} · sorted by SLA target")
            if rows:
                table=[{'ID':t['ticket_id'],'Title':t['short_description'],'Priority':t.get('priority'),'Category':t.get('category'),'Group':t.get('assignment_group'),'Assigned to':t.get('assigned_to') or 'Unassigned (group queue)','Status':t['status'],'SLA due':t.get('sla_resolution_due'),'AI review':ai_review_label(t)} for t in rows]
                st.dataframe(pd.DataFrame(table),width='stretch',hide_index=True)
                choices={f"{t['ticket_id']} · {t.get('priority') or '—'} · {t['short_description']}":t['ticket_id'] for t in rows}
                tid=choices[st.selectbox('Open ticket',list(choices))]; t=call('GET',f'/tickets/{tid}')
                p1,p2=st.columns(2)
                if p1.button('Previous page',disabled=page_num<=1): st.session_state.queue_page=page_num-1; st.rerun()
                if p2.button('Next page',disabled=page_num*25>=data['total']): st.session_state.queue_page=page_num+1; st.rerun()
                if t:
                    if 'support_people' not in st.session_state:
                        st.session_state['support_people'] = call('GET', '/login/options') or []
                    support_agents = [
                        person for person in st.session_state['support_people']
                        if person.get('role') == 'agent'
                    ]
                    left,right=st.columns([3,2])
                    with left:
                        st.subheader(t['short_description']); st.write(t['description']); st.caption(f"{t['requester']['name']} · {t['requester']['department']} · {t['requester']['location']}")
                        d=t.get('triage_decision') or {}; st.write('Status:',t['status'],'· Priority:',t.get('priority'),'· Group:',t.get('assignment_group'),'· Assignee:',t.get('assigned_to') or 'Unassigned (group queue)')
                        with st.expander('AI reasoning and evidence'): st.json(d)
                        if d and st.button('Accept AI triage',key='accept-'+tid):
                            result=call('POST',f'/tickets/{tid}/accept-triage')
                            if result: st.success('AI triage accepted and audited.'); st.rerun()
                        status_list=['New','Assigned','In Progress','Pending','Resolved','Closed']
                        newstatus=st.selectbox('Move to',status_list,index=status_list.index(t['status']) if t['status'] in status_list else 0,key='status-edit-'+tid)
                        group_edit=st.selectbox('Group',groups[1:],index=(groups[1:].index(t['assignment_group']) if t.get('assignment_group') in groups[1:] else 0),key='group-edit-'+tid)
                        group_agents=[
                            person['name'] for person in support_agents
                            if person.get('assignment_group') == group_edit
                        ]
                        if (group_edit == t.get('assignment_group') and t.get('assigned_to')
                                and t['assigned_to'] not in group_agents):
                            group_agents.insert(0, t['assigned_to'])
                        unassigned_label='Unassigned — stays in group queue'
                        assignee_options=[unassigned_label, *group_agents]
                        current_assignee=t.get('assigned_to')
                        assignee_index=(assignee_options.index(current_assignee)
                                        if current_assignee in assignee_options else 0)
                        agent=st.selectbox(
                            'Assignee', assignee_options, index=assignee_index,
                            key='assignee-edit-'+tid,
                            help='Choose an agent from this group, or leave the ticket in the group queue for later assignment.'
                        )
                        reason=st.text_input('Reason for routing or priority changes',key='reason-edit-'+tid)
                        pending=st.selectbox('Pending reason',['Awaiting User','Awaiting Vendor','Awaiting Change'],index=['Awaiting User','Awaiting Vendor','Awaiting Change'].index(t.get('pending_reason')) if t.get('pending_reason') in ['Awaiting User','Awaiting Vendor','Awaiting Change'] else 0,key='pending-reason-'+tid) if newstatus=='Pending' else None
                        code=st.selectbox('Resolution code',['Solved (Permanent Fix)','Solved (Workaround)','User Error / Training','Not Reproducible','Duplicate','Cancelled by User'],key='resolution-code-'+tid) if newstatus=='Resolved' else None
                        notes=st.text_area('Resolution notes',value=t.get('resolution_notes') or '',key='resolution-notes-'+tid) if newstatus=='Resolved' else None
                        save=st.button('Save changes',key='save-ticket-'+tid)
                        if save:
                            patch={'assignment_group':group_edit,'assigned_to':None if agent==unassigned_label else agent,'status':newstatus,'reason':reason,'expected_updated_at':t.get('updated_at')}
                            if pending: patch['pending_reason']=pending
                            if code: patch['resolution_code']=code; patch['resolution_notes']=notes
                            result=call('PATCH',f'/tickets/{tid}',json=patch)
                            if result: st.success('Saved to the audit trail.'); st.rerun()
                        comments=t.get('comments',[])
                        with st.expander(f"Conversation · {len(comments)} message(s)",expanded=False):
                            if comments:
                                for comment in comments:
                                    st.caption(f"{comment.get('author_name') or comment.get('author_id')} · {comment.get('visibility','public').title()} · {comment.get('created_at','')}")
                                    st.write(comment['body'])
                            else:
                                st.caption('No conversation messages yet.')
                        note=st.text_area('Add a public reply or internal note',key='note'+tid); vis=st.radio('Visibility',['public','internal'],horizontal=True,key='vis'+tid)
                        if st.button('Add comment',key='comment'+tid) and note: call('POST',f'/tickets/{tid}/comments',json={'body':note,'visibility':vis}); st.rerun()
                        with st.expander('Audit trail'):
                            for item in t.get('audit_trail',[]): st.caption(f"{item['field']} · {item['old_value']} → {item['new_value']} · {item.get('reason') or ''}")
                    with right:
                        st.subheader('AI suggestions and overrides')
                        override_notice=st.session_state.pop('override_notice',None)
                        if override_notice: st.success(override_notice)
                        if d:
                            st.metric('Confidence',f"{d.get('confidence',0):.0%}")
                            if d.get('needs_human_review') or (d.get('category')=='Security' and not d.get('human_reviewed')): st.warning('Needs human review')
                            elif d.get('human_reviewed') and d.get('review_outcome')=='overridden': st.success('AI triage reviewed with an override.')
                            elif d.get('human_reviewed'): st.success('AI triage reviewed and accepted.')
                            if d.get('duplicate_of'): st.warning(f"Possible duplicate of {d['duplicate_of']} · review before resolving or merging.")
                            st.write(f"**{d.get('category')} / {d.get('subcategory')}** · {d.get('priority')} · {d.get('assignment_group')}")
                            st.write(d.get('suggested_resolution') or 'No grounded resolution found.')
                            for ref in dict.fromkeys(d.get('kb_references') or []): st.caption(f"Evidence: {ref}")
                            if t['status'] in ('Resolved','Closed','Cancelled'):
                                st.info('Overrides are disabled because this ticket is in a terminal status.')
                            else:
                                field=st.selectbox('Override field',['category','priority','impact','urgency','assignment_group'],key='override-field-'+tid)
                                override_choices={
                                    'category':['Access & Identity','Email & Collaboration','Hardware','Software & Applications','Network & Connectivity','Infrastructure','Security'],
                                    'priority':['P1','P2','P3','P4'],
                                    'impact':['High','Medium','Low'],
                                    'urgency':['High','Medium','Low'],
                                    'assignment_group':groups[1:],
                                }
                                value=st.selectbox('Override value',override_choices[field],key=f'override-value-{tid}-{field}'); why=st.text_input('Override reason',key='override-'+tid)
                                if st.button('Record override',key='record-override-'+tid) and value and why:
                                    result=call('POST',f'/tickets/{tid}/override',json={'field':field,'value':value,'reason':why})
                                    if result:
                                        st.session_state['override_notice']=f"AI triage updated: {result['field']} changed from {result['ai_value']} to {result['agent_value']}."
                                        st.rerun()
                        if t['status']=='Cancelled' and user['role']=='manager':
                            typed=st.text_input('Type ticket ID to permanently delete')
                            why_delete=st.text_input('Permanent delete reason')
                            if st.button('Permanently delete') and typed and why_delete: call('DELETE',f'/tickets/{tid}',json={'confirmation_ticket_id':typed,'reason':why_delete}); st.rerun()
                        elif t['status'] not in ('Cancelled','Closed'):
                            cancel_reason=st.selectbox('Cancel reason',['Duplicate','Raised by mistake','No longer needed','Spam / test'],key='cancel-'+tid)
                            if st.button('Cancel ticket',key='cancel-button-'+tid): call('POST',f'/tickets/{tid}/cancel',json={'reason':cancel_reason}); st.rerun()
            else: st.info('No tickets match these filters.')
    elif page=='Create on behalf':
        st.title('Create for an employee'); options=call('GET','/login/options') or []; employees=[x for x in options if x['role']=='employee']
        with st.form('create-on-behalf'):
            who=st.selectbox('Requester',employees,format_func=lambda x:x['name']+' · '+x['user_id']); ticket_type=st.selectbox('Request type',['Incident','Service Request']); title=st.text_input('Short description',max_chars=120); body=st.text_area('Description'); channel=st.selectbox('Channel',['Phone','Email','Portal','Chatbot']); submit=st.form_submit_button('Triage and create')
        if submit and title and body:
            result=call('POST','/tickets',json={'requester_id':who['user_id'],'short_description':title,'description':body,'ticket_type':ticket_type,'channel':channel})
            if result: st.success(f"Created {result['ticket_id']} · {result.get('priority') or 'Needs review'}")
    else: dashboard(user)

def _open_ticket_queue(filters):
    st.session_state.queue_filters = filters
    st.session_state.queue_page = 1
    st.session_state.support_page = 'Ticket queue'


def dashboard(user):
    st.title('Operations overview')

    from datetime import date, timedelta

    date_span = st.date_input(
        'Date range',
        value=(date.today() - timedelta(days=364), date.today()),
    )

    a, b, c = st.columns(3)
    group = a.selectbox(
        'Group',
        [
            'All groups',
            'Identity & Access Mgmt (IAM)',
            'Collaboration Support',
            'Desktop Support',
            'Application Support',
            'Network Operations',
            'Infrastructure Ops',
            'Security Operations (SOC)',
        ],
    )
    category = b.selectbox(
        'Category',
        [
            'All categories',
            'Access & Identity',
            'Email & Collaboration',
            'Hardware',
            'Software & Applications',
            'Network & Connectivity',
            'Infrastructure',
            'Security',
        ],
    )
    priority = c.selectbox('Priority', ['Any', 'P1', 'P2', 'P3', 'P4'])

    params = {
        key: value
        for key, value in {
            'group': group if group != 'All groups' else None,
            'category': category if category != 'All categories' else None,
            'priority': priority if priority != 'Any' else None,
            'start_date': date_span[0].isoformat() if len(date_span) == 2 else None,
            'end_date': date_span[1].isoformat() if len(date_span) == 2 else None,
        }.items()
        if value
    }

    data = call('GET', '/insights', params=params)
    if not data:
        return

    k = data['kpis']
    metrics = [
        ('Open', 'open', 'status=Open'),
        ('Unassigned', 'unassigned', 'unassigned=true'),
        ('P1 + P2', 'p1_p2_open', 'priority=P2'),
        ('At risk', 'at_risk', 'sla_at_risk=true'),
        ('Breached', 'breached', 'breached=true'),
        ('Resolved today', 'resolved_today', 'status=Resolved'),
    ]

    cols = st.columns(3)
    for i, (label, key, query) in enumerate(metrics):
        with cols[i % 3]:
            st.metric(label, k.get(key, 0))

            filters = {
                part.split('=')[0]: part.split('=')[1]
                for part in query.split('&')
            }
            if 'priority' in filters:
                filters['priority'] = 'P1,P2'

            st.button(
                'View ' + label.lower(),
                key='view-' + key,
                on_click=_open_ticket_queue,
                args=(filters,),
            )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Deflection rate', f"{k.get('deflection_rate', 0):.0%}")
    c2.metric('AI agreement', f"{k.get('ai_agreement', 0):.0%}")
    c3.metric(
        'Average satisfaction',
        f"{k['csat_average']:.2f} / 5"
        if k.get('csat_average') is not None else 'No ratings',
    )
    c4.metric('Satisfaction responses', k.get('csat_responses', 0))

    left, right = st.columns(2)

    with left:
        st.subheader('Tickets by status')
        status_data = pd.DataFrame([
            {'Status': name, 'Tickets': count}
            for name, count in data['tickets_by_status'].items()
        ])
        st.plotly_chart(
            px.bar(status_data, x='Status', y='Tickets'),
            width='stretch',
        )
        state = st.selectbox(
            'Drill into status',
            list(data['tickets_by_status']),
        )
        st.button(
            'Open status tickets',
            on_click=_open_ticket_queue,
            args=({'status': state},),
        )

    with right:
        st.subheader('Category mix')
        if data['category_mix']:
            category_data = pd.DataFrame([
                {'Category': name, 'Tickets': count}
                for name, count in data['category_mix'].items()
            ])
            st.plotly_chart(
                px.bar(category_data, x='Category', y='Tickets'),
                width='stretch',
            )
            cat = st.selectbox(
                'Drill into category mix',
                list(data['category_mix']),
            )
            st.button(
                'Open category mix',
                on_click=_open_ticket_queue,
                args=({'category': cat},),
            )
        else:
            st.info(
                'No tickets in this date range. '
                'Widen the date range to see the category mix.'
            )

    st.subheader('Workload by group')
    workloads = data.get('workload_by_group', {})
    workload_rows = [
        {'Group': name, **values}
        for name, values in workloads.items()
    ]

    if workload_rows:
        workload_data = pd.DataFrame(workload_rows).melt(
            id_vars='Group',
            var_name='Priority',
            value_name='Open tickets',
        )
        st.plotly_chart(
            px.bar(
                workload_data,
                x='Group',
                y='Open tickets',
                color='Priority',
                barmode='stack',
            ),
            width='stretch',
        )
        drill_group = st.selectbox(
            'Drill into workload group',
            [row['Group'] for row in workload_rows],
        )
        st.button(
            'Open group workload',
            on_click=_open_ticket_queue,
            args=({'group': drill_group, 'status': 'Open'},),
        )

    c1, c2 = st.columns(2)

    with c1:
        st.subheader('Created vs resolved')
        trend = data['created_vs_resolved']
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=trend['dates'],
            y=trend['created'],
            name='Created',
            mode='lines',
        ))
        fig.add_trace(go.Scatter(
            x=trend['dates'],
            y=trend['resolved'],
            name='Resolved',
            mode='lines',
        ))
        st.plotly_chart(fig, width='stretch')

        trend_day = st.selectbox('Drill into a day', trend['dates'])
        st.button(
            'Open day tickets',
            on_click=_open_ticket_queue,
            args=({'from_date': trend_day, 'to_date': trend_day},),
        )

    with c2:
        st.subheader('SLA compliance by priority')
        sla = data['sla_compliance']
        st.bar_chart({p: (sla[p]['percent'] or 0) for p in sla})

        sla_priority = st.selectbox(
            'Drill into SLA priority',
            list(sla),
        )
        st.button(
            'Open priority tickets',
            on_click=_open_ticket_queue,
            args=({'priority': sla_priority},),
        )

        st.subheader('Ticket aging')
        st.bar_chart(data['ticket_aging'])

    st.subheader('Who is handling what')
    rows = [
        {'Agent': name, **values}
        for name, values in data['who_is_handling_what'].items()
    ]
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    if rows:
        selected = st.selectbox(
            'Drill into agent',
            list(data['who_is_handling_what']),
        )
        st.button(
            'Open this agent’s tickets',
            on_click=_open_ticket_queue,
            args=({'assigned_to': selected},),
        )

    st.subheader('Unassigned queue')
    unassigned = data.get('unassigned_by_group', [])
    st.dataframe(pd.DataFrame(unassigned), width='stretch', hide_index=True)

    if unassigned:
        group_name = st.selectbox(
            'Unassigned group',
            [item['group'] for item in unassigned],
        )
        st.button(
            'Open unassigned tickets',
            on_click=_open_ticket_queue,
            args=({'unassigned': True, 'group': group_name},),
        )

    if data['category_mix']:
        category_pick = st.selectbox(
            'Drill into category',
            list(data['category_mix']),
        )
        st.button(
            'Open category tickets',
            on_click=_open_ticket_queue,
            args=({'category': category_pick},),
        )

def main():
    if not st.session_state.get('user'): login(); return
    user=st.session_state.user
    if user['role'] == 'employee':
        employee(user)
    else:
        support(user)

if __name__=='__main__': main()
