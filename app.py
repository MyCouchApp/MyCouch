import os, sqlite3, csv, io, shutil, tempfile, time, threading, json, urllib.request, urllib.error, secrets, re, math, mimetypes, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, quote
from flask import Flask, render_template, request, redirect, url_for, Response, abort, flash, session, g, send_from_directory
import requests

from werkzeug.security import generate_password_hash, check_password_hash

_SECRET_FILE=os.path.join(os.path.dirname(__file__),'.pla-secret')
def _app_secret():
    env=os.environ.get('MYCOUCH_SECRET') or os.environ.get('PLA_SECRET')
    if env: return env
    try:
        if os.path.exists(_SECRET_FILE): return open(_SECRET_FILE,'r',encoding='utf-8').read().strip()
        value=secrets.token_hex(32)
        with open(_SECRET_FILE,'w',encoding='utf-8') as f: f.write(value)
        return value
    except OSError:
        return secrets.token_hex(32)

app=Flask(__name__); app.secret_key=_app_secret()
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=(os.environ.get('MYCOUCH_SECURE_COOKIE') or os.environ.get('PLA_SECURE_COOKIE','0'))=='1',PERMANENT_SESSION_LIFETIME=timedelta(days=30))
BUILD_LOCK=threading.Lock()
APP_VERSION='2.9.14'
PLEX_UPDATE_STATUS={'running':False,'last_update':None,'error':None}
SMART_LOCK=threading.Lock(); SMART_MODEL=None; SMART_VECTORS=None; SMART_IDS=None
BUILD_STATUS={'running':False,'stage':'Idle','percent':0,'current':0,'total':0,'message':'','started_at':None,'elapsed':0,'error':None,'complete':False}
ARR_LOCK=threading.Lock()
TAUTULLI_LOCK=threading.Lock()
BACKUP_LOCK=threading.Lock()
BACKUP_STATUS={'running':False,'last_backup':None,'error':None}
DISCORD_BOT_STATUS={'running':False,'connected':False,'user':'','error':'','commands_synced':False,'sync_count':0,'guild_id':''}
TAUTULLI_STATUS={'running':False,'stage':'Idle','percent':0,'current':0,'total':0,'message':'','started_at':None,'elapsed':0,'error':None,'complete':False}
ARR_STATUS={'running':False,'stage':'Idle','percent':0,'current':0,'total':0,'message':'','started_at':None,'elapsed':0,'error':None,'complete':False,'radarr':{},'sonarr':{}}
DEFAULT_DB_PATH=os.environ.get('PLEX_DB','')
CONFIG_DB=os.path.join(os.path.dirname(__file__),'auditor.db')
CACHE_DB=os.path.join(os.path.dirname(__file__),'auditor-cache.db')

def get_db_path():
    c=config(); row=c.execute("select value from settings where key='plex_db'").fetchone(); c.close()
    return row['value'] if row and row['value'] else DEFAULT_DB_PATH

def plex():
    db_path=get_db_path()
    uri='file:'+db_path.replace('\\','/')+'?mode=ro'
    try: return sqlite3.connect(uri,uri=True)
    except Exception: return sqlite3.connect(db_path)
def config():
    c=sqlite3.connect(CONFIG_DB); c.row_factory=sqlite3.Row
    c.execute('create table if not exists protected(kind text,title text,note text,primary key(kind,title))')
    c.execute('create table if not exists review(kind text,item_id integer,title text,action text default "review",note text,added_at text default current_timestamp,primary key(kind,item_id))')
    c.execute('create table if not exists settings(key text primary key,value text)')
    c.execute("create table if not exists smart_search_history(id integer primary key autoincrement,query text not null,owner_key text not null default 'shared',searched_at integer not null)")
    # v2.9.12: migrate the original globally-unique history so Plex users can have personal histories.
    history_cols={r[1] for r in c.execute('pragma table_info(smart_search_history)').fetchall()}
    if 'owner_key' not in history_cols:
        c.execute('alter table smart_search_history rename to smart_search_history_legacy')
        c.execute("create table smart_search_history(id integer primary key autoincrement,query text not null,owner_key text not null default 'shared',searched_at integer not null)")
        c.execute("insert into smart_search_history(query,owner_key,searched_at) select query,'shared',searched_at from smart_search_history_legacy")
        c.execute('drop table smart_search_history_legacy')
    c.execute('create unique index if not exists idx_smart_search_history_owner_query on smart_search_history(owner_key,query)')
    c.execute('create index if not exists idx_smart_search_history_recent on smart_search_history(owner_key,searched_at desc)')
    c.execute('create table if not exists mobile_auth_pending(state text primary key,pin_id integer not null,created_at integer not null)')
    c.execute('create table if not exists mobile_auth_codes(code text primary key,profile_json text not null,expires_at integer not null)')
    c.execute('create table if not exists security_events(id integer primary key autoincrement,event_type text not null,ip text,path text,method text,user_agent text,detail text,created_at integer not null)')
    c.execute('create index if not exists idx_security_events_created on security_events(created_at desc)')

    c.execute('create table if not exists discord_posts(id integer primary key autoincrement,category text,item_key text,message text,posted_at integer)')
    c.execute('create index if not exists idx_discord_posts_recent on discord_posts(posted_at)')
    c.execute('create table if not exists leaving_soon(kind text,item_id integer,title text,size_gb real,deadline integer,status text default "announced",discord_posted integer default 0,added_at integer,primary key(kind,item_id))')
    c.execute('create table if not exists tautulli_activity(kind text,item_id integer,plays integer default 0,last_watched integer,last_user text,users_json text,synced_at text default current_timestamp,primary key(kind,item_id))')
    c.execute('create table if not exists tautulli_history(event_key text primary key,kind text,item_id integer,watched_at integer,user text,duration integer default 0,media_type text,transcode_decision text)')
    c.execute('create table if not exists tautulli_media_identity(kind text,item_id integer,title text,year integer,current_item_id integer,updated_at text default current_timestamp,primary key(kind,item_id))')
    c.execute('create index if not exists idx_tautulli_history_date on tautulli_history(watched_at)')
    c.execute('create index if not exists idx_tautulli_history_item on tautulli_history(kind,item_id)')
    c.execute('create table if not exists arr_matches(kind text,item_id integer,arr_id integer,title_slug text,arr_title text,arr_path text,matched_by text,synced_at text default current_timestamp,primary key(kind,item_id))')
    c.commit(); return c
def source_conn(path=None):
    db_path=path or get_db_path()
    uri='file:'+db_path.replace('\\','/')+'?mode=ro'
    c=sqlite3.connect(uri,uri=True); c.row_factory=sqlite3.Row; return c



def setting(key, default=''):
    c=config(); r=c.execute('select value from settings where key=?',(key,)).fetchone(); c.close()
    return r['value'] if r and r['value'] is not None else default

def set_setting(key,value):
    c=config(); c.execute('insert or replace into settings(key,value) values(?,?)',(key,value)); c.commit(); c.close()


def admin_configured():
    return bool(setting('admin_password_hash',''))

def is_admin():
    return bool(session.get('admin')) and admin_configured()

def csrf_token():
    token=session.get('_csrf')
    if not token:
        token=secrets.token_urlsafe(32); session['_csrf']=token
    return token

app.jinja_env.globals.update(is_admin=is_admin, csrf_token=csrf_token, app_version=APP_VERSION)


@app.route('/sw.js')
def service_worker():
    response = send_from_directory(app.static_folder, 'service-worker.js')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

def plex_user():
    return session.get('plex_user') or {}

def has_plex_access():
    machine=setting('plex_machine_id','').strip()
    return bool(plex_user()) and bool(machine) and session.get('plex_server_access')==machine

def _request_ip():
    # MyCouch is normally reached through Cloudflare Tunnel. CF-Connecting-IP is
    # Cloudflare's original-client header; fall back to Flask's peer address.
    return (request.headers.get('CF-Connecting-IP') or request.remote_addr or '')[:64]

def security_log(event_type, detail='', path=None):
    try:
        now=int(time.time()); c=config()
        c.execute('insert into security_events(event_type,ip,path,method,user_agent,detail,created_at) values(?,?,?,?,?,?,?)',
                  ((event_type or '')[:48],_request_ip(),(path if path is not None else request.path)[:300],
                   request.method[:12],(request.headers.get('User-Agent') or '')[:300],(detail or '')[:500],now))
        # Security Activity is deliberately lightweight: retain 30 days only.
        c.execute('delete from security_events where created_at<?',(now-30*86400,))
        c.commit(); c.close()
    except Exception:
        pass

def _plex_account_has_server_access(token):
    """Verify that a Plex login can see this configured Plex Media Server.

    Authentication alone is not authorization: the account must receive the
    configured machineIdentifier from plex.tv's resource list. Fail closed.
    """
    machine=setting('plex_machine_id','').strip()
    if not machine:
        return False, 'MyCouch has not detected the Plex server identity yet. An admin must Save & Test Plex in Settings.'
    headers=dict(_plex_auth_headers()); headers['X-Plex-Token']=token
    try:
        r=requests.get('https://plex.tv/api/v2/resources',params={'includeHttps':'1','includeRelay':'1','includeIPv6':'1'},headers=headers,timeout=15)
        r.raise_for_status()
        resources=[]
        try:
            data=r.json()
            resources=data if isinstance(data,list) else (data.get('MediaContainer',{}).get('Device',[]) if isinstance(data,dict) else [])
        except ValueError:
            root=ET.fromstring(r.content)
            resources=[node.attrib for node in root.findall('.//Device')]
        for resource in resources or []:
            rid=str(resource.get('clientIdentifier') or resource.get('clientidentifier') or resource.get('machineIdentifier') or '')
            provides=str(resource.get('provides') or '')
            if secrets.compare_digest(rid,machine) and ('server' in provides.lower() or not provides):
                return True, ''
        return False, 'This Plex account does not have access to this Plex server.'
    except Exception as e:
        return False, 'MyCouch could not verify access to this Plex server ('+type(e).__name__+').' 

def sort_url(column):
    args=request.args.to_dict(flat=True)
    current=args.get('sort','')
    direction=args.get('dir','desc').lower()
    args['sort']=column
    args['dir']='desc' if current==column and direction=='asc' else 'asc'
    args['page']='1'
    return request.path+'?'+urlencode(args)

def sort_mark(column):
    if request.args.get('sort')!=column: return ''
    return ' ▲' if request.args.get('dir','desc').lower()=='asc' else ' ▼'

app.jinja_env.globals.update(plex_user=plex_user, has_plex_access=has_plex_access, sort_url=sort_url, sort_mark=sort_mark)
app.jinja_env.filters['timestamp_date']=lambda v: datetime.fromtimestamp(int(v)).strftime('%d %b %Y') if v else '—'
app.jinja_env.filters['timestamp_datetime']=lambda v: datetime.fromtimestamp(int(v)).strftime('%d %b %Y %H:%M:%S') if v else '—'

# Endpoints that expose library/history data require a verified Plex account.
PLEX_ENDPOINTS={'dashboard','movie_page','tv_page','movie_detail','show_detail','smart_search','smart_search_history_clear','smart_search_poster','now_playing_api','cleanup','my_history','changelog'}
# These are reachable before Plex authorization. Dashboard renders only the landing page while signed out.
ANON_ENDPOINTS={'dashboard','setup_admin','login','logout','static','service_worker','robots_txt','plex_signin','plex_callback','plex_mobile_callback','plex_mobile_finalize','plex_logout'}

@app.after_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options','nosniff')
    response.headers.setdefault('X-Frame-Options','SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy','same-origin')
    response.headers.setdefault('Permissions-Policy','camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('X-Robots-Tag','noindex, nofollow, noarchive, nosnippet')
    if has_plex_access() or is_admin():
        response.headers.setdefault('Cache-Control','private, no-store')
    return response

@app.get('/robots.txt')
def robots_txt():
    return Response('User-agent: *\\nDisallow: /\\n',mimetype='text/plain',headers={'Cache-Control':'public, max-age=3600'})

@app.before_request
def security_gate():
    g.is_admin=is_admin()
    endpoint=request.endpoint
    # First run: require creation of an admin account before exposing the site.
    if not admin_configured() and endpoint not in {'setup_admin','static','service_worker','robots_txt'}:
        return redirect(url_for('setup_admin'))

    # Unknown/probe URLs are useful security signals and should not be redirected to a login form.
    if endpoint is None:
        suspicious=any(x in request.path.lower() for x in ('.env','wp-admin','wp-login','phpmyadmin','.git','xmlrpc','cgi-bin','actuator'))
        security_log('probe' if suspicious else 'not_found','Unknown path')
        abort(404)

    # Library/data pages require BOTH a Plex identity and verified access to this exact server.
    if endpoint in PLEX_ENDPOINTS and endpoint!='dashboard' and not has_plex_access():
        security_log('access_denied','Plex server authorization required')
        if request.method=='GET': return redirect(url_for('dashboard',next=request.path))
        abort(403)

    # Everything not explicitly public or Plex-user-facing remains admin-only.
    if endpoint not in ANON_ENDPOINTS and endpoint not in PLEX_ENDPOINTS and not is_admin():
        security_log('admin_denied','Admin authorization required')
        if request.method=='GET': return redirect(url_for('login',next=request.path))
        abort(403)

    # CSRF protection for every state-changing browser request.
    if request.method in ('POST','PUT','PATCH','DELETE'):
        sent=request.form.get('_csrf') or request.headers.get('X-CSRF-Token')
        if not sent or not secrets.compare_digest(sent,session.get('_csrf','')):
            security_log('csrf_rejected','Missing or invalid CSRF token')
            abort(400,'Invalid CSRF token')

@app.route('/setup-admin',methods=['GET','POST'])
def setup_admin():
    if admin_configured(): return redirect(url_for('login'))
    if request.method=='POST':
        username=(request.form.get('username') or 'admin').strip()[:64]
        password=request.form.get('password') or ''
        confirm=request.form.get('confirm') or ''
        if len(password)<12:
            flash('Use an admin password of at least 12 characters.','danger')
        elif password!=confirm:
            flash('Passwords do not match.','danger')
        else:
            set_setting('admin_username',username or 'admin')
            set_setting('admin_password_hash',generate_password_hash(password,method='scrypt'))
            session.clear(); session['admin']=True; csrf_token()
            flash('Admin account created. Plex authorization is required for library access.','success')
            return redirect(url_for('dashboard'))
    return render_template('setup_admin.html')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        username=(request.form.get('username') or '').strip()
        password=request.form.get('password') or ''
        if username==setting('admin_username','admin') and check_password_hash(setting('admin_password_hash',''),password):
            remember=request.form.get('remember')=='1'
            session.clear(); session['admin']=True; session.permanent=remember
            if remember:
                try: days=max(1,min(int(setting('remember_days','30')),365))
                except (TypeError,ValueError): days=30
                app.permanent_session_lifetime=timedelta(days=days)
            csrf_token()
            nxt=request.args.get('next','')
            security_log('admin_login','Successful admin login')
            return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('settings'))
        flash('Invalid username or password.','danger')
    return render_template('login.html')

@app.post('/logout')
def logout():
    security_log('admin_logout','Admin session ended')
    session.clear(); return redirect(url_for('dashboard'))

PLEX_AUTH_PRODUCT='MyCouch'

def _plex_auth_headers():
    client_id=setting('plex_auth_client_id','')
    if not client_id:
        client_id='mycouch-'+secrets.token_hex(16)
        set_setting('plex_auth_client_id',client_id)
    return {'Accept':'application/json','X-Plex-Product':PLEX_AUTH_PRODUCT,'X-Plex-Version':APP_VERSION,'X-Plex-Client-Identifier':client_id}

@app.get('/plex/signin')
def plex_signin():
    try:
        headers=_plex_auth_headers()
        r=requests.post('https://plex.tv/api/v2/pins?strong=true',headers=headers,timeout=15)
        r.raise_for_status(); pin=r.json()
        pin_id=int(pin['id']); code=pin['code']
        session['plex_pin_id']=pin_id

        # MyCouch Mobile must authenticate in the system browser because Google
        # blocks OAuth sign-in inside embedded WebViews. A one-time bridge lets
        # the browser return the completed Plex identity to the existing WebView
        # session without exposing the Plex token to the app.
        is_mobile='MyCouchMobile/' in (request.headers.get('User-Agent') or '')
        if is_mobile:
            state=secrets.token_urlsafe(32)
            c=config()
            now=int(time.time())
            c.execute('delete from mobile_auth_pending where created_at<?',(now-900,))
            c.execute('delete from mobile_auth_codes where expires_at<?',(now,))
            c.execute('insert into mobile_auth_pending(state,pin_id,created_at) values(?,?,?)',(state,pin_id,now))
            c.commit(); c.close()
            forward=url_for('plex_mobile_callback',pin_id=pin_id,state=state,_external=True)
        else:
            forward=url_for('plex_callback',pin_id=pin_id,_external=True)

        params={'clientID':headers['X-Plex-Client-Identifier'],'code':code,'context[device][product]':PLEX_AUTH_PRODUCT,'forwardUrl':forward}
        return redirect('https://app.plex.tv/auth#?'+urlencode(params))
    except Exception as e:
        flash('Could not start Plex sign-in: '+str(e),'danger')
        return redirect(url_for('dashboard'))

