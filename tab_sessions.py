'''SQLite-backed, per-tab Flask sessions for the TIST classroom lab demo.

A signed, HttpOnly browser cookie identifies the browser, and a public _tab selector
selects a separate server-side session within it. _tab alone grants NO access.
'''
import json
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urljoin
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask.sessions import SecureCookieSession, SessionInterface

TAB_RE = re.compile(r'^[a-f0-9]{32}$')
COOKIE_NAME = 'tist_browser_id'


def tab_redirect_location(target, req):
    tab = req.headers.get('X-TIST-Tab') or req.form.get('_tab') or req.args.get('_tab', '')
    if not TAB_RE.fullmatch(tab):
        return target
    u = urlsplit(target)
    if u.scheme or u.netloc:
        return target
    if not u.path.startswith('/'):
        u = urlsplit(urljoin(req.path, target))
    pairs = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != '_tab']
    pairs.append(('_tab', tab))
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(pairs), u.fragment))


class PerTabSession(SecureCookieSession):
    def __init__(self, initial=None, browser_id=None, tab_id=None, new_browser=False):
        super().__init__(initial)
        self.browser_id = browser_id
        self.tab_id = tab_id
        self.new_browser = new_browser


class TabSessionInterface(SessionInterface):
    def _db_path(self, app):
        return app.config['DATABASE']

    def _connect(self, app):
        con = sqlite3.connect(self._db_path(app), timeout=15)
        con.execute('''CREATE TABLE IF NOT EXISTS browser_tab_sessions (
          browser_id TEXT NOT NULL, tab_id TEXT NOT NULL,
          data TEXT NOT NULL, updated_at INTEGER NOT NULL,
          PRIMARY KEY(browser_id, tab_id))''')
        return con

    def _signer(self, app):
        return URLSafeTimedSerializer(app.secret_key, salt='tist-browser-cookie-v1')

    def open_session(self, app, req):
        raw = req.cookies.get(COOKIE_NAME)
        browser_id = None
        if raw:
            try:
                browser_id = self._signer(app).loads(raw, max_age=60*60*24*30)
                if not isinstance(browser_id, str) or len(browser_id) != 64:
                    browser_id = None
            except (BadSignature, SignatureExpired):
                pass
        new_browser = browser_id is None
        if new_browser:
            browser_id = secrets.token_hex(32)
        tab = req.headers.get('X-TIST-Tab') or req.form.get('_tab') or req.args.get('_tab', '')
        if not isinstance(tab, str) or not TAB_RE.fullmatch(tab):
            tab = None
        data = {}
        if tab:
            with self._connect(app) as con:
                row = con.execute('SELECT data FROM browser_tab_sessions WHERE browser_id=? AND tab_id=?',
                                  (browser_id, tab)).fetchone()
                if row:
                    try:
                        data = json.loads(row[0])
                    except (ValueError, TypeError):
                        data = {}
        return PerTabSession(data, browser_id, tab, new_browser)

    def save_session(self, app, session, response):
        if not isinstance(session, PerTabSession):
            return
        if session.tab_id:
            with self._connect(app) as con:
                if session:
                    con.execute('''INSERT INTO browser_tab_sessions(browser_id,tab_id,data,updated_at)
                       VALUES(?,?,?,?) ON CONFLICT(browser_id,tab_id)
                       DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at''',
                        (session.browser_id, session.tab_id, json.dumps(dict(session)), int(time.time())))
                else:
                    con.execute('DELETE FROM browser_tab_sessions WHERE browser_id=? AND tab_id=?',
                                (session.browser_id, session.tab_id))
                # Prune old empty/expired tab rows periodically (30 days).
                if secrets.randbelow(200) == 0:
                    con.execute('DELETE FROM browser_tab_sessions WHERE updated_at<?',
                                (int(time.time()) - 60*60*24*30,))
        # Never expose authentication data or tokens in cookies.
        if session.new_browser:
            response.set_cookie(COOKIE_NAME, self._signer(app).dumps(session.browser_id),
                max_age=60*60*24*30, httponly=True,
                secure=app.config.get('SESSION_COOKIE_SECURE', False), samesite='Lax', path='/')
