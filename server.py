#!/usr/bin/env python3
"""Connect Hub Cloud 1.4: opt-in WebRTC screen sharing, cloud-ready.
No automatic/hidden capture. Both sides may stop.
"""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from aiohttp import web, WSMsgType

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('CONNECT_HUB_DATA_DIR', str(Path.home() / '.config' / 'connect-hub-cloud')))
DATA.mkdir(parents=True, exist_ok=True)
try:
    DATA.chmod(0o700)
except OSError:
    pass

IS_CLOUD = bool(os.environ.get('RENDER') or os.environ.get('CONNECT_HUB_CLOUD'))
PASS_FILE = DATA / 'password'
PASSWORD = os.environ.get('CONNECT_HUB_PASSWORD', '').strip()
if not PASSWORD:
    if IS_CLOUD:
        raise RuntimeError('CONNECT_HUB_PASSWORD must be configured in the hosting environment')
    if not PASS_FILE.exists():
        PASS_FILE.write_text(secrets.token_urlsafe(24), encoding='utf8')
        PASS_FILE.chmod(0o600)
    PASSWORD = PASS_FILE.read_text(encoding='utf8').strip()

SECRET = (os.environ.get('CONNECT_HUB_SECRET') or secrets.token_urlsafe(40)).encode()
PUBLIC_BASE = os.environ.get('CONNECT_HUB_PUBLIC_URL', '').strip().rstrip('/')
DB = DATA / 'sessions.sqlite3'
CLIENTS = {}
SESSION_HOURS = 24

def connect_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with connect_db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, token TEXT UNIQUE NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS sessions_token ON sessions(token)')
        db.execute('CREATE INDEX IF NOT EXISTS sessions_expires ON sessions(expires)')

init_db()

def now():
    return int(time.time())

def sign_cookie():
    ts = str(now())
    nonce = secrets.token_urlsafe(18)
    msg = f'{ts}:{nonce}'
    sig = hmac.new(SECRET, msg.encode(), hashlib.sha256).hexdigest()
    return f'{msg}:{sig}'

def is_owner(req):
    try:
        ts, nonce, signature = req.cookies.get('ch_auth', '').split(':')
        age = now() - int(ts)
        if not (-60 <= age <= 86400):
            return False
        actual = hmac.new(SECRET, f'{ts}:{nonce}'.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, actual)
    except (TypeError, ValueError, AttributeError):
        return False

def require_owner(req):
    if not is_owner(req):
        raise web.HTTPUnauthorized(text='لوحة الإدارة تتطلب تسجيل دخول')

def is_secure(req):
    return req.secure or req.headers.get('X-Forwarded-Proto', '').split(',')[0].lower() == 'https'

def base_url(req):
    if PUBLIC_BASE:
        return PUBLIC_BASE
    proto = 'https' if is_secure(req) else 'http'
    return f'{proto}://{req.host}'

def verify_origin(req):
    origin = req.headers.get('Origin', '')
    if not origin:
        return
    parsed = urlsplit(origin)
    current = urlsplit(base_url(req))
    if parsed.scheme != current.scheme or parsed.netloc != current.netloc:
        raise web.HTTPForbidden(text='Cross-origin actions are not permitted')

def valid_session_by_id(sid):
    with connect_db() as db:
        item = db.execute('SELECT * FROM sessions WHERE id=? AND expires>?', (sid, now())).fetchone()
    return dict(item) if item else None

def valid_session_by_token(token):
    with connect_db() as db:
        item = db.execute('SELECT * FROM sessions WHERE token=? AND expires>?', (token, now())).fetchone()
    return dict(item) if item else None

async def index(req):
    return web.FileResponse(ROOT / 'static' / 'index.html')

async def share(req):
    if not valid_session_by_token(req.match_info['token']):
        raise web.HTTPNotFound(text='الرابط منتهي أو غير صالح')
    return web.FileResponse(ROOT / 'static' / 'share.html')

FAILED = {}

async def login(req):
    verify_origin(req)
    ip = req.headers.get('CF-Connecting-IP') or req.remote or 'unknown'
    recent = [x for x in FAILED.get(ip, []) if x > time.time() - 600]
    FAILED[ip] = recent
    if len(recent) >= 10:
        raise web.HTTPTooManyRequests(text='محاولات كثيرة، حاول لاحقاً')
    data = await req.json()
    if not hmac.compare_digest(str(data.get('password', '')), PASSWORD):
        recent.append(time.time())
        await asyncio.sleep(0.5)
        raise web.HTTPUnauthorized(text='رمز غير صحيح')
    FAILED.pop(ip, None)
    res = web.json_response({'ok': True})
    res.set_cookie('ch_auth', sign_cookie(), httponly=True, secure=is_secure(req), samesite='Strict', max_age=86400, path='/')
    return res