@app.get('/plex/mobile/callback')
def plex_mobile_callback():
    try:
        pin_id=int(request.args.get('pin_id') or 0)
        state=(request.args.get('state') or '').strip()
        now=int(time.time())
        c=config()
        row=c.execute('select pin_id,created_at from mobile_auth_pending where state=?',(state,)).fetchone()
        if not row or int(row['pin_id'])!=pin_id or int(row['created_at']) < now-900:
            c.close(); raise RuntimeError('Mobile Plex sign-in request expired or did not match')
        c.execute('delete from mobile_auth_pending where state=?',(state,))
        c.commit(); c.close()

        headers=_plex_auth_headers()
        r=requests.get(f'https://plex.tv/api/v2/pins/{pin_id}',headers=headers,timeout=15); r.raise_for_status()
        token=(r.json() or {}).get('authToken')
        if not token: raise RuntimeError('Plex sign-in was not completed')
        uh=dict(headers); uh['X-Plex-Token']=token
        u=requests.get('https://plex.tv/api/v2/user',headers=uh,timeout=15); u.raise_for_status(); profile=u.json() or {}
        allowed,reason=_plex_account_has_server_access(token)
        if not allowed:
            security_log('plex_denied',reason)
            raise RuntimeError(reason)
        safe_profile={'id':profile.get('id'),'uuid':profile.get('uuid'),'username':profile.get('username') or '',
                      'title':profile.get('title') or profile.get('friendlyName') or '',
                      'email':profile.get('email') or '', 'thumb':profile.get('thumb') or '', '_server_access':setting('plex_machine_id','').strip()}

        auth_code=secrets.token_urlsafe(32)
        c=config()
        c.execute('delete from mobile_auth_codes where expires_at<?',(now,))
        c.execute('insert into mobile_auth_codes(code,profile_json,expires_at) values(?,?,?)',
                  (auth_code,json.dumps(safe_profile),now+120))
        c.commit(); c.close()
        return redirect('mycouch://auth?code='+quote(auth_code))
    except Exception as e:
        return Response('MyCouch mobile Plex sign-in failed: '+str(e),status=400,mimetype='text/plain')


@app.get('/plex/mobile/finalize')
def plex_mobile_finalize():
    code=(request.args.get('code') or '').strip()
    now=int(time.time())
    c=config()
    row=c.execute('select profile_json,expires_at from mobile_auth_codes where code=?',(code,)).fetchone()
    if not row or int(row['expires_at']) < now:
        if row: c.execute('delete from mobile_auth_codes where code=?',(code,)); c.commit()
        c.close()
        flash('Mobile Plex sign-in expired. Please try again.','danger')
        return redirect(url_for('dashboard'))
    c.execute('delete from mobile_auth_codes where code=?',(code,))
    c.commit(); c.close()
    profile=json.loads(row['profile_json'])
    session['plex_server_access']=profile.pop('_server_access','')
    session['plex_user']=profile
    session.pop('plex_pin_id',None)
    security_log('plex_login','Authorized Plex server user')
    flash('Signed in with Plex.','success')
    return redirect(url_for('my_history'))


