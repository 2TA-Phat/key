"""LAB DEMONSTRATION ONLY: UID-only RFID and HTTP are not suitable for real access control."""
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session

rfid_api = Blueprint('rfid_api', __name__)
ROOMS = ('1TA', '2TA', '2TB', '3TE')
ACTIONS = ('開ける', '閉める')
DEVICE = 'esp32-01'

def timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def db():
    con = sqlite3.connect(current_app.config['DATABASE'], timeout=10)
    con.row_factory = sqlite3.Row
    return con

def initialize(db_path):
    with sqlite3.connect(db_path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS rfid_cards (
            uid TEXT PRIMARY KEY, student_id TEXT NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('direct','approval')),
            active INTEGER NOT NULL DEFAULT 1,
            valid_until TEXT,
            FOREIGN KEY(student_id) REFERENCES students(student_id))''')
        con.execute('''CREATE TABLE IF NOT EXISTS rfid_permissions (
            uid TEXT NOT NULL, room TEXT NOT NULL,
            PRIMARY KEY (uid,room), FOREIGN KEY(uid) REFERENCES rfid_cards(uid))''')
        con.execute('''CREATE TABLE IF NOT EXISTS device_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER UNIQUE,
            device_id TEXT NOT NULL, room TEXT NOT NULL,
            action TEXT NOT NULL, source TEXT NOT NULL,
            student_id TEXT,
            state TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            delivered_at TEXT, finished_at TEXT,
            FOREIGN KEY(request_id) REFERENCES requests(id))''')
        con.execute('''CREATE TABLE IF NOT EXISTS access_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_at TEXT NOT NULL, device_id TEXT, uid TEXT,
            student_id TEXT, room TEXT, event_type TEXT NOT NULL,
            detail TEXT NOT NULL)''')
        columns = {row[1] for row in con.execute('PRAGMA table_info(requests)')}
        for column in ('approved_at', 'executed_at', 'execution_status'):
            if column not in columns:
                con.execute(f'ALTER TABLE requests ADD COLUMN {column} TEXT')

def normalize_uid(s):
    s = re.sub(r'[-: ]', '', str(s or '')).upper()
    return s if re.fullmatch('[A-F0-9]{8,20}', s) else None

def auth_device(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        expected = os.environ.get('TIST_DEVICE_TOKEN', '')
        token = request.headers.get('X-Device-Token', '')
        device = request.headers.get('X-Device-ID', '')
        if not expected or not hmac.compare_digest(expected, token) or device != DEVICE:
            return jsonify(error='unauthorized'), 401
        return fn(*a, **kw)
    return wrapped

def admin_only(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not session.get('logged_in') or session.get('role') != 'Administrator':
            return redirect('/login')
        return fn(*a, **kw)
    return wrapped

def valid_csrf():
    expected = session.get('csrf', '')
    actual = request.form.get('csrf', '')
    return bool(expected) and hmac.compare_digest(expected, actual)

def issue_command(con, room, action, source, student_id=None, req_id=None):
    now = datetime.now()
    expires = (now + timedelta(seconds=20)).strftime('%Y-%m-%d %H:%M:%S')
    cur = con.execute('''INSERT INTO device_commands
        (request_id,device_id,room,action,source,student_id,state,created_at,expires_at)
        VALUES (?,?,?,?,?,?,'pending',?,?)''',
        (req_id, DEVICE, room, action, source, student_id,
         now.strftime('%Y-%m-%d %H:%M:%S'), expires))
    return cur.lastrowid

def as_instruction(row):
    return dict(allowed=True, command_id=row['id'], room=row['room'], action=row['action'],
                source=row['source'], expires_at=row['expires_at'])

@rfid_api.post('/admin/rfid/save')
@admin_only
def manage_cards():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(24)
    error = None
    if request.method == 'POST':
        if not valid_csrf():
            return 'Invalid CSRF token', 403
        uid = normalize_uid(request.form.get('uid'))
        student_id = request.form.get('student_id', '').strip()
        mode = request.form.get('mode')
        rooms = [r for r in request.form.getlist('rooms') if r in ROOMS]
        expiry = request.form.get('valid_until', '').strip() or None
        try:
            if not uid or not student_id or mode not in ('direct','approval') or not rooms:
                raise ValueError('UID, student, mode, and rooms are required')
            if expiry:
                datetime.strptime(expiry, '%Y-%m-%d')
            with db() as con:
                con.execute('BEGIN IMMEDIATE')
                if not con.execute('SELECT 1 FROM students WHERE student_id=?',(student_id,)).fetchone():
                    raise ValueError('Student not registered')
                con.execute('''INSERT INTO rfid_cards(uid,student_id,mode,active,valid_until)
                    VALUES(?,?,?,1,?) ON CONFLICT(uid) DO UPDATE SET
                    student_id=excluded.student_id,mode=excluded.mode,
                    active=1,valid_until=excluded.valid_until''',(uid,student_id,mode,expiry))
                con.execute('DELETE FROM rfid_permissions WHERE uid=?',(uid,))
                con.executemany('INSERT INTO rfid_permissions(uid,room) VALUES(?,?)',[(uid,r) for r in rooms])
            return redirect('/admin#rfid-section')
        except (ValueError,sqlite3.Error) as exc:
            error = str(exc)
    with db() as con:
        cards = [dict(c) for c in con.execute('''SELECT c.*,group_concat(p.room,', ') AS rooms
            FROM rfid_cards c LEFT JOIN rfid_permissions p ON p.uid=c.uid
            GROUP BY c.uid ORDER BY c.student_id''')]
    session['rfid_error'] = error or '登録できませんでした'
    return redirect('/admin#rfid-section')

@rfid_api.post('/api/rfid/scan')
@auth_device
def scan_card():
    data = request.get_json(silent=True) or {}
    uid = normalize_uid(data.get('uid'))
    room = data.get('room')
    if not uid or room not in ROOMS:
        return jsonify(allowed=False,reason='invalid_input'),400
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        card = con.execute('''SELECT c.* FROM rfid_cards c
            INNER JOIN rfid_permissions p ON p.uid=c.uid AND p.room=?
            WHERE c.uid=? AND c.active=1 AND (c.valid_until IS NULL OR c.valid_until >= ?)''',
            (room,uid,datetime.now().strftime('%Y-%m-%d'))).fetchone()
        if not card:
            con.execute('INSERT INTO access_events(event_at,device_id,uid,room,event_type,detail) VALUES(?,?,?,?,?,?)',
                        (timestamp(),DEVICE,uid,room,'rfid_denied','card_not_authorized'))
            return jsonify(allowed=False,reason='card_not_authorized'),403
        student_id = card['student_id']
        if card['mode'] == 'approval':
            # Do not generate duplicate pending requests when the same card is scanned repeatedly.
            found = con.execute('''SELECT id FROM requests WHERE student_id=? AND key=? AND action='開ける'
                AND status='申請中' LIMIT 1''',(student_id,room)).fetchone()
            if found:
                req_id = found['id']
            else:
                cur = con.execute('''INSERT INTO requests(student_id,key,action,status,time,source)
                    VALUES(?,?,'開ける','申請中',?,'カード')''',(student_id,room,timestamp()))
                req_id = cur.lastrowid
            con.execute('''INSERT INTO access_events(event_at,device_id,uid,student_id,room,event_type,detail)
                VALUES(?,?,?,?,?,?,?)''',(timestamp(),DEVICE,uid,student_id,room,'rfid_pending',str(req_id)))
            return jsonify(allowed=False,requires_approval=True,request_id=req_id,reason='waiting_teacher_approval')
        # Record the direct card action in the same requests table used by /admin.
        req_cur = con.execute('''INSERT INTO requests(student_id,key,action,status,time,source)
            VALUES(?,?,'開ける','承認',?,'カード')''', (student_id, room, timestamp()))
        req_id = req_cur.lastrowid
        con.execute("UPDATE requests SET approved_at=?, execution_status='実行待ち' WHERE id=?", (timestamp(), req_id))
        command_id = issue_command(con,room,'開ける','rfid_direct',student_id=student_id,req_id=req_id)
        con.execute('''INSERT INTO access_events(event_at,device_id,uid,student_id,room,event_type,detail)
            VALUES(?,?,?,?,?,?,?)''',(timestamp(),DEVICE,uid,student_id,room,'rfid_allowed',str(command_id)))
        row = con.execute('SELECT * FROM device_commands WHERE id=?',(command_id,)).fetchone()
        # The response itself is the delivery for direct RFID commands.
        con.execute("UPDATE device_commands SET state='delivered',delivered_at=? WHERE id=?",(timestamp(),command_id))
        return jsonify(as_instruction(row))

@rfid_api.get('/api/device/commands')
@auth_device
def get_command():
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE device_commands SET state='expired' WHERE state='pending' AND expires_at < ?",(timestamp(),))
        row = con.execute('''SELECT * FROM device_commands WHERE state='pending'
            AND device_id=? AND expires_at>=? ORDER BY id LIMIT 1''',(DEVICE,timestamp())).fetchone()
        if row is None:
            return jsonify(has_command=False)
        con.execute("UPDATE device_commands SET state='delivered',delivered_at=? WHERE id=?",(timestamp(),row['id']))
        return jsonify(has_command=True,**as_instruction(row))

@rfid_api.post('/api/device/result')
@auth_device
def result():
    data = request.get_json(silent=True) or {}
    try:
        command_id = int(data.get('command_id'))
    except (TypeError,ValueError):
        return jsonify(error='invalid_command_id'),400
    outcome = data.get('result')
    if outcome not in ('issued','failed'):
        return jsonify(error='invalid_result'),400
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM device_commands WHERE id=? AND device_id=?',(command_id,DEVICE)).fetchone()
        if not row:
            return jsonify(error='not_found'),404
        if row['state'] in ('issued','failed'):
            return jsonify(ok=True,already_reported=True)
        if row['state'] != 'delivered':
            return jsonify(error='invalid_state'),409
        con.execute('UPDATE device_commands SET state=?,finished_at=? WHERE id=?',(outcome,timestamp(),command_id))
        if row['request_id'] is not None:
            con.execute('UPDATE requests SET executed_at=?, execution_status=? WHERE id=?',
                        (timestamp(),'指令送信済み' if outcome=='issued' else '実行失敗',row['request_id']))
        con.execute('''INSERT INTO access_events(event_at,device_id,student_id,room,event_type,detail)
                       VALUES(?,?,?,?,?,?)''',(timestamp(),DEVICE,row['student_id'],row['room'],'device_result',f'{command_id}:{outcome}'))
    return jsonify(ok=True)

@rfid_api.post('/api/device/heartbeat')
@auth_device
def heartbeat():
    with db() as con:
        con.execute('''INSERT INTO access_events(event_at,device_id,event_type,detail) VALUES(?,?,?,?)''',
                    (timestamp(),DEVICE,'heartbeat','online'))
    return jsonify(ok=True)