async def logout(req):
    verify_origin(req)
    res = web.json_response({'ok': True})
    res.del_cookie('ch_auth', path='/')
    return res

async def me(req):
    return web.json_response({'owner': is_owner(req)})

async def list_sessions(req):
    require_owner(req)
    with connect_db() as db:
        items = db.execute('SELECT * FROM sessions WHERE expires>? ORDER BY id DESC LIMIT 500', (now(),)).fetchall()
    return web.json_response({'sessions': [
        {'id': i['id'], 'label': i['label'], 'created': i['created'], 'expires': i['expires'], 'link': base_url(req) + '/share/' + i['token']}
        for i in items
    ]})

async def create(req):
    verify_origin(req)
    require_owner(req)
    data = await req.json()
    label = ''.join(c for c in str(data.get('label', '')) if c.isprintable())[:70] or 'جلسة جديدة'
    token = secrets.token_urlsafe(32)
    start = now()
    with connect_db() as db:
        c = db.execute('INSERT INTO sessions (label, created, expires, token) VALUES (?,?,?,?)',
                       (label, start, start + SESSION_HOURS * 3600, token))
        sid = c.lastrowid
    return web.json_response({'id': sid, 'label': label, 'link': base_url(req) + '/share/' + token})

async def delete(req):
    verify_origin(req)
    require_owner(req)
    try:
        sid = int(req.match_info['sid'])
    except ValueError:
        raise web.HTTPBadRequest()
    pair = CLIENTS.pop(sid, {})
    for ws in list(pair.values()):
        if not ws.closed:
            await ws.send_json({'type': 'ended'})
            await ws.close()
    with connect_db() as db:
        db.execute('DELETE FROM sessions WHERE id=?', (sid,))
    return web.json_response({'ok': True})

async def socket(req):
    verify_origin(req)
    role = req.query.get('role', '')
    if role == 'viewer':
        require_owner(req)
        try:
            sid = int(req.query.get('id', ''))
        except ValueError:
            raise web.HTTPBadRequest()
        item = valid_session_by_id(sid)
    elif role == 'sender':
        item = valid_session_by_token(req.query.get('token', ''))
        sid = item['id'] if item else -1
    else:
        raise web.HTTPForbidden()
    if not item:
        raise web.HTTPForbidden(text='جلسة غير صالحة أو منتهية')
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=180000)
    await ws.prepare(req)
    pair = CLIENTS.setdefault(sid, {})
    prior = pair.get(role)
    if prior and not prior.closed:
        await prior.send_json({'type': 'ended'})
        await prior.close()
    pair[role] = ws
    await ws.send_json({'type': 'connected', 'role': role})
    if pair.get('viewer') and pair.get('sender'):
        for client in list(pair.values()):
            if not client.closed:
                await client.send_json({'type': 'peer-ready'})
    counterpart = 'sender' if role == 'viewer' else 'viewer'
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except (json.JSONDecodeError, TypeError):
                continue
            if data.get('type') not in {'offer', 'answer', 'candidate', 'stopped', 'ended', 'peer-ready'}:
                continue
            target = pair.get(counterpart)
            if target and not target.closed:
                await target.send_json(data)
    finally:
        if pair.get(role) is ws:
            pair.pop(role, None)
            target = pair.get(counterpart)
            if target and not target.closed:
                await target.send_json({'type': 'peer-left'})
        if not pair:
            CLIENTS.pop(sid, None)
    return ws

async def health(req):
    return web.json_response({'status': 'ok'})

app = web.Application(client_max_size=100_000)
app.add_routes([
    web.get('/', index), web.get('/share/{token}', share),
    web.post('/api/login', login), web.post('/api/logout', logout), web.get('/api/me', me),
    web.get('/api/sessions', list_sessions), web.post('/api/sessions', create), web.delete('/api/sessions/{sid}', delete),
    web.get('/ws', socket), web.get('/healthz', health), web.static('/static/', ROOT / 'static'),
])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8767'))
    if not IS_CLOUD:
        print('Owner password (local):', PASSWORD)
    print('Connect Hub cloud-ready, listening on port', port)
    web.run_app(app, host='0.0.0.0', port=port)