@app.get('/plex/callback')
def plex_callback():
    try:
        pin_id=int(request.args.get('pin_id') or 0)
        if not pin_id or pin_id!=int(session.get('plex_pin_id') or 0): raise RuntimeError('Plex sign-in session did not match')
        headers=_plex_auth_headers()
        r=requests.get(f'https://plex.tv/api/v2/pins/{pin_id}',headers=headers,timeout=15); r.raise_for_status()
        token=(r.json() or {}).get('authToken')
        if not token: raise RuntimeError('Plex sign-in was not completed')
        uh=dict(headers); uh['X-Plex-Token']=token
        u=requests.get('https://plex.tv/api/v2/user',headers=uh,timeout=15); u.raise_for_status(); profile=u.json() or {}
        allowed,reason=_plex_account_has_server_access(token)
        if not allowed:
            security_log('plex_denied',reason)
            raise RuntimeError(reason)
        # Keep only non-secret identity details in the signed browser session. The Plex token is discarded here.
        session['plex_user']={'id':profile.get('id'),'uuid':profile.get('uuid'),'username':profile.get('username') or '',
                              'title':profile.get('title') or profile.get('friendlyName') or '',
                              'email':profile.get('email') or '', 'thumb':profile.get('thumb') or ''}
        session['plex_server_access']=setting('plex_machine_id','').strip()
        session.pop('plex_pin_id',None)
        security_log('plex_login','Authorized Plex server user')
        flash('Signed in with Plex.','success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        session.pop('plex_pin_id',None)
        flash('Plex sign-in failed: '+str(e),'danger')
        return redirect(url_for('dashboard'))

@app.post('/plex/logout')
def plex_logout():
    security_log('plex_logout','Plex session ended'); session.pop('plex_user',None); session.pop('plex_server_access',None); session.pop('plex_pin_id',None)
    flash('Plex account signed out.','success')
    return redirect(url_for('dashboard'))

def _personal_history_user(profile):
    candidates=[]
    for key in ('title','username','email'):
        v=(profile.get(key) or '').strip()
        if v: candidates.append(v)
    if not candidates: return None
    c=config()
    for candidate in candidates:
        r=c.execute('select user,count(*) n from tautulli_history where lower(user)=lower(?) group by user order by n desc limit 1',(candidate,)).fetchone()
        if r: c.close(); return r['user']
    c.close(); return None

def _personal_stats(user):
    c=config()
    total=c.execute('select count(*) plays,coalesce(sum(duration),0) duration,min(watched_at) first_play,max(watched_at) last_play from tautulli_history where user=?',(user,)).fetchone()
    by_kind={r['kind']:r['n'] for r in c.execute('select kind,count(*) n from tautulli_history where user=? group by kind',(user,))}
    recent=[dict(r) for r in c.execute('select kind,item_id,watched_at,duration,transcode_decision from tautulli_history where user=? order by watched_at desc limit 50',(user,))]
    top=[dict(r) for r in c.execute('select kind,item_id,count(*) plays,coalesce(sum(duration),0) duration,max(watched_at) last_watched from tautulli_history where user=? group by kind,item_id order by plays desc,last_watched desc limit 20',(user,))]
    c.close()
    cc=cache_conn() if cache_ready() else None
    def label(r):
        if not cc: return None,None
        table,idcol=('movies','metadata_id') if r['kind']=='movie' else ('shows','show_id')
        x=cc.execute(f'select title,year from {table} where {idcol}=? limit 1',(r['item_id'],)).fetchone()
        return (x['title'],x['year']) if x else (None,None)
    for r in recent+top:
        r['title'],r['year']=label(r); r['plex_url']=_plex_web_link(r['item_id']) if r.get('title') else None
    if cc: cc.close()
    return {'plays':total['plays'] or 0,'hours':round((total['duration'] or 0)/3600,1),'first_play':total['first_play'],'last_play':total['last_play'],
            'movies':by_kind.get('movie',0),'episodes':by_kind.get('tv',0),'recent':recent,'top':top}

@app.get('/my-history')
def my_history():
    profile=plex_user()
    if not profile: return redirect(url_for('plex_signin'))
    history_user=_personal_history_user(profile)
    stats=_personal_stats(history_user) if history_user else None
    return render_template('my_history.html',profile=profile,history_user=history_user,stats=stats)

def arr_request(kind, endpoint):
    base=setting(kind+'_url', 'http://localhost:7878' if kind=='radarr' else 'http://localhost:7879').rstrip('/')
    key=setting(kind+'_api_key','')
    if not key: raise RuntimeError(kind.title()+' API key is not configured')
    req=urllib.request.Request(base+'/api/v3/'+endpoint.lstrip('/'),headers={'X-Api-Key':key,'Accept':'application/json'})
    # Large Sonarr libraries can take tens of seconds to serialize /api/v3/series.
    timeout = 120 if kind == 'sonarr' else 60
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def tautulli_request(cmd, **params):
    base=setting('tautulli_url','http://localhost:8181').rstrip('/')
    key=setting('tautulli_api_key','')
    if not key: raise RuntimeError('Tautulli API key is not configured')
    query={'apikey':key,'cmd':cmd}; query.update(params)
    url=base+'/api/v2?'+urlencode(query)
    req=urllib.request.Request(url,headers={'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=120) as r:
        payload=json.loads(r.read().decode('utf-8'))
    response=payload.get('response',{})
    if response.get('result') not in ('success',None): raise RuntimeError(response.get('message') or 'Tautulli API error')
    return response.get('data')

def tautulli_activity(kind):
    c=config(); rows={r['item_id']:dict(r) for r in c.execute('select * from tautulli_activity where kind=?',(kind,))}; c.close(); return rows

def set_tautulli_status(**kw):
    TAUTULLI_STATUS.update(kw)
    if TAUTULLI_STATUS.get('started_at'): TAUTULLI_STATUS['elapsed']=round(time.time()-TAUTULLI_STATUS['started_at'],1)

def _history_event(h):
    mt=(h.get('media_type') or '').lower()
    if mt=='movie': kind='movie'; rid=h.get('rating_key')
    elif mt=='episode': kind='tv'; rid=h.get('grandparent_rating_key')
    else: return None
    try: item_id=int(rid)
    except (TypeError,ValueError): return None
    try: ts=int(h.get('date') or h.get('started') or 0)
    except (TypeError,ValueError): ts=0
    user=h.get('user') or h.get('friendly_name') or ''
    try: duration=int(float(h.get('play_duration') or h.get('duration') or 0))
    except (TypeError,ValueError): duration=0
    raw_id=h.get('row_id') or h.get('history_id') or h.get('id')
    key=str(raw_id) if raw_id is not None else '|'.join(map(str,(kind,item_id,ts,user,h.get('session_key') or '',h.get('reference_id') or '')))
    title=(h.get('grandparent_title') or h.get('grandparentTitle')) if mt=='episode' else (h.get('title') or h.get('full_title'))
    year=(h.get('grandparent_year') or h.get('year')) if mt=='episode' else h.get('year')
    try: year=int(year) if year not in (None,'') else None
    except (TypeError,ValueError): year=None
    return key,kind,item_id,ts,user,duration,mt,(h.get('transcode_decision') or ''),title,year

def rebuild_tautulli_activity(c):
    c.execute('delete from tautulli_activity')
    rows=c.execute('select kind,item_id,count(*) plays,max(watched_at) last_watched from tautulli_history group by kind,item_id').fetchall()
    for r in rows:
        users=[x['user'] for x in c.execute("select distinct user from tautulli_history where kind=? and item_id=? and user<>'' order by user",(r['kind'],r['item_id']))]
        last=c.execute('select user from tautulli_history where kind=? and item_id=? order by watched_at desc limit 1',(r['kind'],r['item_id'])).fetchone()
        c.execute('insert into tautulli_activity(kind,item_id,plays,last_watched,last_user,users_json) values(?,?,?,?,?,?)',(r['kind'],r['item_id'],r['plays'],r['last_watched'],last['user'] if last else '',json.dumps(users)))

def sync_tautulli(full=False):
    started=time.time(); mode='Full rescan' if full else 'Incremental update'
    set_tautulli_status(running=True,complete=False,error=None,stage=mode,percent=2,current=0,total=0,message='Requesting play history from Tautulli…',started_at=started)
    try:
        c=config(); existing=c.execute('select count(*) n from tautulli_history').fetchone()['n']
        if not full and existing==0:
            c.close(); raise RuntimeError('v2.7 needs one Full Rescan to seed detailed Tautulli history. After that, Update Now is incremental.')
        if full:
            c.execute('delete from tautulli_history'); c.commit(); newest_seen=0; start=0; total=0
            while True:
                page=tautulli_request('get_history',start=start,length=5000)
                if not isinstance(page,dict): raise RuntimeError('Unexpected Tautulli history response')
                if start==0: total=int(page.get('recordsTotal') or page.get('recordsFiltered') or 0)
                batch=list(page.get('data') or [])
                if not batch: break
                for h in batch:
                    ev=_history_event(h)
                    if not ev: continue
                    c.execute('insert or ignore into tautulli_history(event_key,kind,item_id,watched_at,user,duration,media_type,transcode_decision) values(?,?,?,?,?,?,?,?)',ev[:8])
                    if ev[8]:
                        c.execute('insert into tautulli_media_identity(kind,item_id,title,year,updated_at) values(?,?,?,?,current_timestamp) on conflict(kind,item_id) do update set title=excluded.title,year=coalesce(excluded.year,tautulli_media_identity.year),updated_at=current_timestamp',(ev[1],ev[2],ev[8],ev[9]))
                    newest_seen=max(newest_seen,ev[3])
                c.commit(); start+=len(batch)
                set_tautulli_status(stage='Loading history',percent=5+int(70*start/max(total,1)),current=start,total=total,message=f'Loaded {start:,} / {total:,} history records')
                if start>=total: break
            set_setting('tautulli_cursor_ts',str(newest_seen)); loaded=start
        else:
            cursor=int(setting('tautulli_cursor_ts','0') or 0); loaded=0; start=0; newest_seen=cursor; stop=False
            while not stop:
                page=tautulli_request('get_history',start=start,length=1000); batch=list((page or {}).get('data') or [])
                if not batch: break
                for h in batch:
                    ev=_history_event(h)
                    if not ev: continue
                    if ev[3] <= cursor: stop=True; continue
                    c.execute('insert or ignore into tautulli_history(event_key,kind,item_id,watched_at,user,duration,media_type,transcode_decision) values(?,?,?,?,?,?,?,?)',ev[:8])
                    if ev[8]:
                        c.execute('insert into tautulli_media_identity(kind,item_id,title,year,updated_at) values(?,?,?,?,current_timestamp) on conflict(kind,item_id) do update set title=excluded.title,year=coalesce(excluded.year,tautulli_media_identity.year),updated_at=current_timestamp',(ev[1],ev[2],ev[8],ev[9]))
                    newest_seen=max(newest_seen,ev[3]); loaded+=1
                c.commit(); start+=len(batch)
                set_tautulli_status(stage='Loading new history',percent=min(75,10+start//10),current=loaded,total=max(loaded,1),message=f'Found {loaded:,} new history records')
                if stop or len(batch)<1000: break
            set_setting('tautulli_cursor_ts',str(newest_seen))
        set_tautulli_status(stage='Updating activity',percent=82,current=0,total=0,message='Updating title activity and dashboard statistics…')
        rebuild_tautulli_activity(c); c.commit(); c.close()
        set_setting('tautulli_last_sync',datetime.now().strftime('%Y-%m-%d %H:%M:%S')); set_setting('tautulli_authoritative','1')
        msg=(f'Full history cache rebuilt from {loaded:,} Tautulli records' if full else f'Incremental update complete · {loaded:,} new history records')
        set_tautulli_status(running=False,complete=True,stage='Complete',percent=100,current=loaded,total=loaded,message=msg,elapsed=round(time.time()-started,1))
    except Exception as e:
        set_tautulli_status(running=False,complete=False,stage='Failed',error=str(e),message=str(e),elapsed=round(time.time()-started,1))

def tautulli_worker(full=False):
    if not TAUTULLI_LOCK.acquire(blocking=False): return
    try: sync_tautulli(full=full)
    finally: TAUTULLI_LOCK.release()

def tautulli_dashboard_stats(days=30):
    c=config(); cutoff=0 if int(days)==0 else int(time.time()-int(days)*86400)
    total=c.execute('select count(*) n,coalesce(sum(duration),0) d from tautulli_history where watched_at>=?',(cutoff,)).fetchone()
    users=c.execute("select count(distinct user) n from tautulli_history where watched_at>=? and user<>''",(cutoff,)).fetchone()['n']
    movies=c.execute("select count(*) n from tautulli_history where watched_at>=? and kind='movie'",(cutoff,)).fetchone()['n']
    tvplays=c.execute("select count(*) n from tautulli_history where watched_at>=? and kind='tv'",(cutoff,)).fetchone()['n']
    pm=[dict(r) for r in c.execute("select item_id,count(*) plays,count(distinct user) viewers,coalesce(sum(duration),0) duration,max(watched_at) last_watched from tautulli_history where watched_at>=? and kind='movie' group by item_id order by viewers desc,plays desc limit 10",(cutoff,))]
    pt=[dict(r) for r in c.execute("select item_id,count(*) plays,count(distinct user) viewers,coalesce(sum(duration),0) duration,max(watched_at) last_watched from tautulli_history where watched_at>=? and kind='tv' group by item_id order by viewers desc,plays desc limit 10",(cutoff,))]
    identities={(r['kind'],r['item_id']):dict(r) for r in c.execute('select kind,item_id,title,year,current_item_id from tautulli_media_identity')}
    c.close()

    # Dashboard resolution is deliberately local-only: never call Plex/Tautulli over HTTP here.
    if cache_ready():
        cc=cache_conn()
        for kind,rows,table,idcol in (('movie',pm,'movies','metadata_id'),('tv',pt,'shows','show_id')):
            for r in rows:
                x=cc.execute(f'select title,year,{idcol} current_id from {table} where {idcol}=? limit 1',(r['item_id'],)).fetchone()
                if x:
                    r['title'],r['year'],r['current_item_id']=x['title'],x['year'],x['current_id']
                    continue

                ident=identities.get((kind,r['item_id']))
                if ident and ident.get('title'):
                    r['title'],r['year']=ident['title'],ident.get('year')
                    # A Plex ratingKey can change. Relink by normalized title + year to
                    # the current cache so artwork/details use the live Plex item.
                    title=ident['title'].strip()
                    year=ident.get('year')
                    if year:
                        nx=cc.execute(f'select title,year,{idcol} current_id from {table} where lower(trim(title))=lower(trim(?)) and year=? limit 2',(title,year)).fetchall()
                    else:
                        nx=cc.execute(f'select title,year,{idcol} current_id from {table} where lower(trim(title))=lower(trim(?)) limit 2',(title,)).fetchall()
                    if len(nx)==1:
                        r['current_item_id']=nx[0]['current_id']
                        r['title'],r['year']=nx[0]['title'],nx[0]['year']
                        r['relinked']=True
                    else:
                        r['removed']=True
                else:
                    r['title']='No longer in library'; r['year']=None; r['removed']=True
        cc.close()
    return {'days':days,'plays':total['n'],'hours':round((total['d'] or 0)/3600,1),'users':users,'movies':movies,'episodes':tvplays,'popular_movies':pm,'popular_tv':pt}

def _scheduler_loop():
    last_minute=''
    while True:
        try:
            if setting('tautulli_auto_enabled','0')=='1' and setting('tautulli_api_key') and not TAUTULLI_STATUS.get('running'):
                now=datetime.now(); freq=setting('tautulli_auto_frequency','daily'); hhmm=setting('tautulli_auto_time','01:00'); stamp=now.strftime('%Y-%m-%d %H:%M'); due=False
                if freq=='daily': due=now.strftime('%H:%M')==hhmm
                elif freq=='weekly': due=now.strftime('%a').lower()[:3]==setting('tautulli_auto_day','mon') and now.strftime('%H:%M')==hhmm
                elif freq in ('6h','12h'):
                    hours=int(freq[:-1]); due=now.minute==0 and now.hour%hours==0
                if due and stamp!=last_minute:
                    last_minute=stamp; threading.Thread(target=tautulli_worker,kwargs={'full':False},daemon=True).start()
            if setting('plex_auto_enabled','0')=='1' and not BUILD_STATUS.get('running'):
                now=datetime.now(); freq=setting('plex_auto_frequency','daily'); hhmm=setting('plex_auto_time','03:00'); stamp=now.strftime('%Y-%m-%d %H:%M'); due=False
                if freq=='daily': due=now.strftime('%H:%M')==hhmm
                elif freq=='6h': due=now.minute==0 and now.hour%6==0
                elif freq=='12h': due=now.minute==0 and now.hour%12==0
                if due and setting('plex_last_schedule_stamp','')!=stamp:
                    set_setting('plex_last_schedule_stamp',stamp); threading.Thread(target=refresh_worker,daemon=True).start()
        except Exception: pass
        time.sleep(30)

threading.Thread(target=_scheduler_loop,daemon=True).start()


def _plex_token():
    """Return the saved Plex token, or safely discover the local server token.

    Older installs can have a persisted machineIdentifier but no plex_token row.
    On Windows Plex Media Server keeps its own token in Preferences.xml, so use
    that as a local-only fallback rather than exposing it to the browser.
    """
    token=setting('plex_token','').strip()
    if token: return token
    try:
        local=os.environ.get('LOCALAPPDATA','')
        pref=os.path.join(local,'Plex Media Server','Preferences.xml') if local else ''
        if pref and os.path.exists(pref):
            root=ET.parse(pref).getroot()
            token=(root.attrib.get('PlexOnlineToken') or '').strip()
            if token:
                # Persist it so every Plex feature uses the same local setting next time.
                set_setting('plex_token',token)
                print('[plex] recovered local Plex token from Preferences.xml', flush=True)
                return token
    except Exception as e:
        print(f'[plex] could not recover local Plex token: {type(e).__name__}: {e}', flush=True)
    return ''

def _plex_web_link(item_id):
    machine=setting('plex_machine_id','').strip()
    if not machine: return None
    key=urllib.parse.quote('/library/metadata/'+str(item_id),safe='')
    return f"https://app.plex.tv/desktop/#!/server/{machine}/details?key={key}"

def _plex_poster(item_id):
    """Resolve and proxy Plex artwork without exposing the Plex token to the browser.

    Plex servers can return either JSON or XML for metadata, so support both.
    We also fall back to Plex's direct item-thumb endpoint. Failures are logged
    with enough detail to diagnose them without ever printing the token.
    """
    base=setting('plex_url','http://localhost:32400').rstrip('/'); token=_plex_token()
    if not token:
        print(f'[poster] item {item_id}: no Plex token configured', flush=True)
        return None
    headers={'X-Plex-Token':token,'Accept':'application/json'}
    thumb=None
    try:
        meta=requests.get(f'{base}/library/metadata/{int(item_id)}',headers=headers,timeout=20)
        if meta.ok:
            try:
                data=meta.json()
                items=((data.get('MediaContainer') or {}).get('Metadata') or [])
                if items: thumb=(items[0].get('thumb') or '').strip()
            except (ValueError, TypeError, AttributeError):
                # Some Plex versions ignore Accept: application/json and return XML.
                try:
                    root=ET.fromstring(meta.content)
                    node=root.find('.//Video') or root.find('.//Directory')
                    if node is not None: thumb=(node.attrib.get('thumb') or '').strip()
                except ET.ParseError:
                    pass
        else:
            print(f'[poster] item {item_id}: metadata HTTP {meta.status_code}', flush=True)

        candidates=[]
        if thumb:
            candidates.append(thumb if thumb.startswith(('http://','https://')) else base+'/'+thumb.lstrip('/'))
        # Safe fallback used by Plex for metadata items even when metadata parsing fails.
        candidates.append(f'{base}/library/metadata/{int(item_id)}/thumb')

        seen=set()
        for art_url in candidates:
            if art_url in seen: continue
            seen.add(art_url)
            art=requests.get(art_url,headers={'X-Plex-Token':token,'Accept':'image/*'},timeout=20,allow_redirects=True)
            ctype=(art.headers.get('Content-Type') or '').split(';',1)[0].lower()
            if art.ok and art.content and ctype.startswith('image/'):
                return (art.content,ctype)
            print(f'[poster] item {item_id}: artwork HTTP {art.status_code}, content-type={ctype or "unknown"}', flush=True)
    except requests.RequestException as e:
        print(f'[poster] item {item_id}: Plex request failed: {type(e).__name__}: {e}', flush=True)
    except Exception as e:
        print(f'[poster] item {item_id}: unexpected error: {type(e).__name__}: {e}', flush=True)
    return None

def discord_webhook_send(content=None, embed=None, webhook_url=None):
    url=(webhook_url or setting('discord_webhook_url','')).strip()
    if not url: raise RuntimeError('Discord webhook URL is not configured')
    payload={'allowed_mentions':{'parse':[]}}; item_id=None
    if content: payload['content']=str(content)[:1900]
    if embed:
        e=dict(embed); item_id=e.pop('_plex_item_id',None)
        if e.get('title'): e['title']=str(e['title'])[:256]
        if e.get('description'): e['description']=str(e['description'])[:4096]
        e['fields']=[{'name':str(x.get('name',''))[:256],'value':str(x.get('value',''))[:1024],'inline':bool(x.get('inline',True))} for x in (e.get('fields') or [])][:25]
        if item_id:
            link=_plex_web_link(item_id)
            if link: e['url']=link
        payload['embeds']=[e]
    poster=_plex_poster(item_id) if item_id else None
    if poster:
        payload['embeds'][0]['thumbnail']={'url':'attachment://poster.jpg'}
        files={'files[0]':('poster.jpg',poster[0],poster[1])}
        r=requests.post(url,data={'payload_json':json.dumps(payload)},files=files,timeout=30)
    else:
        r=requests.post(url,json=payload,timeout=30)
    if r.status_code not in (200,204): raise RuntimeError(f'Discord returned HTTP {r.status_code}')

def _discord_embed(title, description='', fields=None, footer='MyCouch', colour=5793266):
    e={'title':title,'description':description,'color':colour,'fields':fields or [],'footer':{'text':footer}}
    return e

def _title_for(kind,item_id):
    if not cache_ready(): return None
    c=cache_conn()
    try:
        if kind=='movie': r=c.execute('select title,year,size_gb from movies where metadata_id=? order by size_gb desc limit 1',(item_id,)).fetchone()
        else: r=c.execute('select title,year,size_gb from shows where show_id=? limit 1',(item_id,)).fetchone()
        return dict(r) if r else None
    finally: c.close()

def _discord_recent(category,item_key,cooldown_days):
    c=config(); cutoff=int(time.time()-cooldown_days*86400)
    r=c.execute('select 1 from discord_posts where category=? and item_key=? and posted_at>=? limit 1',(category,item_key,cutoff)).fetchone(); c.close()
    return bool(r)

def _record_discord(category,item_key,message):
    c=config(); c.execute('insert into discord_posts(category,item_key,message,posted_at) values(?,?,?,?)',(category,item_key,message,int(time.time()))); c.commit(); c.close()

def _plex_ratings(kind, ids):
    """Best-effort rating lookup from the selected Plex DB without changing the cache schema."""
    ids=[int(x) for x in ids if x is not None]
    if not ids: return {}
    try:
        db=get_db_path()
        c=sqlite3.connect(db); c.row_factory=sqlite3.Row
        cols={r['name'] for r in c.execute('pragma table_info(metadata_items)')}
        rating_cols=[x for x in ('rating','audience_rating','user_rating') if x in cols]
        if not rating_cols: c.close(); return {}
        ph=','.join('?' for _ in ids)
        rows=c.execute(f"select id,{','.join(rating_cols)} from metadata_items where id in ({ph})",ids).fetchall(); c.close()
        out={}
        for r in rows:
            vals=[]
            for col in rating_cols:
                try:
                    v=float(r[col]) if r[col] is not None else None
                    if v is not None and v>0: vals.append(v)
                except (TypeError,ValueError): pass
            if vals: out[int(r['id'])]=max(vals)
        return out
    except Exception:
        return {}

def _recommendation_candidates(kind, days=30):
    """Return ranked recommendation candidates using rating + discovery + activity signals."""
    if not cache_ready() or setting('tautulli_authoritative','0')!='1': return []
    rows=movies() if kind=='movie' else shows()
    # Collapse movie versions so one title does not get multiple chances.
    if kind=='movie':
        unique={}
        for r in rows:
            key=(r.get('title'),r.get('year'))
            if key not in unique or (r.get('size_gb') or 0)>(unique[key].get('size_gb') or 0): unique[key]=r
        rows=list(unique.values())
    ratings=_plex_ratings(kind,[r['metadata_id'] if kind=='movie' else r['show_id'] for r in rows])
    now=int(time.time()); recent_cut=now-days*86400; ranked=[]
    for r in rows:
        if r.get('protected'): continue
        item_id=int(r['metadata_id'] if kind=='movie' else r['show_id'])
        a=r.get('tautulli') or {}; plays=int(a.get('plays') or 0);
        try: viewers=len(json.loads(a.get('users_json') or '[]'))
        except Exception: viewers=0
        last=int(a.get('last_watched') or 0)
        rating=ratings.get(item_id)
        # High ratings lead; zero/low discovery gets a boost; some recent popularity can also qualify.
        score=(rating or 0)*10
        if viewers==0: score+=28
        elif viewers<=3: score+=15
        if plays==0: score+=10
        if last>=recent_cut: score+=min(18,viewers*2+min(plays,10))
        age=float(r.get('age') or 0)
        if age>=0.25: score+=4
        # If no rating exists, require a useful discovery/popularity signal rather than pure randomness.
        if rating is None and viewers==0 and plays==0: score-=12
        ranked.append((score,r,rating,viewers,plays,last))
    ranked.sort(key=lambda x:x[0],reverse=True)
    return ranked[:80]

def _recommendation_pick(kind, days=30, force=False):
    category='movie_recommendation' if kind=='movie' else 'tv_recommendation'
    cooldown=int(setting('discord_cooldown_days','90') or 90)
    pool=_recommendation_candidates(kind,days)
    eligible=[]
    for x in pool:
        r=x[1]; item_id=str(r['metadata_id'] if kind=='movie' else r['show_id'])
        if force or not _discord_recent(category,item_id,cooldown): eligible.append(x)
    if not eligible: return None
    # Choose among the strongest few to keep recommendations varied while still useful.
    top=eligible[:min(12,len(eligible))]
    idx=int(time.time()//86400)%len(top); score,r,rating,viewers,plays,last=top[idx]
    item_id=str(r['metadata_id'] if kind=='movie' else r['show_id'])
    label=r['title']+(f' ({r["year"]})' if r.get('year') else '')
    if viewers==0 and rating and rating>=7: reason='Highly rated and still undiscovered across your Plex users.'
    elif viewers==0: reason='An unwatched title waiting to be discovered.'
    elif viewers<=3 and rating and rating>=7: reason='Highly rated, but only a few people have discovered it so far.'
    elif last and last>=int(time.time()-days*86400): reason='A strong pick that has been getting attention recently.'
    else: reason='A worthwhile library pick based on rating and viewing activity.'
    fields=[]
    if rating: fields.append({'name':'Rating','value':f'{rating:.1f}/10','inline':True})
    fields.extend([{'name':'Viewers','value':f'{viewers:,}','inline':True},{'name':'Plays' if kind=='movie' else 'Episode Plays','value':f'{plays:,}','inline':True}])
    if kind=='tv': fields.append({'name':'Episodes','value':f'{int(r.get("episodes") or 0):,}','inline':True})
    else:
        mins=round((r.get('duration') or 0)/60000) if r.get('duration') else 0
        if mins: fields.append({'name':'Runtime','value':f'{mins} min','inline':True})
    title=('Movie Recommendation: ' if kind=='movie' else 'TV Recommendation: ')+label
    e=_discord_embed(title,reason,fields,'MyCouch • Recommendation'); e['_plex_item_id']=item_id
    return (category,item_id,e)

def discord_stat_candidates(days=30):
    if setting('tautulli_authoritative','0')!='1': return []
    enabled=set(x for x in setting('discord_categories','popular_movie,popular_tv,viewing_hours,storage_hog,forgotten,movie_recommendation,tv_recommendation').split(',') if x)
    stats=tautulli_dashboard_stats(days); out=[]
    if 'movie_recommendation' in enabled:
        x=_recommendation_pick('movie',days);
        if x: out.append(x)
    if 'tv_recommendation' in enabled:
        x=_recommendation_pick('tv',days);
        if x: out.append(x)
    footer=f'MyCouch • Last {days} days'
    if 'viewing_hours' in enabled:
        e=_discord_embed('Plex viewing activity',f'Viewing activity across the library over the last {days} days.',[
            {'name':'Viewing Hours','value':f'{stats["hours"]:,.1f}','inline':True},
            {'name':'Plays','value':f'{stats["plays"]:,}','inline':True},
            {'name':'Active Users','value':f'{stats["users"]:,}','inline':True},
            {'name':'Movie Plays','value':f'{stats["movies"]:,}','inline':True},
            {'name':'TV Plays','value':f'{stats["episodes"]:,}','inline':True}],footer)
        out.append(('viewing_hours',f'period-{days}',e))
    if 'popular_movie' in enabled and stats['popular_movies']:
        r=stats['popular_movies'][0]; label=r['title']+(f' ({r["year"]})' if r.get('year') else '')
        e=_discord_embed(f'Popular Movie: {label}',f'One of the most watched movies on Plex over the last {days} days.',[
            {'name':'Viewers','value':f'{r["viewers"]:,}','inline':True},
            {'name':'Plays','value':f'{r["plays"]:,}','inline':True},
            {'name':'Watch Time','value':f'{(r["duration"] or 0)/3600:,.1f} hours','inline':True}],footer); e['_plex_item_id']=str(r['item_id'])
        out.append(('popular_movie',str(r['item_id']),e))
    if 'popular_tv' in enabled and stats['popular_tv']:
        r=stats['popular_tv'][0]; label=r['title']+(f' ({r["year"]})' if r.get('year') else '')
        e=_discord_embed(f'Popular TV: {label}',f'One of the most watched shows on Plex over the last {days} days.',[
            {'name':'Viewers','value':f'{r["viewers"]:,}','inline':True},
            {'name':'Episode Plays','value':f'{r["plays"]:,}','inline':True},
            {'name':'Watch Time','value':f'{(r["duration"] or 0)/3600:,.1f} hours','inline':True}],footer); e['_plex_item_id']=str(r['item_id'])
        out.append(('popular_tv',str(r['item_id']),e))
    if cache_ready() and 'storage_hog' in enabled:
        c=cache_conn(); m=c.execute('select metadata_id item_id,title,size_gb from movies order by size_gb desc limit 1').fetchone(); sh=c.execute('select show_id item_id,title,size_gb from shows order by size_gb desc limit 1').fetchone(); c.close()
        candidates=[dict(x) for x in (m,sh) if x]
        if candidates:
            r=max(candidates,key=lambda x:x['size_gb'] or 0)
            e=_discord_embed(f'Library Storage Hog: {r["title"]}','This title currently takes up the most space in the Plex library.',[{'name':'Storage','value':f'{r["size_gb"]:,.1f} GB','inline':True}],'MyCouch • Library stat')
            out.append(('storage_hog',str(r['item_id']),e))
    if cache_ready() and 'forgotten' in enabled:
        cutoff=int(time.time()-730*86400); shows_now=shows(); old=[x for x in shows_now if not x.get('protected') and x['size_gb']>=20 and (not x.get('tautulli') or not x['tautulli'].get('last_watched') or x['tautulli']['last_watched']<cutoff)]
        if old:
            r=max(old,key=lambda x:x['size_gb'])
            e=_discord_embed(f'Forgotten Show: {r["title"]}','This sizeable show has had no activity in at least two years.',[{'name':'Storage','value':f'{r["size_gb"]:,.1f} GB','inline':True},{'name':'Activity','value':'None in 2+ years','inline':True}],'MyCouch • Library archaeology')
            out.append(('forgotten',str(r['show_id']),e))
    return out

def send_random_discord_stat(force=False):
    days=int(setting('discord_stats_days','30') or 30); cooldown=int(setting('discord_cooldown_days','90') or 90)
    candidates=discord_stat_candidates(days)
    available=[x for x in candidates if force or not _discord_recent(x[0],x[1],cooldown)]
    if not available and candidates: available=candidates if force else []
    if not available: raise RuntimeError('No eligible Discord stat is available with the current categories/cooldown')
    # Rotate deterministically through eligible categories; avoids repeated random picks after restarts.
    c=config(); last=c.execute('select category from discord_posts order by id desc limit 1').fetchone(); c.close()
    pick=available[0]
    if last:
        for x in available:
            if x[0]!=last['category']: pick=x; break
    route_url=None
    if pick[0]=='movie_recommendation': route_url=setting('discord_movie_webhook_url','').strip() or None
    elif pick[0]=='tv_recommendation': route_url=setting('discord_tv_webhook_url','').strip() or None
    discord_webhook_send(embed=pick[2],webhook_url=route_url); _record_discord(pick[0],pick[1],json.dumps(pick[2])); set_setting('discord_last_post',datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    return pick

def _discord_bot_worker():
    """Run the optional Discord slash-command bot in its own thread/event loop."""
    token=setting('discord_bot_token','').strip()
    if setting('discord_bot_enabled','0')!='1' or not token:
        return
    try:
        import asyncio
        import discord
        from discord import app_commands
        guild_id=setting('discord_bot_guild_id','').strip()
        target_guild=discord.Object(id=int(guild_id)) if guild_id else None
        DISCORD_BOT_STATUS.update(running=True,connected=False,user='',error='',commands_synced=False,sync_count=0,guild_id=guild_id)
        intents=discord.Intents.none()
        client=discord.Client(intents=intents)
        tree=app_commands.CommandTree(client)

        # Register directly as a guild command when a Guild ID is configured.
        # This avoids relying on copying a global command into the guild at startup.
        command_kwargs={'name':'search','description':'Search the MyCouch movie library'}
        if target_guild is not None:
            command_kwargs['guild']=target_guild

        @tree.command(**command_kwargs)
        @app_commands.describe(query='Describe the movie you want to find')
        async def library_search(interaction: discord.Interaction, query: str):
            ephemeral=setting('discord_bot_ephemeral','1')=='1'
            await interaction.response.defer(thinking=True,ephemeral=ephemeral)
            q=' '.join((query or '').split())[:500]
            if not q:
                await interaction.followup.send('Enter something to search for.',ephemeral=ephemeral)
                return
            try:
                results=await asyncio.to_thread(_lexical_smart_search,q,5)
                if not results:
                    await interaction.followup.send(f'No MyCouch matches for **{q}**.',ephemeral=ephemeral)
                    return
                embeds=[]; files=[]
                for i,r in enumerate(results):
                    label=r.get('title') or 'Untitled'
                    if r.get('year'): label+=f' ({r["year"]})'
                    summary=(r.get('summary') or 'No synopsis available.').strip()
                    if len(summary)>700: summary=summary[:697]+'…'
                    e=discord.Embed(title=label,url=r.get('plex_url') or None,description=summary,colour=discord.Colour(0x5865F2))
                    genres=r.get('genres_display') or ''
                    if genres: e.add_field(name='Genres',value=genres[:1024],inline=False)
                    e.add_field(name='Match',value=r.get('match_label') or 'Match',inline=True)
                    if r.get('size_gb') is not None: e.add_field(name='Storage',value=f'{float(r["size_gb"]):,.1f} GB',inline=True)
                    e.set_footer(text=f'MyCouch • Search result {i+1} of {len(results)}')
                    try:
                        poster=await asyncio.to_thread(_plex_poster,int(r['metadata_id']))
                        if poster:
                            fn=f'poster_{i}.jpg'
                            files.append(discord.File(io.BytesIO(poster[0]),filename=fn))
                            e.set_thumbnail(url=f'attachment://{fn}')
                    except Exception as ex:
                        print(f'[discord bot] poster failed for {r.get("metadata_id")}: {ex}',flush=True)
                    embeds.append(e)
                await interaction.followup.send(content=f'**MyCouch search:** {q}',embeds=embeds,files=files,ephemeral=ephemeral)
            except Exception as e:
                print(f'[discord bot] /search failed: {type(e).__name__}: {e}',flush=True)
                await interaction.followup.send('MyCouch could not complete that search.',ephemeral=ephemeral)

        synced_once=False
        @client.event
        async def on_ready():
            nonlocal synced_once
            DISCORD_BOT_STATUS.update(connected=True,user=str(client.user),error='')
            print(f'[discord bot] connected as {client.user} (application id {client.application_id})',flush=True)
            if synced_once:
                return
            synced_once=True
            try:
                if target_guild is not None:
                    print(f'[discord bot] registering commands for guild {guild_id}',flush=True)
                    synced=await tree.sync(guild=target_guild)
                    names=', '.join('/'+cmd.name for cmd in synced) or '(none)'
                    print(f'[discord bot] synced {len(synced)} guild command(s): {names}',flush=True)
                else:
                    print('[discord bot] no Guild ID configured; syncing globally',flush=True)
                    synced=await tree.sync()
                    names=', '.join('/'+cmd.name for cmd in synced) or '(none)'
                    print(f'[discord bot] synced {len(synced)} global command(s): {names}',flush=True)
                DISCORD_BOT_STATUS.update(commands_synced=True,sync_count=len(synced))
                if not any(cmd.name=='search' for cmd in synced):
                    DISCORD_BOT_STATUS['error']='Discord sync completed but /search was not returned by Discord.'
                    print('[discord bot] WARNING: Discord sync returned no /search command',flush=True)
            except Exception as e:
                DISCORD_BOT_STATUS.update(commands_synced=False,sync_count=0,error=f'Command sync failed: {type(e).__name__}: {e}')
                print(f'[discord bot] command sync failed: {type(e).__name__}: {e}',flush=True)

        client.run(token,log_handler=None)
    except Exception as e:
        DISCORD_BOT_STATUS.update(running=False,connected=False,error=str(e))
        print(f'[discord bot] stopped: {type(e).__name__}: {e}',flush=True)

def _discord_scheduler_loop():
    last_minute=''
    while True:
        try:
            if setting('discord_auto_enabled','0')=='1' and setting('discord_webhook_url'):
                now=datetime.now(); hhmm=setting('discord_post_time','19:00'); freq=setting('discord_frequency','weekly'); stamp=now.strftime('%Y-%m-%d %H:%M'); due=False
                if freq=='daily': due=now.strftime('%H:%M')==hhmm
                elif freq=='3xweek': due=now.weekday() in (0,2,4) and now.strftime('%H:%M')==hhmm
                elif freq=='weekly': due=now.weekday()==int(setting('discord_weekday','4') or 4) and now.strftime('%H:%M')==hhmm
                if due and stamp!=last_minute:
                    last_minute=stamp
                    try: send_random_discord_stat()
                    except Exception as e: set_setting('discord_last_error',str(e))
        except Exception: pass
        time.sleep(30)

threading.Thread(target=_discord_scheduler_loop,daemon=True).start()

def _backup_filename(path):
    base=os.path.splitext(os.path.basename(path))[0]
    return f"{base}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"

def sqlite_online_backup(src_path,dst_path):
    # SQLite's online backup API creates a consistent snapshot even while the app is running.
    src=sqlite3.connect(src_path,timeout=60)
    try:
        dst=sqlite3.connect(dst_path,timeout=60)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

def prune_backups(folder,keep):
    keep=max(1,min(int(keep),365))
    for stem in ('auditor-','auditor-cache-'):
        files=sorted((x for x in os.listdir(folder) if x.startswith(stem) and x.endswith('.db')),reverse=True)
        for name in files[keep:]:
            try: os.remove(os.path.join(folder,name))
            except OSError: pass

def run_backup():
    if not BACKUP_LOCK.acquire(blocking=False): return False
    BACKUP_STATUS.update(running=True,error=None)
    try:
        folder=setting('backup_path','').strip()
        if not folder: raise RuntimeError('Backup destination is not configured')
        os.makedirs(folder,exist_ok=True)
        keep=int(setting('backup_keep','14') or 14)
        for src in (CONFIG_DB,CACHE_DB):
            if os.path.exists(src): sqlite_online_backup(src,os.path.join(folder,_backup_filename(src)))
        prune_backups(folder,keep)
        stamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        set_setting('backup_last_success',stamp)
        BACKUP_STATUS.update(running=False,last_backup=stamp,error=None)
        return True
    except Exception as e:
        BACKUP_STATUS.update(running=False,error=str(e))
        return False
    finally:
        BACKUP_LOCK.release()

def backup_worker():
    run_backup()

def _backup_scheduler_loop():
    last_minute=''
    while True:
        try:
            if setting('backup_auto_enabled','0')=='1' and setting('backup_path') and not BACKUP_STATUS.get('running'):
                now=datetime.now(); hhmm=setting('backup_time','02:00'); stamp=now.strftime('%Y-%m-%d %H:%M')
                if now.strftime('%H:%M')==hhmm and stamp!=last_minute:
                    last_minute=stamp
                    threading.Thread(target=backup_worker,daemon=True).start()
        except Exception: pass
        time.sleep(30)

threading.Thread(target=_backup_scheduler_loop,daemon=True).start()

def normpath(p):
    if not p: return ''
    return os.path.normcase(os.path.normpath(p)).rstrip('\\/').lower()

def arr_matches(kind):
    c=config(); rows={r['item_id']:dict(r) for r in c.execute('select * from arr_matches where kind=?',(kind,))}; c.close(); return rows

def set_arr_status(**kw):
    ARR_STATUS.update(kw)
    if ARR_STATUS.get('started_at'):
        ARR_STATUS['elapsed']=round(time.time()-ARR_STATUS['started_at'],1)

def sync_arr_matches():
    """Read-only Arr sync. Matching is exact path based; no title guessing."""
    results={}
    c=config()
    started=time.time()
    set_arr_status(running=True,complete=False,error=None,stage='Loading Radarr',percent=3,current=0,total=0,message='Requesting movie library from Radarr…',started_at=started,radarr={},sonarr={})
    try:
        try:
            rad=arr_request('radarr','movie')
            set_arr_status(stage='Matching Radarr',percent=15,current=0,total=len(rad),message=f'Loaded {len(rad):,} Radarr movies…')
            bypath={normpath(x.get('path')):x for x in rad if x.get('path')}
            c.execute("delete from arr_matches where kind='movie'")
            movie_rows=qcache('select metadata_id,title,path from movies')
            unique={}
            for m in movie_rows: unique.setdefault(m['metadata_id'],m)
            total=len(unique); matched=0
            for i,m in enumerate(unique.values(),1):
                parent=normpath(os.path.dirname(m['path'] or '')); a=bypath.get(parent)
                if a:
                    c.execute('insert or replace into arr_matches(kind,item_id,arr_id,title_slug,arr_title,arr_path,matched_by) values(?,?,?,?,?,?,?)',('movie',m['metadata_id'],a.get('id'),a.get('titleSlug',''),a.get('title',''),a.get('path',''),'exact path')); matched+=1
                if i==1 or i%100==0 or i==total:
                    set_arr_status(stage='Matching Radarr',percent=15+int(20*i/max(total,1)),current=i,total=total,message=f'{matched:,} matched · {i:,} / {total:,} Plex movies checked')
            c.commit()
            results['radarr']={'ok':True,'items':len(rad),'plex_items':total,'matched':matched}
            ARR_STATUS['radarr']=results['radarr']
        except Exception as e:
            results['radarr']={'ok':False,'error':str(e)}; ARR_STATUS['radarr']=results['radarr']

        set_arr_status(stage='Loading Sonarr',percent=38,current=0,total=0,message='Requesting series library from Sonarr — your library may take ~20–30 seconds to respond…')
        try:
            son=arr_request('sonarr','series')
            # Exact normalized series path lookup. For each episode, walk its parent directories
            # rather than comparing it with every Sonarr series path.
            bypath={normpath(x.get('path')):x for x in son if x.get('path')}
            c.execute("delete from arr_matches where kind='tv'")
            show_rows=qcache('select show_id,title from shows'); total=len(show_rows); matched=0
            set_arr_status(stage='Matching Sonarr',percent=58,current=0,total=total,message=f'Loaded {len(son):,} Sonarr series · matching exact paths…')
            for i,sh in enumerate(show_rows,1):
                eps=qcache('select path from episodes where show_id=? and path is not null limit 5',(sh['show_id'],))
                a=None
                for e in eps:
                    cur=normpath(os.path.dirname(e['path'] or ''))
                    # Walk from episode folder toward the drive root looking for an exact Sonarr series path.
                    for _ in range(8):
                        if cur in bypath:
                            a=bypath[cur]; break
                        parent=normpath(os.path.dirname(cur))
                        if not parent or parent==cur: break
                        cur=parent
                    if a: break
                if a:
                    c.execute('insert or replace into arr_matches(kind,item_id,arr_id,title_slug,arr_title,arr_path,matched_by) values(?,?,?,?,?,?,?)',('tv',sh['show_id'],a.get('id'),a.get('titleSlug',''),a.get('title',''),a.get('path',''),'exact path')); matched+=1
                if i==1 or i%25==0 or i==total:
                    set_arr_status(stage='Matching Sonarr',percent=58+int(35*i/max(total,1)),current=i,total=total,message=f'{matched:,} matched · {i:,} / {total:,} Plex shows checked')
            c.commit()
            results['sonarr']={'ok':True,'items':len(son),'plex_items':total,'matched':matched}
            ARR_STATUS['sonarr']=results['sonarr']
        except Exception as e:
            results['sonarr']={'ok':False,'error':str(e)}; ARR_STATUS['sonarr']=results['sonarr']

        ok=all(results.get(k,{}).get('ok') for k in ('radarr','sonarr'))
        summary=[]
        for k in ('radarr','sonarr'):
            x=results.get(k,{})
            summary.append(f"{k.title()} {x.get('matched',0):,}/{x.get('plex_items',x.get('items',0)):,} Plex items matched" if x.get('ok') else f"{k.title()} failed: {x.get('error','unknown error')}")
        set_arr_status(running=False,complete=True,stage='Complete' if ok else 'Completed with warnings',percent=100,current=0,total=0,message=' · '.join(summary),elapsed=round(time.time()-started,1))
        return results
    except Exception as e:
        set_arr_status(running=False,complete=False,stage='Failed',error=str(e),message=str(e),elapsed=round(time.time()-started,1))
        raise
    finally:
        c.close()

def arr_sync_worker():
    if not ARR_LOCK.acquire(blocking=False): return
    try:
        sync_arr_matches()
    except Exception:
        pass
    finally:
        ARR_LOCK.release()

def _natural_key(value):
    # Use ASCII digits only. str.isdigit() is True for Unicode characters such
    # as superscript ², but int('²') is invalid and breaks SQLite collation.
    value = '' if value is None else str(value)
    return [int(x) if x and all('0' <= ch <= '9' for ch in x) else x.casefold()
            for x in re.split(r'([0-9]+)', value)]

def _natural_cmp(a,b):
    ka,kb=_natural_key(a),_natural_key(b)
    return (ka>kb)-(ka<kb)

def cache_conn():
    c=sqlite3.connect(CACHE_DB); c.row_factory=sqlite3.Row; c.create_collation('NATURAL',_natural_cmp); return c

def cache_ready():
    if not os.path.exists(CACHE_DB): return False
    try:
        c=cache_conn(); row=c.execute("select value from cache_meta where key='refreshed_at'").fetchone(); c.close(); return bool(row)
    except Exception: return False

def cache_meta():
    if not cache_ready(): return {}
    c=cache_conn(); d={r['key']:r['value'] for r in c.execute('select key,value from cache_meta')}; c.close(); return d

def age_years(ts): return round((datetime.now(timezone.utc).timestamp()-ts)/(365.25*86400),1) if ts else 0

def protected_set(kind):
    c=config(); s={r['title'] for r in c.execute('select title from protected where kind=?',(kind,))}; c.close(); return s

def review_ids(kind):
    c=config(); s={r['item_id'] for r in c.execute('select item_id from review where kind=?',(kind,))}; c.close(); return s

def resolution(h):
    h=int(h or 0); return '4K' if h>=2000 else '1080p' if h>=1000 else '720p' if h>=700 else 'SD'

MOVIE_SQL="""select ls.name library,mi.id metadata_id,mi.title,mi.year,mi.added_at,med.id media_id,med.width,med.height,med.video_codec codec,med.audio_codec,med.bitrate,med.duration,mp.size size_bytes,mp.file path,case when exists(select 1 from metadata_item_settings s where s.guid=mi.guid and coalesce(s.view_count,0)>0) then 1 else 0 end watched from metadata_items mi join library_sections ls on ls.id=mi.library_section_id join media_items med on med.metadata_item_id=mi.id and med.deleted_at is null join media_parts mp on mp.media_item_id=med.id and mp.deleted_at is null where mi.metadata_type=1 and mi.deleted_at is null"""
TV_SQL="""select ls.name library,sh.id show_id,sh.title,sh.year,sh.added_at,count(*) episodes,sum(case when med.height<700 then 1 else 0 end) sd,sum(case when med.height>=700 and med.height<1000 then 1 else 0 end) p720,sum(case when med.height>=1000 and med.height<2000 then 1 else 0 end) p1080,sum(case when med.video_codec='h264' then 1 else 0 end) h264,sum(case when med.video_codec='hevc' then 1 else 0 end) hevc,sum(case when med.video_codec='av1' then 1 else 0 end) av1,sum(mp.size) size_bytes,sum(med.duration) duration_ms,sum(case when exists(select 1 from metadata_item_settings s where s.guid=ep.guid and coalesce(s.view_count,0)>0) then 1 else 0 end) watched_episodes from metadata_items ep join metadata_items se on ep.parent_id=se.id join metadata_items sh on se.parent_id=sh.id join library_sections ls on ls.id=ep.library_section_id join media_items med on med.metadata_item_id=ep.id and med.deleted_at is null join media_parts mp on mp.media_item_id=med.id and mp.deleted_at is null where ep.metadata_type=4 and ep.deleted_at is null and med.height<2000 and ls.name<>'Sports' group by sh.id"""

def set_build_status(**kw):
    BUILD_STATUS.update(kw)
    if BUILD_STATUS.get('started_at'):
        BUILD_STATUS['elapsed']=round(time.time()-BUILD_STATUS['started_at'],1)

def cleanup_plex_snapshots(max_age_seconds=21600):
    """Remove Auditor-owned Plex snapshot files left behind by completed/crashed refreshes.

    Startup cleanup only removes files older than six hours so a snapshot that may still
    belong to another running Auditor process is left alone.
    """
    workdir=os.path.dirname(__file__)
    now=time.time(); removed=0
    try:
        for name in os.listdir(workdir):
            if not name.startswith('plex-snapshot-'):
                continue
            if not (name.endswith('.db') or name.endswith('.db-wal') or name.endswith('.db-shm')):
                continue
            path=os.path.join(workdir,name)
            try:
                if now-os.path.getmtime(path) < max_age_seconds:
                    continue
                os.remove(path); removed+=1
            except OSError:
                pass
    except OSError:
        pass
    if removed:
        print(f'[snapshot] cleaned up {removed} stale Plex snapshot file(s)')
    return removed

def _remove_snapshot_family(snapshot):
    """Remove one temporary snapshot and its SQLite WAL/SHM sidecars."""
    for path in (snapshot, snapshot+'-wal', snapshot+'-shm'):
        try:
            if os.path.exists(path): os.remove(path)
        except OSError:
            pass

def refresh_cache():
    source=get_db_path(); workdir=os.path.dirname(__file__)
    fd,snapshot=tempfile.mkstemp(prefix='plex-snapshot-',suffix='.db',dir=workdir); os.close(fd)
    build=CACHE_DB+'.building'
    started=time.time()
    set_build_status(running=True,complete=False,error=None,stage='Copying Plex database',percent=2,current=0,total=0,message='Creating a safe snapshot of the selected Plex database…',started_at=started)
    try:
        # SQLite online backup gives a consistent snapshot even when the live Plex DB is open.
        try:
            src_live=sqlite3.connect('file:'+source.replace('\\','/')+'?mode=ro',uri=True,timeout=60)
            snap=sqlite3.connect(snapshot)
            src_live.backup(snap)
            snap.close(); src_live.close()
        except Exception:
            # Backup files/non-standard SQLite builds can still be copied safely as a fallback.
            shutil.copy2(source,snapshot)
        set_build_status(stage='Opening database',percent=8,message='Opening safe local Plex snapshot read-only…')
        src=sqlite3.connect('file:'+snapshot.replace('\\','/')+'?mode=ro',uri=True); src.row_factory=sqlite3.Row
        if os.path.exists(build): os.remove(build)
        dst=sqlite3.connect(build)
        dst.executescript("""
          create table cache_meta(key text primary key,value text);
          create table movies(library text,metadata_id integer,title text,year integer,added_at integer,media_id integer,width integer,height integer,codec text,audio_codec text,bitrate integer,duration integer,size_bytes integer,path text,watched integer,size_gb real,resolution text,age real,summary text,genres text);
          create table shows(library text,show_id integer primary key,title text,year integer,added_at integer,episodes integer,sd integer,p720 integer,p1080 integer,h264 integer,hevc integer,av1 integer,size_bytes integer,duration_ms integer,watched_episodes integer,size_gb real,hours real,gbph real,pct real,age real);
          create table episodes(show_id integer,season integer,episode integer,title text,height integer,codec text,audio_codec text,duration integer,size_bytes integer,path text,watched integer,size_gb real,resolution text);
        """)
        set_build_status(stage='Reading movies',percent=10,message='Reading movie metadata…')
        mrows=src.execute(MOVIE_SQL).fetchall(); total=len(mrows)
        for i,r in enumerate(mrows,1):
            d=dict(r); size=round((d['size_bytes'] or 0)/1073741824,2)
            summary=''; genres=''
            try:
                mr=src.execute('select summary from metadata_items where id=?',(d['metadata_id'],)).fetchone(); summary=(mr['summary'] or '') if mr else ''
                gr=src.execute("select group_concat(distinct t.tag) g from taggings tg join tags t on t.id=tg.tag_id where tg.metadata_item_id=? and t.tag_type=1 and trim(coalesce(t.tag,''))<>''",(d['metadata_id'],)).fetchone(); genres=(gr['g'] or '') if gr else ''
            except Exception: pass
            dst.execute('insert into movies values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(d['library'],d['metadata_id'],d['title'],d['year'],d['added_at'],d['media_id'],d['width'],d['height'],d['codec'],d['audio_codec'],d['bitrate'],d['duration'],d['size_bytes'],d['path'],d['watched'],size,resolution(d['height']),age_years(d['added_at']),summary,genres))
            if i==1 or i%100==0 or i==total: set_build_status(stage='Processing movies',percent=10+int(20*i/max(total,1)),current=i,total=total,message=f'{i:,} / {total:,} movie files')
        set_build_status(stage='Reading TV shows',percent=31,current=0,total=0,message='Calculating TV show statistics…')
        trows=src.execute(TV_SQL).fetchall(); total=len(trows)
        for i,r in enumerate(trows,1):
            d=dict(r); size=round((d['size_bytes'] or 0)/1073741824,2); hours=round((d['duration_ms'] or 0)/3600000,1); gbph=round(size/hours,2) if hours else 0; pct=round((d['watched_episodes'] or 0)*100/(d['episodes'] or 1),1)
            dst.execute('insert into shows values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(d['library'],d['show_id'],d['title'],d['year'],d['added_at'],d['episodes'],d['sd'],d['p720'],d['p1080'],d['h264'],d['hevc'],d['av1'],d['size_bytes'],d['duration_ms'],d['watched_episodes'],size,hours,gbph,pct,age_years(d['added_at'])))
            if i==1 or i%50==0 or i==total: set_build_status(stage='Processing TV shows',percent=31+int(14*i/max(total,1)),current=i,total=total,message=f'{i:,} / {total:,} TV shows')
        set_build_status(stage='Reading episodes',percent=46,current=0,total=0,message='Reading TV episode metadata…')
        eps=src.execute("""select sh.id show_id,se.[index] season,ep.[index] episode,ep.title,med.height,med.video_codec codec,med.audio_codec,med.duration,mp.size size_bytes,mp.file path,case when exists(select 1 from metadata_item_settings x where x.guid=ep.guid and coalesce(x.view_count,0)>0) then 1 else 0 end watched from metadata_items ep join metadata_items se on ep.parent_id=se.id join metadata_items sh on se.parent_id=sh.id join library_sections ls on ls.id=ep.library_section_id join media_items med on med.metadata_item_id=ep.id and med.deleted_at is null join media_parts mp on mp.media_item_id=med.id and mp.deleted_at is null where ep.metadata_type=4 and ep.deleted_at is null and ls.name<>'Sports'""").fetchall(); total=len(eps)
        for i,r in enumerate(eps,1):
            d=dict(r); size=round((d['size_bytes'] or 0)/1073741824,3)
            dst.execute('insert into episodes values(?,?,?,?,?,?,?,?,?,?,?,?,?)',(d['show_id'],d['season'],d['episode'],d['title'],d['height'],d['codec'],d['audio_codec'],d['duration'],d['size_bytes'],d['path'],d['watched'],size,resolution(d['height'])))
            if i==1 or i%500==0 or i==total: set_build_status(stage='Processing TV episodes',percent=46+int(43*i/max(total,1)),current=i,total=total,message=f'{i:,} / {total:,} TV episodes')
        set_build_status(stage='Building indexes',percent=91,current=0,total=0,message='Optimising the local cache…')
        dst.executescript("""create index ix_movies_title on movies(title); create index ix_movies_meta on movies(metadata_id); create index ix_movies_flags on movies(watched,age,resolution,codec,size_gb); create index ix_shows_title on shows(title); create index ix_shows_flags on shows(watched_episodes,age,gbph,size_gb); create index ix_episodes_show on episodes(show_id,season,episode);""")
        set_build_status(stage='Finalising cache',percent=97,message='Saving cache metadata and swapping databases…')
        meta={'refreshed_at':datetime.now().astimezone().isoformat(timespec='seconds'),'source_db':source,'movie_files':str(len(mrows)),'tv_shows':str(len(trows)),'episodes':str(len(eps))}
        dst.executemany('insert into cache_meta(key,value) values(?,?)',meta.items()); dst.commit(); dst.close(); src.close(); os.replace(build,CACHE_DB)
        set_build_status(running=False,complete=True,stage='Complete',percent=100,current=0,total=0,message=f"{len(mrows):,} movie files · {len(trows):,} shows · {len(eps):,} episodes",elapsed=round(time.time()-started,1))
        return meta
    except Exception as e:
        set_build_status(running=False,complete=False,stage='Failed',error=str(e),message=str(e),elapsed=round(time.time()-started,1))
        raise
    finally:
        _remove_snapshot_family(snapshot)
        for f in (build, build+'-wal', build+'-shm'):
            try:
                if os.path.exists(f): os.remove(f)
            except OSError: pass

def refresh_worker():
    if not BUILD_LOCK.acquire(blocking=False): return
    try: refresh_cache()
    finally: BUILD_LOCK.release()

def qcache(sql,args=()):
    if not cache_ready(): return []
    c=cache_conn(); rows=c.execute(sql,args).fetchall(); c.close(); return [dict(r) for r in rows]

def movies():
    out=qcache('select * from movies'); prot=protected_set('movie'); rev=review_ids('movie'); matches=arr_matches('movie'); activity=tautulli_activity('movie'); base=setting('radarr_url','http://localhost:7878').rstrip('/')
    for r in out:
        r['protected']=r['title'] in prot; r['review']=r['metadata_id'] in rev; r['tautulli']=activity.get(r['metadata_id']); r['arr']=matches.get(r['metadata_id']); r['arr_url']=(base+'/movie/'+r['arr']['title_slug']) if r['arr'] and r['arr'].get('title_slug') else None
    return out

def shows():
    out=qcache('select * from shows'); prot=protected_set('tv')|{'Star Trek: The Next Generation'}; rev=review_ids('tv'); matches=arr_matches('tv'); activity=tautulli_activity('tv'); base=setting('sonarr_url','http://localhost:7879').rstrip('/')
    for r in out:
        r['protected']=r['title'] in prot; r['review']=r['show_id'] in rev; r['tautulli']=activity.get(r['show_id']); r['arr']=matches.get(r['show_id']); r['arr_url']=(base+'/series/'+r['arr']['title_slug']) if r['arr'] and r['arr'].get('title_slug') else None
    return out

def sort_rows(data,allowed,default):
    key=request.args.get('sort',default); direction=request.args.get('dir','desc'); key=key if key in allowed else default
    return sorted(data,key=lambda x:(x.get(key) is not None,x.get(key) or 0),reverse=direction!='asc'),key,direction

def tautulli_now_playing():
    """Privacy-filtered current sessions for the public dashboard."""
    try:
        data=tautulli_request('get_activity') or {}
        sessions=[]
        for s in data.get('sessions') or []:
            mt=(s.get('media_type') or '').lower()
            title=s.get('full_title') or s.get('title') or 'Unknown title'
            if mt=='episode': title=s.get('grandparent_title') or title
            item_id=s.get('rating_key') or s.get('ratingKey')
            poster_id=(s.get('grandparent_rating_key') or s.get('grandparentRatingKey')) if mt=='episode' else item_id
            try: item_id=int(item_id) if item_id else None
            except (TypeError,ValueError): item_id=None
            try: poster_id=int(poster_id) if poster_id else item_id
            except (TypeError,ValueError): poster_id=item_id
            season=s.get('parent_media_index') or s.get('parentMediaIndex')
            episode_no=s.get('media_index') or s.get('mediaIndex')
            episode_title=s.get('title') or ''
            episode_label=''
            if mt=='episode':
                if season is not None and episode_no is not None:
                    try: episode_label=f'S{int(season):02d}E{int(episode_no):02d}'
                    except (TypeError,ValueError): pass
                if episode_title:
                    episode_label=(episode_label+' · ' if episode_label else '')+episode_title
            sessions.append({'title':title,'episode':episode_label or (s.get('full_title') if mt=='episode' else ''), 'progress':round(float(s.get('progress_percent') or 0)), 'player':s.get('product') or s.get('platform') or 'Plex player', 'quality':s.get('quality_profile') or s.get('video_resolution') or '', 'decision':s.get('transcode_decision') or s.get('video_decision') or '', 'media_type':mt, 'item_id':item_id, 'poster_id':poster_id, 'plex_url':_plex_web_link(item_id) if item_id else None})
        return sessions
    except Exception:
        return []

@app.get('/api/now-playing')
def now_playing_api():
    return {'sessions':tautulli_now_playing(),'updated':datetime.now().strftime('%H:%M:%S')}

_SMART_SYNONYMS={
 'wilderness':['survival','stranded','lost','forest','mountain','desert','remote','alone'],
 'stuck':['stranded','trapped','lost','survival'], 'home':['return','journey','escape','rescue'],
 'funny':['comedy','comic','humor','hilarious'], 'scary':['horror','terror','frightening'],
 'space':['sci-fi','science fiction','alien','spaceship','planet'], 'romantic':['romance','love'],
 'war':['military','soldier','battle'], 'crime':['criminal','detective','murder','police']}

def _smart_terms(q):
    terms=re.findall(r"[a-z0-9']+",q.lower()); out=list(terms)
    for t in terms: out.extend(_SMART_SYNONYMS.get(t,[]))
    return list(dict.fromkeys(x for x in out if len(x)>2))

_KNOWN_GENRES={x.lower():x for x in [
    'Action','Adventure','Animation','Anime','Biography','Comedy','Crime','Documentary','Drama','Family','Fantasy',
    'Film-Noir','History','Horror','Music','Musical','Mystery','Romance','Sci-Fi','Science Fiction','Sport','Thriller',
    'War','Western','Kids','Reality','Short'
]}

def _clean_genres(value):
    """Keep only recognisable genre tags. Older v2.9.4 caches may contain every Plex tag."""
    found=[]
    for raw in (value or '').split(','):
        key=raw.strip().lower()
        if key in _KNOWN_GENRES and _KNOWN_GENRES[key] not in found:
            found.append(_KNOWN_GENRES[key])
    return found

def _smart_constraints(q):
    """Extract constraints that should not be treated as ordinary fuzzy keywords."""
    text=(q or '').lower()
    out={'year_min':None,'year_max':None,'watched':None,'genres':[],'runtime_min':None,'runtime_max':None}
    # Decades: "90s", "1990s", "from/in the 90s".
    m=re.search(r'(?<!\d)(?:(19|20)?(\d0))s\b',text)
    if m:
        prefix=m.group(1); decade=int(m.group(2))
        if prefix: year=int(prefix)*100+decade
        else: year=(1900+decade) if decade>=30 else (2000+decade)
        out['year_min'],out['year_max']=year,year+9
    else:
        m=re.search(r'\b(19\d{2}|20\d{2})\b',text)
        if m: out['year_min']=out['year_max']=int(m.group(1))
    if re.search(r'\b(unwatched|not watched|haven[\'’]?t watched|never watched)\b',text): out['watched']=False
    elif re.search(r'\b(watched|seen)\b',text): out['watched']=True
    genre_patterns={
        'Comedy':r'\b(comedy|comedies|funny|hilarious|comic)\b',
        'Sci-Fi':r'\b(sci[ -]?fi|science fiction)\b',
        'Horror':r'\b(horror|scary|frightening)\b',
        'Romance':r'\b(romance|romantic)\b',
        'Action':r'\baction\b', 'Adventure':r'\badventure\b', 'Crime':r'\bcrime\b',
        'Documentary':r'\bdocumentar(?:y|ies)\b', 'Drama':r'\bdrama\b', 'Fantasy':r'\bfantasy\b',
        'Mystery':r'\bmystery\b', 'Thriller':r'\bthriller\b', 'War':r'\bwar\b', 'Western':r'\bwestern\b'
    }
    for genre,pat in genre_patterns.items():
        if re.search(pat,text): out['genres'].append(genre)

    # Runtime constraints. Plex stores movie duration in milliseconds.
    # Examples: "under 90 minutes", "less than 2 hours", "over 2 hours",
    # "at least 100 minutes", "around 90 minutes", "about 2 hours".
    runtime_patterns=[
        (r'\b(?:under|less than|shorter than|no more than|up to)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|minutes?|mins?|min|m)\b','max'),
        (r'\b(?:over|more than|longer than|at least)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|minutes?|mins?|min|m)\b','min'),
        (r'\b(?:around|about|roughly|approximately)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|minutes?|mins?|min|m)\b','around'),
    ]
    for pat,mode in runtime_patterns:
        m=re.search(pat,text)
        if not m: continue
        value=float(m.group(1)); unit=m.group(2)
        mins=round(value*60) if unit.startswith(('h','hr','hour')) else round(value)
        if mode=='max': out['runtime_max']=mins
        elif mode=='min': out['runtime_min']=mins
        else:
            out['runtime_min']=max(1,mins-15); out['runtime_max']=mins+15
        break
    if re.search(r'\bshort\s+(?:movie|film)\b',text) and out['runtime_max'] is None:
        out['runtime_max']=100
    return out

def _smart_search_interpretation(q):
    c=_smart_constraints(q); parts=[]
    if re.search(r'\b(movie|movies|film|films)\b',(q or '').lower()): parts.append('Movie')
    if c['watched'] is False: parts.append('Unwatched')
    elif c['watched'] is True: parts.append('Watched')
    if c['year_min'] is not None:
        parts.append(str(c['year_min']) if c['year_min']==c['year_max'] else f"{c['year_min']}–{c['year_max']}")
    parts.extend('Science Fiction' if g=='Sci-Fi' else g for g in c['genres'])
    if c['runtime_max'] is not None and c['runtime_min'] is None: parts.append(f"Under {c['runtime_max']} minutes")
    elif c['runtime_min'] is not None and c['runtime_max'] is None: parts.append(f"Over {c['runtime_min']} minutes")
    elif c['runtime_min'] is not None and c['runtime_max'] is not None:
        midpoint=round((c['runtime_min']+c['runtime_max'])/2)
        parts.append(f"Around {midpoint} minutes")
    return parts

def _lexical_smart_search(q,limit=20,strict=True):
    terms=_smart_terms(q); constraints=_smart_constraints(q); c=cache_conn()
    try: rows=[dict(r) for r in c.execute('select metadata_id,title,year,summary,genres,duration,watched,size_gb from movies group by metadata_id order by size_gb desc')]
    except sqlite3.OperationalError: rows=[dict(r,summary='',genres='') for r in c.execute('select metadata_id,title,year,duration,watched,size_gb from movies group by metadata_id order by size_gb desc')]
    c.close(); scored=[]
    structural={'movie','movies','film','films','from','the','with','about','that','this','want','something','watch','please',
                'under','over','less','more','than','shorter','longer','least','most','up','to','around','roughly','approximately',
                'hour','hours','hr','hrs','minute','minutes','min','mins'}
    constraint_words={'funny','comedy','comedies','hilarious','comic','sci','sci-fi','science','fiction','horror','scary','romance','romantic','action','adventure','crime','documentary','drama','fantasy','mystery','thriller','war','western','watched','unwatched','seen','short'}
    lexical_terms=[t for t in terms if t not in structural and t not in constraint_words and not re.fullmatch(r'(?:19|20)?\d0s?',t) and not t.isdigit()]
    for r in rows:
        year=int(r.get('year') or 0)
        duration_min=round((r.get('duration') or 0)/60000) if r.get('duration') else 0
        clean_genres=_clean_genres(r.get('genres')); genres_lower={g.lower() for g in clean_genres}
        summary=(r.get('summary') or '').strip(); title=(r.get('title') or '').lower()

        misses=[]; score=0.0; lexical_hits=set(); genre_hits=0
        if constraints['year_min'] is not None and not (constraints['year_min'] <= year <= constraints['year_max']): misses.append('year')
        if constraints['watched'] is not None and bool(r.get('watched')) != constraints['watched']: misses.append('watched')
        if constraints['runtime_min'] is not None and (not duration_min or duration_min < constraints['runtime_min']): misses.append('runtime')
        if constraints['runtime_max'] is not None and (not duration_min or duration_min > constraints['runtime_max']): misses.append('runtime')

        for wanted in constraints['genres']:
            aliases={wanted.lower()}
            if wanted=='Sci-Fi': aliases|={'science fiction'}
            if genres_lower & aliases:
                score+=5.0; genre_hits+=1
            elif wanted.lower() in summary.lower():
                score+=1.5
            else:
                misses.append('genre')

        # Exact results obey every structured constraint.
        if strict and misses: continue
        if not strict:
            # Closest-match candidates must still honour the core genre intent.
            # We collect candidates here and choose the least-important relaxed
            # constraint after scoring: runtime -> watched -> year.
            unique_misses=set(misses)
            if 'genre' in unique_misses or len(unique_misses)>1: continue
            score-=3.0*len(unique_misses)

        for t in lexical_terms:
            if t in title: score+=4; lexical_hits.add(t)
            elif t in ' '.join(clean_genres).lower(): score+=2.5; lexical_hits.add(t)
            elif t in summary.lower(): score+=1; lexical_hits.add(t)

        if score or constraints['year_min'] is not None or constraints['watched'] is not None or constraints['runtime_min'] is not None or constraints['runtime_max'] is not None:
            score += len(lexical_hits)*.25
            r['genre_list']=clean_genres; r['genres_display']=' · '.join(clean_genres); r['plex_url']=_plex_web_link(r['metadata_id'])
            r['runtime_minutes']=duration_min
            requested_genres=len(constraints['genres'])
            if requested_genres and genre_hits==requested_genres: score+=2.0
            r['constraint_misses']=sorted(set(misses))
            scored.append((score,r,genre_hits,requested_genres))

    scored.sort(key=lambda x:x[0],reverse=True)
    if not strict:
        # Do not mix different kinds of compromise on the same results page.
        # Prefer relaxing runtime, then watched status, then year/decade.
        relaxation_order=('runtime','watched','year')
        chosen=None
        for relax in relaxation_order:
            if any(set(item[1].get('constraint_misses') or [])=={relax} for item in scored):
                chosen=relax
                break
        if chosen:
            scored=[item for item in scored if set(item[1].get('constraint_misses') or [])=={chosen}]
        else:
            scored=[]
    results=[]
    for s,r,genre_hits,requested_genres in scored[:limit]:
        if not r.get('constraint_misses') and requested_genres and genre_hits==requested_genres and s>=8: label='Strong match'
        elif not r.get('constraint_misses') and ((requested_genres and genre_hits) or s>=4): label='Good match'
        elif r.get('constraint_misses'): label='Closest match'
        else: label='Possible match'
        r['match_score']=round(s,2); r['match_label']=label; results.append(r)
    return results

def _closest_relaxation(results):
    if not results: return None
    misses=results[0].get('constraint_misses') or []
    if not misses: return None
    labels={'runtime':'runtime requirement','watched':'watched/unwatched requirement','year':'year requirement'}
    return labels.get(misses[0],misses[0]+' requirement')

def _smart_search_owner_key():
    profile=plex_user()
    if not profile: return 'shared'
    # Prefer Plex's stable identifiers; never key personal history by display name alone.
    for key in ('uuid','id'):
        value=str(profile.get(key) or '').strip()
        if value: return 'plex:'+value
    return 'shared'

def _smart_search_history(limit=10,owner_key=None):
    owner_key=owner_key or _smart_search_owner_key(); c=config()
    rows=c.execute('select query,searched_at from smart_search_history where owner_key=? order by searched_at desc limit ?',(owner_key,int(limit))).fetchall(); c.close()
    return [dict(r) for r in rows]

def _remember_smart_search(q,owner_key=None):
    q=' '.join((q or '').split())[:500]
    if not q: return
    owner_key=owner_key or _smart_search_owner_key(); now=int(time.time()); c=config()
    c.execute('insert into smart_search_history(query,owner_key,searched_at) values(?,?,?) on conflict(owner_key,query) do update set searched_at=excluded.searched_at',(q,owner_key,now))
    # Keep up to 100 searches per Plex user (or 100 shared searches when signed out).
    c.execute('delete from smart_search_history where owner_key=? and id not in (select id from smart_search_history where owner_key=? order by searched_at desc limit 100)',(owner_key,owner_key))
    c.commit(); c.close()

@app.get('/smart-search')
def smart_search():
    q=(request.args.get('q') or '').strip()[:500]; owner_key=_smart_search_owner_key()
    show_closest=(request.args.get('closest') or '')=='1'
    if q: _remember_smart_search(q,owner_key)
    results=_lexical_smart_search(q,strict=not show_closest) if q and cache_ready() else []
    interpretation=_smart_search_interpretation(q) if q else []
    closest_relaxation=_closest_relaxation(results) if show_closest else None
    return render_template('smart_search.html',q=q,results=results,search_history=_smart_search_history(owner_key=owner_key),
                           interpretation=interpretation,show_closest=show_closest,closest_relaxation=closest_relaxation)

@app.post('/smart-search/history/clear')
def smart_search_history_clear():
    owner_key=_smart_search_owner_key(); c=config(); c.execute('delete from smart_search_history where owner_key=?',(owner_key,)); c.commit(); c.close()
    flash('Smart Search history cleared.','success')
    return redirect(url_for('smart_search'))

@app.get('/smart-search/poster/<int:item_id>')
def smart_search_poster(item_id):
    poster=_plex_poster(item_id)
    if not poster: abort(404)
    resp=Response(poster[0],mimetype=poster[1].split(';',1)[0])
    resp.headers['Cache-Control']='private, max-age=86400'
    return resp

def _dashboard_library_summary():
    """Cheap aggregate queries for the dashboard; avoid hydrating every movie/show."""
    c=cache_conn()
    try:
        m=c.execute('select count(*) n,coalesce(sum(size_gb),0) gb from movies').fetchone()
        t=c.execute('select count(*) n,coalesce(sum(size_gb),0) gb from shows').fetchone()
        old=c.execute('select count(*) n,coalesce(sum(size_gb),0) gb from shows where watched_episodes=0 and age>=3 and title<>?',('Star Trek: The Next Generation',)).fetchone()
        large=c.execute("select count(*) n,coalesce(sum(size_gb),0) gb from movies where resolution='720p' and codec='h264' and size_gb>=4").fetchone()
        ineff=c.execute('select count(*) n,coalesce(sum(size_gb),0) gb from shows where gbph>=1.5 and title<>?',('Star Trek: The Next Generation',)).fetchone()
        total_gb=float(m['gb'] or 0)+float(t['gb'] or 0)
        return {'movie_count':m['n'],'movie_tb':round(m['gb']/1024,2),'tv_count':t['n'],'tv_tb':round(t['gb']/1024,2),
                'library_tb':round(total_gb/1024,2),'old_count':old['n'],'old_tb':round(old['gb']/1024,2),'large_count':large['n'],'large_tb':round(large['gb']/1024,2),
                'ineff_count':ineff['n'],'ineff_tb':round(ineff['gb']/1024,2)}
    finally: c.close()

def _dashboard_recently_added(limit=6):
    """Newest cached Plex movies/shows, using the same cache that powers Movies and TV."""
    c=cache_conn()
    try:
        rows=c.execute("""
            select 'movie' kind,metadata_id item_id,title,year,added_at from movies
            union all
            select 'tv' kind,show_id item_id,title,year,added_at from shows
            order by added_at desc limit ?
        """,(limit,)).fetchall()
        return [dict(r) for r in rows]
    finally: c.close()

def _dashboard_recently_watched(limit=6):
    """Latest unique titles from the existing Tautulli history cache."""
    c=config()
    try:
        rows=c.execute("""
            select kind,item_id,max(watched_at) watched_at,count(*) plays
            from tautulli_history where item_id is not null
            group by kind,item_id order by watched_at desc limit ?
        """,(limit,)).fetchall()
    finally: c.close()
    if not rows: return []
    cc=cache_conn(); out=[]
    try:
        for r in rows:
            table,idcol=('movies','metadata_id') if r['kind']=='movie' else ('shows','show_id')
            item=cc.execute(f'select title,year from {table} where {idcol}=?',(r['item_id'],)).fetchone()
            if item: out.append({'kind':r['kind'],'item_id':r['item_id'],'title':item['title'],'year':item['year'],'watched_at':r['watched_at'],'plays':r['plays']})
        return out
    finally: cc.close()

def _dashboard_user_count():
    c=config()
    try:
        return c.execute("select count(distinct user) n from tautulli_history where trim(coalesce(user,''))<>''").fetchone()['n']
    finally: c.close()

@app.route('/')
def dashboard():
    if not has_plex_access():
        return render_template('landing.html')
    started=time.perf_counter()
    if not cache_ready(): return render_template('no_cache.html',db=get_db_path())
    summary=_dashboard_library_summary()
    try: days=int(request.args.get('activity_days','30'))
    except ValueError: days=30
    days=days if days in (0,7,30,90,365) else 30
    stats_started=time.perf_counter()
    stats=tautulli_dashboard_stats(days) if setting('tautulli_authoritative','0')=='1' else None
    stats_ms=(time.perf_counter()-stats_started)*1000
    response=render_template('dashboard.html',summary=summary,user_count=_dashboard_user_count(),recently_added=_dashboard_recently_added(),recently_watched=_dashboard_recently_watched(),review_count=len(review_ids('movie'))+len(review_ids('tv')),cache=cache_meta(),stats=stats,tautulli_last_sync=setting('tautulli_last_sync','Never'))
    total_ms=(time.perf_counter()-started)*1000
    if total_ms>=250: print(f'[dashboard] rendered in {total_ms:.0f} ms (Tautulli stats {stats_ms:.0f} ms)')
    return response

@app.route('/cleanup')
def cleanup():
    if not cache_ready(): return render_template('no_cache.html',db=get_db_path())
    ms=movies(); tv=shows()
    old_tv=[x for x in tv if not x['protected'] and x['watched_episodes']==0 and x['age']>=3]
    inefficient=[x for x in tv if not x['protected'] and x['gbph']>=1.5]
    large720=[x for x in ms if x['resolution']=='720p' and x['codec']=='h264' and x['size_gb']>=4]
    old_movies=[x for x in ms if not x['protected'] and not x['watched'] and x['age']>=3]
    return render_template('cleanup.html',old_tv=old_tv,ineff=inefficient,large720=large720,old_movies=old_movies,
                           summary=_dashboard_library_summary(),user_count=_dashboard_user_count(),
                           review_count=len(review_ids('movie'))+len(review_ids('tv')),cache=cache_meta())

def _page_args():
    try: page=max(1,int(request.args.get('page','1')))
    except ValueError: page=1
    try: per_page=int(request.args.get('per_page','100'))
    except ValueError: per_page=100
    per_page=per_page if per_page in (50,100,200) else 100
    return page,per_page

def _mark_alternate_matches(rows, table, idcol, kind):
    # An unmatched Plex item may be an alternate/special edition of a title that
    # *is* managed by Arr.  We only label it Alternate / duplicate when another
    # Plex row with the exact same title + year has an exact-path Arr match.
    pending=[r for r in rows if not r.get('arr')]
    if not pending: return rows
    c=cache_conn(); c.execute('attach database ? as cfg',(os.path.abspath(CONFIG_DB),))
    sql=f'''select 1 from {table} sibling
            join cfg.arr_matches am on am.kind=? and am.item_id=sibling.{idcol}
            where sibling.{idcol}<>?
              and lower(sibling.title)=lower(?)
              and coalesce(sibling.year,0)=coalesce(?,0)
            limit 1'''
    for r in pending:
        r['arr_status']='alternate' if c.execute(sql,(kind,r[idcol],r['title'],r.get('year'))).fetchone() else 'unmatched'
    c.close(); return rows

def _enrich_movies(rows):
    prot=protected_set('movie'); rev=review_ids('movie'); matches=arr_matches('movie'); activity=tautulli_activity('movie'); base=setting('radarr_url','http://localhost:7878').rstrip('/')
    for r in rows:
        r['protected']=r['title'] in prot; r['review']=r['metadata_id'] in rev; r['tautulli']=activity.get(r['metadata_id']); r['arr']=matches.get(r['metadata_id']); r['arr_url']=(base+'/movie/'+r['arr']['title_slug']) if r['arr'] and r['arr'].get('title_slug') else None; r['arr_status']='matched' if r['arr'] else 'unmatched'
    return _mark_alternate_matches(rows,'movies','metadata_id','movie')

def _enrich_shows(rows):
    prot=protected_set('tv')|{'Star Trek: The Next Generation'}; rev=review_ids('tv'); matches=arr_matches('tv'); activity=tautulli_activity('tv'); base=setting('sonarr_url','http://localhost:7879').rstrip('/')
    for r in rows:
        r['protected']=r['title'] in prot; r['review']=r['show_id'] in rev; r['tautulli']=activity.get(r['show_id']); r['arr']=matches.get(r['show_id']); r['arr_url']=(base+'/series/'+r['arr']['title_slug']) if r['arr'] and r['arr'].get('title_slug') else None; r['arr_status']='matched' if r['arr'] else 'unmatched'
    return _mark_alternate_matches(rows,'shows','show_id','tv')

def _paged_cache(table, idcol, allowed_sort, default_sort, filt, term, kind):
    page,per_page=_page_args(); sort=request.args.get('sort',default_sort); direction=request.args.get('dir','desc').lower()
    sort=sort if sort in allowed_sort else default_sort; direction='asc' if direction=='asc' else 'desc'
    where=[]; args=[]
    if term:
        where.append('title like ?'); args.append('%'+term+'%')
    if table=='movies':
        if filt=='old_unwatched': where += ['watched=0','age>=3']
        elif filt=='large720': where += ["resolution='720p'","codec='h264'",'size_gb>=4']
        elif filt=='8gb720': where += ["resolution='720p'","codec='h264'",'size_gb>=8']
    else:
        if filt=='old_unwatched': where += ['watched_episodes=0','age>=3']
        elif filt=='inefficient': where += ['gbph>=1.5']
        elif filt=='large_unwatched': where += ['watched_episodes=0','size_gb>=20']
    # Review queue is tiny; constrain it in SQLite rather than loading the whole cache.
    if filt=='review':
        ids=sorted(review_ids(kind))
        if not ids: where.append('1=0')
        else:
            where.append(idcol+' in ('+','.join('?' for _ in ids)+')'); args.extend(ids)
    # Arr match filters use the local auditor DB directly, so even a 7,000+ movie
    # library stays server-side and does not hit SQLite's parameter limit.
    matched_sql=f"exists (select 1 from cfg.arr_matches am where am.kind=? and am.item_id={table}.{idcol})"
    sibling_sql=f"exists (select 1 from {table} sibling join cfg.arr_matches am2 on am2.kind=? and am2.item_id=sibling.{idcol} where sibling.{idcol}<>{table}.{idcol} and lower(sibling.title)=lower({table}.title) and coalesce(sibling.year,0)=coalesce({table}.year,0))"
    if filt=='matched':
        where.append(matched_sql); args.append(kind)
    elif filt=='unmatched':
        where.append('not '+matched_sql); args.append(kind)
    elif filt=='alternate':
        where += ['not '+matched_sql, sibling_sql]; args += [kind,kind]
    elif filt=='not_in_arr':
        where += ['not '+matched_sql, 'not '+sibling_sql]; args += [kind,kind]
    # Tautulli activity filters are based on all Plex users, not the single-account Plex watched flag.
    if filt=='tautulli_never':
        where.append(f'not exists (select 1 from cfg.tautulli_activity ta where ta.kind=? and ta.item_id={table}.{idcol} and ta.plays>0)'); args.append(kind)
    elif filt in ('tautulli_1y','tautulli_2y'):
        cutoff=int(time.time()-(365 if filt=='tautulli_1y' else 730)*86400)
        where.append(f'not exists (select 1 from cfg.tautulli_activity ta where ta.kind=? and ta.item_id={table}.{idcol} and ta.plays>0 and ta.last_watched>=?)'); args += [kind,cutoff]
    # Popularity filters use the detailed play-history cache. They keep the existing list UI
    # but rank the selected period by aggregate play count.
    popularity_days={'popular_7':7,'popular_30':30,'popular_90':90,'popular_365':365,'popular_all':0}
    popularity_expr=None
    if filt in popularity_days:
        days=popularity_days[filt]; cutoff=0 if days==0 else int(time.time()-days*86400)
        popularity_expr=f'(select count(*) from cfg.tautulli_history th where th.kind=\'{kind}\' and th.item_id={table}.{idcol} and th.watched_at>={cutoff})'
        where.append(popularity_expr+' > 0')
        sort='plays'; direction='desc'
    # Protected exclusions for cleanup filters. TNG is always protected.
    if filt in ('old_unwatched','large720','8gb720','inefficient','large_unwatched'):
        titles=sorted(protected_set(kind) | ({'Star Trek: The Next Generation'} if kind=='tv' else set()))
        if titles:
            where.append('title not in ('+','.join('?' for _ in titles)+')'); args.extend(titles)
    clause=(' where '+' and '.join(where)) if where else ''
    c=cache_conn()
    # Attach the small local settings DB for Matched/Unmatched filters.
    # Use the native Windows filename here. ATTACH does not reliably interpret
    # a parameterised file: URI on Windows, which caused /movies and /tv to 500.
    # These page queries are SELECT-only; application writes still use config_conn().
    c.execute("attach database ? as cfg", (os.path.abspath(CONFIG_DB),))
    summary=c.execute(f'select count(*) n,coalesce(sum(size_gb),0) gb from {table}'+clause,args).fetchone()
    pages=max(1,(summary['n']+per_page-1)//per_page); page=min(page,pages); offset=(page-1)*per_page
    sort_expr = (popularity_expr if sort=='plays' and popularity_expr else (f"(select coalesce(ta.plays,0) from cfg.tautulli_activity ta where ta.kind='{kind}' and ta.item_id={table}.{idcol})" if sort=='plays' else ('title COLLATE "NATURAL"' if sort=='title' else sort)))
    plays_select = f", {sort_expr} as played_count" if sort=='plays' else ''
    rows=[dict(r) for r in c.execute(f'select {table}.*'+plays_select+f' from {table}'+clause+f' order by {sort_expr} {direction}, title COLLATE "NATURAL" asc limit ? offset ?',args+[per_page,offset]).fetchall()]
    c.close()
    return rows,dict(summary),page,pages,per_page,sort,direction

@app.route('/movies')
def movie_page():
    if not cache_ready(): return render_template('no_cache.html',db=get_db_path())
    filt=request.args.get('filter','all'); term=request.args.get('q','').strip()
    rows,summary,page,pages,per_page,key,direction=_paged_cache('movies','metadata_id',{'title','year','size_gb','age','resolution','codec','plays'},'size_gb',filt,term,'movie')
    _enrich_movies(rows)
    return render_template('movies.html',rows=rows,total=summary['n'],total_tb=round(summary['gb']/1024,2),page=page,pages=pages,per_page=per_page,filt=filt,qterm=term,sort=key,dir=direction)

@app.route('/tv')
def tv_page():
    if not cache_ready(): return render_template('no_cache.html',db=get_db_path())
    filt=request.args.get('filter','all'); term=request.args.get('q','').strip()
    rows,summary,page,pages,per_page,key,direction=_paged_cache('shows','show_id',{'title','year','episodes','pct','age','size_gb','gbph','sd','p720','p1080','plays'},'size_gb',filt,term,'tv')
    _enrich_shows(rows)
    return render_template('tv.html',rows=rows,total=summary['n'],total_tb=round(summary['gb']/1024,2),page=page,pages=pages,per_page=per_page,filt=filt,qterm=term,sort=key,dir=direction)

@app.route('/movie/<int:item_id>')
def movie_detail(item_id):
    rows=qcache('select * from movies where metadata_id=? order by size_gb desc',(item_id,))
    if not rows: abort(404)
    _enrich_movies(rows)
    m=rows[0]
    m['plex_url']=_plex_web_link(item_id)
    m['genre_list']=_clean_genres(m.get('genres'))
    m['runtime_minutes']=round((m.get('duration') or 0)/60000) if (m.get('duration') or 0) > 10000 else round((m.get('duration') or 0)/60)
    return render_template('movie_detail.html',m=m,versions=rows,total_gb=round(sum(x['size_gb'] for x in rows),2))

@app.route('/show/<int:item_id>')
def show_detail(item_id):
    rows=qcache('select * from shows where show_id=?',(item_id,))
    if not rows: abort(404)
    _enrich_shows(rows); s=rows[0]
    s['plex_url']=_plex_web_link(item_id)
    eps=qcache('select * from episodes where show_id=? order by season,episode',(item_id,))
    seasons=len({e['season'] for e in eps if e.get('season') is not None})
    watched=sum(1 for e in eps if e.get('watched'))
    return render_template('show_detail.html',s=s,episodes=eps,seasons=seasons,watched=watched)

@app.post('/protect')
def protect():
    kind=request.form['kind']; title=request.form['title']; action=request.form.get('action','protect'); c=config()
    if action=='unprotect': c.execute('delete from protected where kind=? and title=?',(kind,title))
    else: c.execute('insert or replace into protected(kind,title,note) values(?,?,?)',(kind,title,request.form.get('note','')))
    c.commit(); c.close(); return redirect(request.referrer or url_for('dashboard'))

@app.post('/review')
def review():
    kind=request.form['kind']; item_id=int(request.form['item_id']); title=request.form['title']; action=request.form.get('action','add'); c=config()
    if action=='remove': c.execute('delete from review where kind=? and item_id=?',(kind,item_id))
    else: c.execute('insert or replace into review(kind,item_id,title,action,note) values(?,?,?,?,?)',(kind,item_id,title,'review',request.form.get('note','')))
    c.commit(); c.close(); return redirect(request.referrer or url_for('review_page'))

@app.route('/review')
def review_page():
    c=config(); rows=[dict(r) for r in c.execute('select * from review order by added_at desc')]; c.close(); ms={x['metadata_id']:x for x in movies()}; ts={x['show_id']:x for x in shows()}
    for r in rows: r['data']=ms.get(r['item_id']) if r['kind']=='movie' else ts.get(r['item_id'])
    return render_template('review.html',rows=rows)

@app.route('/export/<kind>')
def export(kind):
    data=movies() if kind=='movies' else shows(); output=io.StringIO()
    if not data:return Response('',mimetype='text/csv')
    w=csv.DictWriter(output,fieldnames=data[0].keys()); w.writeheader(); w.writerows(data)
    return Response(output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename={kind}.csv'})

@app.post('/refresh-cache')
def refresh_cache_route():
    if BUILD_STATUS.get('running'):
        return redirect(url_for('settings'))
    threading.Thread(target=refresh_worker,daemon=True).start()
    return redirect(url_for('settings',building='1'))

@app.get('/api/cache-status')
def cache_status_route():
    if BUILD_STATUS.get('started_at') and BUILD_STATUS.get('running'):
        BUILD_STATUS['elapsed']=round(time.time()-BUILD_STATUS['started_at'],1)
    return dict(BUILD_STATUS)

@app.get('/api/database-options')
def database_options():
    current=get_db_path()
    folder=os.path.dirname(current)
    try:
        names=[]
        for name in os.listdir(folder):
            full=os.path.join(folder,name)
            if not os.path.isfile(full):
                continue
            low=name.lower()
            if 'com.plexapp.plugins.library.db' not in low:
                continue
            try:
                st=os.stat(full)
                names.append({'name':name,'path':full,'size_mb':round(st.st_size/1024/1024,1),'modified':datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),'current':os.path.normcase(full)==os.path.normcase(current)})
            except OSError:
                pass
        names.sort(key=lambda x:x['modified'],reverse=True)
        return {'folder':folder,'databases':names}
    except Exception as e:
        return {'folder':folder,'databases':[],'error':str(e)},500

@app.post('/plex/use-live-db')
def plex_use_live_db():
    local=os.environ.get('LOCALAPPDATA','')
    path=os.path.join(local,'Plex Media Server','Plug-in Support','Databases','com.plexapp.plugins.library.db') if local else ''
    if not path or not os.path.exists(path):
        flash('Could not auto-detect the live Plex database for this Windows account. You can still select its path manually.','danger')
    else:
        try:
            c=source_conn(path); c.execute('select count(*) from library_sections').fetchone(); c.close(); set_setting('plex_db',path); flash('Live Plex database selected. Click Update Plex Now to build a safe snapshot and refresh the Auditor cache.','success')
        except Exception as e: flash('Found the live Plex database but could not open it: '+str(e),'danger')
    return redirect(url_for('settings'))

@app.post('/plex/schedule')
def plex_schedule():
    set_setting('plex_auto_enabled','1' if request.form.get('enabled')=='1' else '0')
    freq=request.form.get('frequency','daily'); set_setting('plex_auto_frequency',freq if freq in ('daily','6h','12h') else 'daily')
    t=request.form.get('time','03:00'); set_setting('plex_auto_time',t if len(t)==5 and t[2]==':' else '03:00')
    flash('Plex update schedule saved.','success'); return redirect(url_for('settings'))

@app.post('/plex/connection')
def plex_connection_save():
    set_setting('plex_url',(request.form.get('plex_url') or 'http://localhost:32400').strip().rstrip('/'))
    token=(request.form.get('plex_token') or '').strip()
    if token: set_setting('plex_token',token)
    try:
        base=setting('plex_url','http://localhost:32400'); tok=_plex_token()
        r=requests.get(base+'/identity',headers={'X-Plex-Token':tok,'Accept':'application/json'},timeout=15)
        if r.ok:
            try: machine=r.json().get('MediaContainer',{}).get('machineIdentifier')
            except Exception:
                m=re.search(r'machineIdentifier=["\']([^"\']+)',r.text); machine=m.group(1) if m else None
            if machine: set_setting('plex_machine_id',machine)
            flash('Plex connection saved and server identity detected.','success')
        else: flash('Plex settings saved, but the server identity test failed.','warning')
    except Exception as e: flash('Plex settings saved; connection test failed: '+str(e),'warning')
    return redirect(url_for('settings'))

@app.post('/integrations/save')
def integrations_save():
    for kind,default in [('radarr','http://localhost:7878'),('sonarr','http://localhost:7879')]:
        set_setting(kind+'_url',request.form.get(kind+'_url',default).strip().rstrip('/'))
        key=request.form.get(kind+'_api_key','').strip()
        if key: set_setting(kind+'_api_key',key)
    flash('Integration settings saved locally.','success'); return redirect(url_for('settings'))

@app.post('/integrations/test/<kind>')
def integrations_test(kind):
    if kind not in ('radarr','sonarr'): abort(404)
    try:
        st=arr_request(kind,'system/status'); flash(f"{kind.title()} connected: {st.get('appName',kind.title())} {st.get('version','')}",'success')
    except Exception as e: flash(f'{kind.title()} connection failed: {e}','danger')
    return redirect(url_for('settings'))

@app.post('/integrations/sync')
def integrations_sync():
    if not ARR_STATUS.get('running'):
        threading.Thread(target=arr_sync_worker,daemon=True).start()
    return redirect(url_for('settings'))

@app.get('/api/arr-sync-status')
def arr_sync_status():
    if ARR_STATUS.get('started_at') and ARR_STATUS.get('running'):
        ARR_STATUS['elapsed']=round(time.time()-ARR_STATUS['started_at'],1)
    return dict(ARR_STATUS)


@app.post('/tautulli/save')
def tautulli_save():
    set_setting('tautulli_url',request.form.get('tautulli_url','http://localhost:8181').strip().rstrip('/'))
    key=request.form.get('tautulli_api_key','').strip()
    if key: set_setting('tautulli_api_key',key)
    flash('Tautulli settings saved locally.','success'); return redirect(url_for('settings'))

@app.post('/tautulli/test')
def tautulli_test():
    try:
        users=tautulli_request('get_users') or []
        flash(f'Tautulli connected successfully · {len(users):,} Plex users found.','success')
    except Exception as e: flash(f'Tautulli connection failed: {e}','danger')
    return redirect(url_for('settings'))

@app.post('/tautulli/sync')
def tautulli_sync_route():
    if not TAUTULLI_STATUS.get('running'): threading.Thread(target=tautulli_worker,kwargs={'full':False},daemon=True).start()
    return redirect(url_for('settings'))

@app.post('/tautulli/full-rescan')
def tautulli_full_rescan_route():
    if not TAUTULLI_STATUS.get('running'): threading.Thread(target=tautulli_worker,kwargs={'full':True},daemon=True).start()
    return redirect(url_for('settings'))

@app.post('/tautulli/schedule')
def tautulli_schedule():
    set_setting('tautulli_auto_enabled','1' if request.form.get('enabled')=='1' else '0')
    freq=request.form.get('frequency','daily'); set_setting('tautulli_auto_frequency',freq if freq in ('daily','6h','12h','weekly') else 'daily')
    t=request.form.get('time','01:00'); set_setting('tautulli_auto_time',t if len(t)==5 and t[2]==':' else '01:00')
    day=request.form.get('day','mon'); set_setting('tautulli_auto_day',day if day in ('mon','tue','wed','thu','fri','sat','sun') else 'mon')
    flash('Tautulli update schedule saved.','success'); return redirect(url_for('settings'))

@app.get('/api/tautulli-sync-status')
def tautulli_sync_status():
    if TAUTULLI_STATUS.get('started_at') and TAUTULLI_STATUS.get('running'): TAUTULLI_STATUS['elapsed']=round(time.time()-TAUTULLI_STATUS['started_at'],1)
    return dict(TAUTULLI_STATUS)


@app.post('/discord/save')
def discord_save():
    webhook=request.form.get('webhook_url','').strip()
    if webhook: set_setting('discord_webhook_url',webhook)
    bot_token=request.form.get('bot_token','').strip()
    if bot_token: set_setting('discord_bot_token',bot_token)
    set_setting('discord_bot_enabled','1' if request.form.get('bot_enabled')=='1' else '0')
    set_setting('discord_bot_ephemeral','1' if request.form.get('bot_ephemeral')=='1' else '0')
    guild_id=re.sub(r'\D','',request.form.get('bot_guild_id','') or '')
    set_setting('discord_bot_guild_id',guild_id)
    movie_webhook=request.form.get('movie_webhook_url','').strip()
    tv_webhook=request.form.get('tv_webhook_url','').strip()
    if movie_webhook: set_setting('discord_movie_webhook_url',movie_webhook)
    if tv_webhook: set_setting('discord_tv_webhook_url',tv_webhook)
    set_setting('discord_auto_enabled','1' if request.form.get('enabled')=='1' else '0')
    freq=request.form.get('frequency','weekly'); set_setting('discord_frequency',freq if freq in ('daily','3xweek','weekly') else 'weekly')
    t=request.form.get('time','19:00'); set_setting('discord_post_time',t if len(t)==5 and t[2]==':' else '19:00')
    try: wd=max(0,min(int(request.form.get('weekday','4')),6))
    except ValueError: wd=4
    set_setting('discord_weekday',str(wd))
    try: cooldown=max(1,min(int(request.form.get('cooldown','90')),3650))
    except ValueError: cooldown=90
    set_setting('discord_cooldown_days',str(cooldown))
    try: days=int(request.form.get('stats_days','30'))
    except ValueError: days=30
    set_setting('discord_stats_days',str(days if days in (7,30,90,365) else 30))
    cats=[x for x in ('popular_movie','popular_tv','viewing_hours','storage_hog','forgotten','movie_recommendation','tv_recommendation') if request.form.get('cat_'+x)=='1']
    set_setting('discord_categories',','.join(cats))
    flash('Discord settings saved.','success'); return redirect(url_for('settings'))

@app.post('/discord/test')
def discord_test():
    try: discord_webhook_send(embed=_discord_embed('MyCouch','Discord connection is working.',[{'name':'Status','value':'Connected ✓','inline':True}],'MyCouch • Test message')); flash('Test message sent to Discord.','success')
    except Exception as e: flash('Discord test failed: '+str(e),'danger')
    return redirect(url_for('settings'))

@app.post('/discord/test-recommendation/<kind>')
def discord_test_recommendation(kind):
    if kind not in ('movie','tv'): abort(404)
    key='discord_movie_webhook_url' if kind=='movie' else 'discord_tv_webhook_url'
    target=setting(key,'').strip() or setting('discord_webhook_url','').strip()
    label='Movie Recommendations' if kind=='movie' else 'TV Recommendations'
    try:
        discord_webhook_send(embed=_discord_embed(label,'Recommendation webhook routing is working.',[{'name':'Status','value':'Connected ✓','inline':True}],'MyCouch • Test message'),webhook_url=target)
        flash(label+' test sent to Discord.','success')
    except Exception as e: flash(label+' test failed: '+str(e),'danger')
    return redirect(url_for('settings'))

@app.post('/discord/send-recommendation/<kind>')
def discord_send_recommendation(kind):
    if kind not in ('movie','tv'): abort(404)
    try:
        days=int(setting('discord_stats_days','30') or 30)
        pick=_recommendation_pick(kind,days,force=True)
        if not pick: raise RuntimeError('No eligible recommendation could be found')
        key='discord_movie_webhook_url' if kind=='movie' else 'discord_tv_webhook_url'
        target=setting(key,'').strip() or setting('discord_webhook_url','').strip()
        discord_webhook_send(embed=pick[2],webhook_url=target)
        _record_discord(pick[0],pick[1],json.dumps(pick[2]))
        flash(('Movie' if kind=='movie' else 'TV')+' recommendation sent.','success')
    except Exception as e: flash('Could not send recommendation: '+str(e),'danger')
    return redirect(url_for('settings'))

@app.post('/discord/send-stat')
def discord_send_stat():
    try:
        x=send_random_discord_stat(force=True); flash('Discord stat sent: '+x[0].replace('_',' ').title()+'.','success')
    except Exception as e: flash('Could not send Discord stat: '+str(e),'danger')
    return redirect(url_for('settings'))

@app.get('/leaving-soon')
def leaving_soon_page():
    c=config(); rows=[dict(r) for r in c.execute('select * from leaving_soon order by status,deadline,title')]; c.close()
    return render_template('leaving_soon.html',rows=rows)

@app.post('/leaving-soon/add')
def leaving_soon_add():
    kind=request.form.get('kind'); item_id=int(request.form.get('item_id','0')); title=request.form.get('title','').strip()
    if kind not in ('movie','tv') or not item_id or not title: abort(400)
    info=_title_for(kind,item_id) or {}; days=max(1,min(int(setting('leaving_soon_days','14') or 14),90)); deadline=int(time.time()+days*86400)
    c=config(); c.execute('insert or replace into leaving_soon(kind,item_id,title,size_gb,deadline,status,discord_posted) values(?,?,?,?,?,\"announced\",0)',(kind,item_id,title,info.get('size_gb'),deadline)); c.commit(); c.close()
    flash(f'{title} added to Leaving Soon.','success'); return redirect(url_for('leaving_soon_page'))

@app.post('/leaving-soon/post')
def leaving_soon_post():
    kind=request.form.get('kind'); item_id=int(request.form.get('item_id','0')); c=config(); r=c.execute('select * from leaving_soon where kind=? and item_id=?',(kind,item_id)).fetchone(); c.close()
    if not r: abort(404)
    days=max(0,int((r['deadline']-time.time())/86400)+1); size=f" · {r['size_gb']:,.1f} GB" if r['size_gb'] is not None else ''
    fields=[]
    if r['size_gb'] is not None: fields.append({'name':'Size','value':f'{r["size_gb"]:,.1f} GB','inline':True})
    fields.extend([{'name':'Review In','value':f'About {days} days','inline':True},{'name':'Feedback','value':'👍 Keep  •  🗑️ Fine to remove','inline':False}])
    embed=_discord_embed(f'Leaving Soon: {r["title"]}','This title is being reviewed for removal from the Plex library. Any Keep response should be treated as a reason to protect it.',fields,'MyCouch • No automatic deletion'); embed['_plex_item_id']=str(item_id)
    try:
        discord_webhook_send(embed=embed); c=config(); c.execute('update leaving_soon set discord_posted=1 where kind=? and item_id=?',(kind,item_id)); c.commit(); c.close(); flash('Leaving Soon announcement posted.','success')
    except Exception as e: flash('Discord post failed: '+str(e),'danger')
    return redirect(url_for('leaving_soon_page'))

@app.post('/leaving-soon/status')
def leaving_soon_status():
    kind=request.form.get('kind'); item_id=int(request.form.get('item_id','0')); status=request.form.get('status','announced')
    if status not in ('announced','keep','approved','removed'): abort(400)
    c=config(); c.execute('update leaving_soon set status=? where kind=? and item_id=?',(status,kind,item_id)); c.commit(); c.close(); return redirect(url_for('leaving_soon_page'))

@app.post('/leaving-soon/settings')
def leaving_soon_settings():
    try: days=max(1,min(int(request.form.get('days','14')),90))
    except ValueError: days=14
    set_setting('leaving_soon_days',str(days)); flash('Leaving Soon period saved.','success'); return redirect(url_for('settings'))

@app.get('/changelog')
def changelog():
    versions = [
        ('v2.9.14', 'Security & Private Access: Plex login is now required for library and data pages, and MyCouch verifies that the signed-in Plex account can access the configured Plex server. Added server-side route protection, noindex/robots controls, stronger private response headers, and lightweight 30-day Security Activity logging for noteworthy access events.'),
        ('v2.9.13', 'Server Stats visual refresh: Popular Movies and Popular TV are now compact Top 10 poster grids with ranking badges and hover activity details. Movie and TV detail pages have richer artwork, metadata, activity, storage and quality information. Historical Tautulli titles are retained locally and old Plex rating keys can be relinked to the current title/year match, restoring current artwork and working detail links without slowing Dashboard loads.'),
        ('v2.9.12', 'Smart Search update: year and decade constraints are now honoured, relevance labels use absolute match quality, results rank by relevance instead of favouring newer titles within a decade, and recent searches are separated by signed-in Plex user with shared history for signed-out visitors.'),
        ('v2.9.11', 'Redesigned the Dashboard with a visual welcome hero and mascot shortcuts, introduced a responsive left-hand navigation sidebar, moved account/admin controls to the bottom, and removed duplicated page-heading mascot artwork.'),
        ('v2.9.10', 'Added the MyCouch couch artwork to the dashboard, navigation and section headings, with a light-theme logo and GitHub avatar.'),
        ('v2.9.9', 'Dashboard redesign: Welcome moved to the top, library summary cards moved to Server Stats, Recently Added and Recently Watched poster panels added, split primary/secondary navigation, and retained live Now Playing and Tautulli activity.'),
        ('v2.9.8', 'UI and navigation update: reordered the main menu, renamed Cleanup to Server Stats, added a collapsible linked MyCouch introduction to the Dashboard, and documented Discord /search directly on Smart Search.'),
        ('v2.9.7', 'Renamed LibraryLens to MyCouch. Added GitHub-ready project hygiene, removed machine-specific defaults, refreshed documentation and branding, and renamed the dashboard Now Playing section to “What’s Playing on MyCouch?”. Existing auditor.db, auditor-cache.db and .pla-secret files remain compatible.'),
        ('v2.9.6.2', 'Fixed natural title sorting for Unicode numeric characters such as superscript ² by treating only ASCII 0–9 groups as numeric sort tokens.'),
        ('v2.9.6.1', 'Fixed SQLite sorting failure caused by the NATURAL collation name being parsed as SQL syntax; the custom collation is now quoted correctly.'),
        ('v2.9.6', 'Added Plex account sign-in and private personal play-history/stats, sortable Movies/TV columns with natural and numeric ordering, popularity period filters, and clearer Played Count terminology.'),
        ('v2.9.5.3', 'Light mode added by special request from Kyle, who apparently prefers staring into the sun. Includes a persistent Dark / Light theme toggle that remembers each browser’s choice.'),
        ('v2.9.5.2', 'Dashboard performance update: moved cleanup analysis to a dedicated Cleanup page, replaced full-library dashboard hydration with fast SQLite aggregates, and made Now Playing load asynchronously.'),
        ('v2.9.5.1', 'Discord slash-command hotfix: registers /search directly to the configured guild, reports the exact command sync count/names, and surfaces sync errors.'),
        ('v2.9.5.0', 'Discord bot: adds /search using the same MyCouch Smart Search, with Plex posters and Open in Plex links. Optional private/ephemeral replies and guild-specific command sync.'),
        ('v2.9.4.9', 'Dashboard polish: richer Now Playing cards with Plex posters, direct Plex links, playback progress bars, playback-mode badges, and cleaner episode labels.'),
        ('v2.9.4.8', 'Fixed Smart Search query URLs so new searches replace rather than append to the previous query. Recent-search buttons now use the same in-page search flow and show the animated progress indicator.'),
        ('v2.9.4.7', 'Renamed the website to MyCouch. Smart Search now performs the page request with fetch so the animated Searching indicator remains visible for the entire search. Movie and TV detail pages now include Plex posters and an Open in Plex link.'),
        ('v2.9.4.5', 'Fixed Smart Search progress feedback so the animated Searching indicator is painted before navigation. Added safe cleanup of Auditor-owned Plex snapshot .db/.db-wal/.db-shm files after refreshes and stale snapshot housekeeping at startup.'),
        ('v2.9.4.4', 'Fixed Plex token discovery for Smart Search posters by reusing the saved token or recovering the local Plex Media Server token from Preferences.xml. Corrected Plex connection status so a stale server identity no longer masks a missing token.'),
        ('v2.9.4.3', 'Fixed Smart Search poster compatibility with Plex XML or JSON metadata responses, added direct-thumb fallback and useful poster diagnostics. Added an animated Searching progress indicator.'),
        ('v2.9.4.2', 'Fixed Smart Search poster retrieval by resolving each item’s real Plex thumb path. Added persistent, deduplicated recent Smart Search history with click-to-search and admin Clear History.'),
        ('v2.9.4.1', 'Smart Search result polish: clean genre-only indexing/display, compact synopsis cards, Plex poster thumbnails, relevance labels, and direct Open in Plex links.'),
        ('v2.9.4', 'Smart Search for natural-language movie discovery, live Now Playing dashboard, All Time Tautulli stats, safe live Plex database snapshots with scheduled updates, Discord/Plex groundwork, and status/UI fixes.'),
        ('v2.9.3', 'Movie and TV recommendations using Plex ratings and Tautulli discovery/activity signals, with optional separate Movie and TV Discord webhooks that fall back to the main webhook.'),
        ('v2.9.2', 'Discord embed layout: Jellyseerr-style cards for tests, random stats and Leaving Soon announcements.'),
        ('v2.9.1', 'SQLite compatibility hotfix for Discord/Leaving Soon timestamps.'),
        ('v2.9', 'Discord integration: configurable webhook, test post, scheduled random aggregate library/activity stats with category controls and cooldowns, plus a safe Leaving Soon announcement workflow with no automatic deletion.'),
        ('v2.8.1', 'Public Dashboard, Movies, TV and title details without login; Settings and administrative actions remain protected. Added Remember me with adjustable duration, fixed the Popular TV dashboard layout, and improved missing-title resolution for Tautulli history.'),
        ('v2.8', 'Security update: admin login, password hashing, server-side route protection, CSRF protection, private settings/actions, and privacy-filtered public read-only pages that never expose Tautulli usernames or individual viewing identities.'),
        ('v2.7.1', 'Safe SQLite online backups for auditor.db and auditor-cache.db; manual Back Up Now; adjustable daily backup time, destination and retention.'),
        ('v2.7', 'Incremental Tautulli updates, manual Update Now and Full Rescan, adjustable automatic schedule, Tautulli-authoritative activity, and dashboard popularity/activity stats.'),
        ('v2.6', 'Tautulli integration across all Plex users; background activity sync; never-watched and no-activity filters; Changelog page.'),
        ('v2.5.4', 'Distinguishes exact Arr matches, alternate/duplicate media, and items genuinely not matched in Radarr/Sonarr.'),
        ('v2.5.3.1', 'Fixed Windows SQLite ATTACH handling used by Arr match filters.'),
        ('v2.5.3', 'Added Radarr/Sonarr matched and unmatched options to the Movies and TV filter dropdowns.'),
        ('v2.5.2', 'Server-side SQLite pagination, filtering and sorting; direct detail queries; fixed Movies/TV page slowdowns and freezes.'),
        ('v2.5.1', 'Background Arr matching with progress display; 120-second Sonarr timeout; faster exact-path matching.'),
        ('v2.5', 'Read-only Radarr/Sonarr integration, exact-path matching and Open in Radarr/Sonarr links.'),
        ('v2.4.1', 'Fixed the Choose Database popup by loading the Bootstrap JavaScript bundle.'),
        ('v2.4', 'Added a popup Plex database picker that scans the current backup folder.'),
        ('v2.3', 'Background Plex cache refresh with real progress, stages, item counts and elapsed time.'),
        ('v2.2', 'Introduced the local indexed auditor-cache.db for dramatically faster browsing.'),
        ('v2.1', 'Added changing and validating the Plex database from Settings.'),
        ('v2.0', 'Added movie/TV detail pages, Review Queue, filters, CSV exports and protected-content handling.'),
        ('v1.0', 'Initial Plex Library Auditor dashboard and movie/TV cleanup analysis.')
    ]
    return render_template('changelog.html', versions=versions)


@app.post('/backup/settings')
def backup_settings_route():
    set_setting('backup_auto_enabled','1' if request.form.get('enabled')=='1' else '0')
    set_setting('backup_path',request.form.get('path','').strip().strip('\"'))
    t=request.form.get('time','02:00'); set_setting('backup_time',t if len(t)==5 and t[2]==':' else '02:00')
    try: keep=max(1,min(int(request.form.get('keep','14')),365))
    except ValueError: keep=14
    set_setting('backup_keep',str(keep))
    flash('Backup settings saved.','success')
    return redirect(url_for('settings'))

@app.post('/backup/run')
def backup_run_route():
    if BACKUP_STATUS.get('running'):
        flash('A backup is already running.','warning')
    elif not setting('backup_path'):
        flash('Set a backup destination first.','danger')
    else:
        ok=run_backup()
        flash('SQLite backup completed successfully.' if ok else 'Backup failed: '+str(BACKUP_STATUS.get('error') or 'Unknown error'),'success' if ok else 'danger')
    return redirect(url_for('settings'))

@app.post('/security/settings')
def security_settings_route():
    try: days=max(1,min(int(request.form.get('remember_days','30')),365))
    except (TypeError,ValueError): days=30
    set_setting('remember_days',str(days))
    flash('Login security settings saved. Security Activity retains noteworthy events for 30 days.','success')
    return redirect(url_for('settings'))

@app.get('/security-activity')
def security_activity():
    c=config()
    events=[dict(r) for r in c.execute('select * from security_events order by created_at desc limit 250').fetchall()]
    c.close()
    return render_template('security_activity.html',events=events)


@app.route('/settings', methods=['GET','POST'])
def settings():
    if request.method=='POST':
        new_path=request.form.get('plex_db','').strip().strip('\"')
        if not new_path:
            flash('Enter a Plex database path.','danger')
            return redirect(url_for('settings'))
        try:
            uri='file:'+new_path.replace('\\','/')+'?mode=ro'
            test=sqlite3.connect(uri,uri=True)
            test.execute('select count(*) from library_sections').fetchone()
            test.close()
        except Exception as e:
            flash('Could not open that Plex database: '+str(e),'danger')
            return redirect(url_for('settings'))
        c=config(); c.execute("insert or replace into settings(key,value) values('plex_db',?)",(new_path,)); c.commit(); c.close()
        flash('Plex database changed. Click Refresh Library to rebuild the local cache.','success')
        return redirect(url_for('settings'))
    c=config(); p=c.execute('select * from protected order by kind,title').fetchall(); c.close(); 
    mc=config(); counts={r['kind']:r['n'] for r in mc.execute('select kind,count(*) n from arr_matches group by kind')}; mc.close()
    integrations={'radarr_url':setting('radarr_url','http://localhost:7878'),'sonarr_url':setting('sonarr_url','http://localhost:7879'),'radarr_key':bool(setting('radarr_api_key')),'sonarr_key':bool(setting('sonarr_api_key')),'movie_matches':counts.get('movie',0),'tv_matches':counts.get('tv',0)}
    tc=config(); tautulli_items=tc.execute('select count(*) n from tautulli_activity').fetchone()['n']; tc.close()
    tautulli={'url':setting('tautulli_url','http://localhost:8181'),'key':bool(setting('tautulli_api_key')),'last_sync':setting('tautulli_last_sync','Never'),'items':tautulli_items,'authoritative':setting('tautulli_authoritative','0')=='1','auto_enabled':setting('tautulli_auto_enabled','0')=='1','frequency':setting('tautulli_auto_frequency','daily'),'time':setting('tautulli_auto_time','01:00'),'day':setting('tautulli_auto_day','mon')}
    plex_update={'enabled':setting('plex_auto_enabled','0')=='1','frequency':setting('plex_auto_frequency','daily'),'time':setting('plex_auto_time','03:00')}
    plex_connection={'url':setting('plex_url','http://localhost:32400'),'token':bool(_plex_token()),'machine':bool(setting('plex_machine_id'))}
    security={'remember_days':setting('remember_days','30')}
    backup={'enabled':setting('backup_auto_enabled','0')=='1','path':setting('backup_path',''),'time':setting('backup_time','02:00'),'keep':setting('backup_keep','14'),'last_success':setting('backup_last_success','Never'),'running':BACKUP_STATUS.get('running',False),'error':BACKUP_STATUS.get('error')}
    discord={'enabled':setting('discord_auto_enabled','0')=='1','webhook':bool(setting('discord_webhook_url')),'frequency':setting('discord_frequency','weekly'),'time':setting('discord_post_time','19:00'),'weekday':setting('discord_weekday','4'),'cooldown':setting('discord_cooldown_days','90'),'stats_days':setting('discord_stats_days','30'),'categories':set(setting('discord_categories','popular_movie,popular_tv,viewing_hours,storage_hog,forgotten,movie_recommendation,tv_recommendation').split(',')),'movie_webhook':bool(setting('discord_movie_webhook_url')),'tv_webhook':bool(setting('discord_tv_webhook_url')),'last_post':setting('discord_last_post','Never'),'last_error':setting('discord_last_error',''),'leaving_days':setting('leaving_soon_days','14'),'bot_enabled':setting('discord_bot_enabled','0')=='1','bot_token':bool(setting('discord_bot_token')),'bot_guild_id':setting('discord_bot_guild_id',''),'bot_ephemeral':setting('discord_bot_ephemeral','1')=='1','bot_status':dict(DISCORD_BOT_STATUS)}
    return render_template('settings.html',db=get_db_path(),protected=p,cache=cache_meta(),integrations=integrations,tautulli=tautulli,backup=backup,security=security,discord=discord,plex_update=plex_update,plex_connection=plex_connection)

if __name__=='__main__':
    cleanup_plex_snapshots()
    if setting('discord_bot_enabled','0')=='1' and setting('discord_bot_token','').strip():
        threading.Thread(target=_discord_bot_worker,daemon=True,name='MyCouchDiscordBot').start()
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT','8090')),debug=False)
