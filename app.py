import sqlite3
import os
import hmac
import secrets
import urllib.parse
import urllib.request
import urllib.error
import json
import re
import time
import hashlib
import smtplib
import ssl
from email.message import EmailMessage

from flask import Flask, request, redirect, render_template, session, url_for
from rfid_api import rfid_api, initialize, issue_command, ROOMS, ACTIONS
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

app.secret_key = os.environ.get("TIST_FLASK_SECRET", "CHANGE_ME_LOCAL_DEMO_ONLY")
if app.secret_key == "CHANGE_ME_LOCAL_DEMO_ONLY" and os.environ.get("TIST_ALLOW_LOCAL_DEMO") != "1":
    raise RuntimeError("TIST_FLASK_SECRET を設定してください。")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("TIST_HTTPS", "0") == "1")
app.config["DATABASE"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")
app.register_blueprint(rfid_api)

# Cấu hình Mặc định Tài khoản & Mật khẩu Admin






# --- DB 初期化 ---
def init_db():
    conn = sqlite3.connect(app.config["DATABASE"])
    cur = conn.cursor()

    # Bảng Học sinh
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            name TEXT,
            department TEXT,
            course TEXT,
            class TEXT,
            number INTEGER
        )
    """)

    # Bảng Đơn xin mượn chìa khóa
    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            key TEXT,
            action TEXT,
            status TEXT,
            time TEXT
        )
    """)

    # Bảng Quản lý Admin (Managers)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT,
            name TEXT NOT NULL,
            email TEXT,
            role TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)



    cur.execute("PRAGMA table_info(requests)")
    cols = {row[1] for row in cur.fetchall()}
    if "source" not in cols:
        cur.execute("ALTER TABLE requests ADD COLUMN source TEXT NOT NULL DEFAULT 'Web申請'")
    cur.execute("PRAGMA table_info(managers)")
    mcols = {r[1] for r in cur.fetchall()}
    for field in ("phone", "student_id"):
        if field not in mcols:
            cur.execute(f"ALTER TABLE managers ADD COLUMN {field} TEXT")
    cur.execute("""CREATE TABLE IF NOT EXISTS room_permissions (
        manager_id INTEGER NOT NULL,
        room TEXT NOT NULL,
        PRIMARY KEY(manager_id, room)
    )""")
    if 'discord_id' not in mcols:
        cur.execute('ALTER TABLE managers ADD COLUMN discord_id TEXT')
    cur.execute("""CREATE TABLE IF NOT EXISTS login_otp (
        manager_id INTEGER PRIMARY KEY,
        code_hash TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_sent_at INTEGER NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS enrollment_invites (
        student_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL,
        expires_at INTEGER NOT NULL, used_at INTEGER
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS pending_registrations (
        student_id TEXT PRIMARY KEY, username TEXT NOT NULL, email TEXT NOT NULL,
        password_hash TEXT NOT NULL, code_hash TEXT NOT NULL,
        expires_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        last_sent_at INTEGER NOT NULL, invite_hash TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

init_db()
initialize(app.config["DATABASE"])

# Gmail SMTP: application password via environment, not source control.
def email_send_otp(address, code, purpose='ログイン'):
    gmail = os.environ.get('TIST_SMTP_EMAIL', '').strip()
    app_password = os.environ.get('TIST_SMTP_APP_PASSWORD', '').replace(' ', '')
    if not gmail or not app_password:
        app.logger.error('Gmail SMTP is not configured')
        return False
    message = EmailMessage()
    message['From'] = gmail
    message['To'] = address
    message['Subject'] = f'【TIST 鍵管理システム】{purpose}認証コード'
    message.set_content(f'認証コード：{code}\n有効期限：5分\nこのコードを他人に教えないでください。')
    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=12) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(gmail, app_password)
            smtp.send_message(message)
        return True
    except (smtplib.SMTPException, OSError):
        app.logger.exception('OTP mail delivery failed')
        return False

def invite_hash(value):
    return hmac.new(app.secret_key.encode(), ('invite:' + value).encode(), hashlib.sha256).hexdigest()

def registration_hash(student_id, code):
    return hmac.new(app.secret_key.encode(), f'reg:{student_id}:{code}'.encode(), hashlib.sha256).hexdigest()

def make_otp_hash(manager_id, code):
    return hmac.new(app.secret_key.encode(), f'{manager_id}:{code}'.encode(), hashlib.sha256).hexdigest()

ADMIN_ROLES = {'Administrator', 'Admin', '管理者', '教員', 'Teacher', 'Operator'}

def is_admin():
    return bool(session.get('logged_in') and session.get('role') in ADMIN_ROLES)

@app.before_request
def admin_access_control():
    if session.get('logged_in'):
        with sqlite3.connect(app.config['DATABASE']) as con:
            info = con.execute("SELECT status,role FROM managers WHERE id=?",(session.get('manager_id'),)).fetchone()
        if not info or info[0] != '有効' or info[1] != session.get('role') or not session.get('otp_verified'):
            session.clear()
            return redirect(url_for('login'))
    sensitive = ('/admin', '/users', '/approve/', '/reject/', '/delete/')
    if request.path.startswith(sensitive) and not is_admin():
        return redirect(url_for('login')) if not session.get('logged_in') else ('アクセス権限がありません。', 403)
    if request.path.startswith('/admin/managers') and session.get('role') != 'Administrator':
        return 'アクセス権限がありません。', 403

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        invitation = request.form.get('invite', '').strip()
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.row_factory = sqlite3.Row
            manager = conn.execute("SELECT * FROM managers WHERE username=? AND status IN ('有効','メール未確認')", (username,)).fetchone()
            if not (manager and manager['password'] and check_password_hash(manager['password'], password)):
                return render_template('login.html', error='ユーザー名またはパスワードが違います。'), 401
            if manager['status'] == 'メール未確認' and manager['role'] != 'Student':
                return render_template('login.html', error='アカウントを確認できません。'), 403
            # School-issued invitation is required for student accounts at login, not at registration.
            now = int(time.time())
            if manager['role'] == 'Student':
                invite = conn.execute('SELECT * FROM enrollment_invites WHERE student_id=?',
                                      (manager['student_id'],)).fetchone()
                if (not invitation or not invite or invite['used_at'] is not None
                        or invite['expires_at'] < now
                        or not hmac.compare_digest(invite['token_hash'], invite_hash(invitation))):
                    return render_template('login.html', error='招待コードが無効または期限切れです。学校から新しいコードを取得してください。'), 403
            if not manager['email'] or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', manager['email']):
                return render_template('login.html', error='メールアドレスが未登録です。管理者にお問い合わせください。'), 400
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT last_sent_at FROM login_otp WHERE manager_id=?', (manager['id'],)).fetchone()
            if previous and now - previous['last_sent_at'] < 60:
                return render_template('login.html', error='認証コードの再送信は60秒後にお試しください。'), 429
            code = f'{secrets.randbelow(1000000):06d}'
            # 送信前にOTPを無効化し、処理を直列化。送信失敗時はログイン不可。
            conn.execute('DELETE FROM login_otp WHERE manager_id=?', (manager['id'],))
            if not email_send_otp(manager['email'], code):
                return render_template('login.html', error='メール送信に失敗しました。管理者にお問い合わせください。'), 503
            conn.execute('INSERT INTO login_otp(manager_id,code_hash,expires_at,attempts,last_sent_at) VALUES(?,?,?,?,?)',
                         (manager['id'], make_otp_hash(manager['id'], code), now + 300, 0, now))
            session.clear()
            session['pending_manager_id'] = manager['id']
            if manager['role'] == 'Student':
                session['pending_invite_hash'] = invite['token_hash']
            session['otp_session_expires'] = now + 300
            return redirect(url_for('verify_otp'))
    return render_template('login.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    manager_id = session.get('pending_manager_id')
    if not manager_id or int(time.time()) > session.get('otp_session_expires', 0):
        session.clear()
        return redirect(url_for('login'))
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        if not re.fullmatch(r'\d{6}', code):
            return render_template('verify_otp.html', error='6桁の認証コードを入力してください。'), 400
        now = int(time.time())
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            otp = conn.execute('SELECT * FROM login_otp WHERE manager_id=?', (manager_id,)).fetchone()
            manager = conn.execute("SELECT * FROM managers WHERE id=? AND status IN ('有効','メール未確認')", (manager_id,)).fetchone()
            if not manager or not otp or now > otp['expires_at'] or otp['attempts'] >= 5:
                conn.execute('DELETE FROM login_otp WHERE manager_id=?', (manager_id,))
                session.clear()
                return render_template('login.html', error='認証コードが無効です。再度ログインしてください。'), 401
            conn.execute('UPDATE login_otp SET attempts=attempts+1 WHERE manager_id=?', (manager_id,))
            if not hmac.compare_digest(otp['code_hash'], make_otp_hash(manager_id, code)):
                if otp['attempts'] + 1 >= 5:
                    conn.execute('DELETE FROM login_otp WHERE manager_id=?', (manager_id,))
                    session.clear()
                    return render_template('login.html', error='認証回数の上限に達しました。'), 429
                return render_template('verify_otp.html', error='認証コードが正しくありません。'), 401
            if manager['role'] == 'Student':
                invite = conn.execute('SELECT * FROM enrollment_invites WHERE student_id=?',
                                      (manager['student_id'],)).fetchone()
                expected_invite_hash = session.get('pending_invite_hash', '')
                if (not invite or invite['used_at'] is not None or now > invite['expires_at']
                        or not expected_invite_hash
                        or not hmac.compare_digest(invite['token_hash'], expected_invite_hash)):
                    conn.execute('DELETE FROM login_otp WHERE manager_id=?', (manager_id,))
                    session.clear()
                    return render_template('login.html', error='招待コードの有効期限が切れました。再度ログインしてください。'), 403
                conn.execute('UPDATE enrollment_invites SET used_at=? WHERE student_id=?',
                             (now, manager['student_id']))
            if manager['role'] == 'Student' and manager['status'] == 'メール未確認':
                conn.execute("UPDATE managers SET status='有効' WHERE id=? AND status='メール未確認'", (manager_id,))
            conn.execute('DELETE FROM login_otp WHERE manager_id=?', (manager_id,))
        session.clear()
        session.update(logged_in=True, manager_id=manager['id'], username=manager['username'],
                       name=manager['name'], role=manager['role'], student_id=manager['student_id'], otp_verified=True)
        session['csrf'] = secrets.token_hex(24)
        return redirect(url_for('admin') if is_admin() else url_for('student_submit'))
    return render_template('verify_otp.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- 生徒画面 ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/student_submit', methods=['GET', 'POST'])
def student_submit():
    if request.method == 'GET':
        if not session.get('logged_in') or not session.get('otp_verified'):
            return redirect(url_for('login'))
        if session.get('logged_in') and not session.get('csrf'):
            session['csrf'] = secrets.token_hex(24)
        return render_template('student.html', rooms=ROOMS, actions=ACTIONS,
                               authenticated=bool(session.get('logged_in') and session.get('otp_verified')),
                               student_id=session.get('student_id', ''))
    if not session.get('logged_in') or not session.get('otp_verified'):
        return redirect(url_for('login'))
    student_id = request.form.get('student_id', '').strip()
    key = request.form.get('key', '').strip()
    action = request.form.get('action', '').strip()
    if key not in ROOMS or action not in ACTIONS:
        return '教室または操作の指定が正しくありません。', 400
    authed = bool(session.get('logged_in') and session.get('otp_verified'))
    if not hmac.compare_digest(request.form.get('csrf', ''), session.get('csrf', '')):
        return '認証エラー', 403
    if authed and not is_admin():
        if not session.get('student_id'):
            return '学籍番号がアカウントに設定されていません。', 403
        student_id = session['student_id']
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        student = conn.execute('SELECT student_id FROM students WHERE student_id=?', (student_id,)).fetchone()
        if not student:
            return render_template('student.html', rooms=ROOMS, actions=ACTIONS,
                                   authenticated=authed, student_id=student_id,
                                   error='学籍番号が登録されていません。'), 400
        instant = False
        if authed and (not is_admin() or session.get('student_id') == student_id):
            permission = conn.execute('SELECT 1 FROM room_permissions WHERE manager_id=? AND room=?',
                                      (session['manager_id'], key)).fetchone()
            instant = bool(permission)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute("INSERT INTO requests (student_id, key, action, status, time, source) VALUES (?, ?, ?, '申請中', ?, ?)",
                           (student_id, key, action, now, '認証済Web申請' if authed else 'Web申請'))
        if instant:
            conn.execute("UPDATE requests SET status='承認', approved_at=?, execution_status='待機中' WHERE id=?",
                         (now, cur.lastrowid))
            issue_command(conn, key, action, 'verified_user', student_id, cur.lastrowid)
    return render_template('student.html', rooms=ROOMS, actions=ACTIONS,
                           authenticated=authed, student_id=student_id, sent=True,
                           message='開錠指令を送信しました。装置の応答をお待ちください。' if instant else '申請を受け付けました。教員の承認をお待ちください。')

@app.route("/status", methods=["POST"])
def status():
    student_id = request.form.get("student_id")
    if not is_admin() and (not session.get('otp_verified') or session.get('student_id') != student_id):
        return 'アクセス権限がありません。', 403

    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT r.id, r.key, r.action, r.status, r.time
        FROM requests r
        WHERE r.student_id=?
        ORDER BY r.time DESC
    """, (student_id,))

    results = cur.fetchall()
    conn.close()

    return render_template("student.html", results=results)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        session['register_csrf'] = secrets.token_hex(24)
        return render_template('register.html', csrf=session['register_csrf'])
    if not session.get('register_csrf') or not hmac.compare_digest(request.form.get('csrf', ''), session['register_csrf']):
        return '認証エラー', 403
    student_id = request.form.get('student_id', '').strip()
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    def invalid(message, status=400):
        return render_template('register.html', error=message, csrf=session['register_csrf']), status
    if (not re.fullmatch(r'[A-Za-z0-9_-]{3,64}', username)
            or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)
            or len(email) > 254 or len(password) < 8 or len(password) > 15
            or not student_id):
        return invalid('入力内容をご確認ください。パスワードは8～15文字にしてください。')
    # Create an inactive account. Email is verified during the FIRST login OTP.
    # A student must already exist in the school-controlled students table.
    with sqlite3.connect(app.config['DATABASE'], timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        student = conn.execute('SELECT student_id,name FROM students WHERE student_id=?', (student_id,)).fetchone()
        claimed = conn.execute('SELECT 1 FROM managers WHERE student_id=? OR username=? OR lower(email)=?',
                               (student_id,username,email)).fetchone()
        if not student or claimed:
            return invalid('登録できません。学籍番号またはアカウント情報をご確認ください。')
        conn.execute("""INSERT INTO managers (username,password,name,email,role,status,student_id)
                        VALUES (?,?,?,?,'Student','メール未確認',?)""",
                     (username,generate_password_hash(password),student['name'],email,student_id))
    session.pop('register_csrf',None)
    return render_template('registration_complete.html')

# --- ユーザー画面 ---
@app.route("/users")
def users():
    if not session.get("logged_in"):
        return redirect("/login")

    # Điều kiện từ form GET /users?contact_id=...&date_from=...&date_to=...
    contact_id = request.args.get("contact_id", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    # Giới hạn ngày an toàn và tránh lỗi khi truy vấn.
    for value in (date_from, date_to):
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return "日付の形式が正しくありません。", 400

    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Tính thời gian đầu/cuối và tổng số yêu cầu trên TOÀN BỘ lịch sử.
    # Chỉ dùng EXISTS để xác định học sinh có yêu cầu trong khoảng ngày lọc.
    where_conditions = []
    params = []
    if contact_id:
        escaped_id = contact_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where_conditions.append("s.student_id LIKE ? ESCAPE '\\'")
        params.append("%" + escaped_id + "%")

    # if date_from or date_to:
    #     conditions = ["rf.student_id = s.student_id"]
    #     if date_from:
    #         conditions.append("rf.time >= ?")
    #         params.append(date_from + " 00:00:00")
    #     if date_to:
    #         from datetime import timedelta
    #         next_day = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    #         conditions.append("rf.time < ?")
    #         params.append(next_day + " 00:00:00")
    #     where_conditions.append("EXISTS (SELECT 1 FROM requests rf WHERE " + " AND ".join(conditions) + ")")

    sql = """
        SELECT
            s.student_id AS contact_id,
            s.name, s.department, s.course, s.class, s.number,
            MIN(r.time) AS first_login,
            MAX(r.time) AS last_login,
            SUM(CASE WHEN r.status = '申請中' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN r.status IN ('承認', '却下') THEN 1 ELSE 0 END) AS done_count
        FROM students s
        LEFT JOIN requests r ON s.student_id = r.student_id
    """
    if where_conditions:
        sql += " WHERE " + " AND ".join(where_conditions)

    sql += " GROUP BY s.student_id HAVING 1=1"

    if date_from:
        sql += " AND DATE(MIN(r.time)) >= ?"
        params.append(date_from)

    if date_to:
        sql += " AND DATE(MIN(r.time)) <= ?"
        params.append(date_to)

    sql += " ORDER BY last_login DESC, s.student_id ASC"
    print("SQL ĐANG CHẠY:", sql, flush=True)
    print("PARAMS:", params, flush=True)

    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    user_list = []
    total_pending = 0
    total_done = 0

    for row in rows:
        item = dict(row)
        
        p_count = item["pending_count"] or 0
        d_count = item["done_count"] or 0
        
        total_pending += p_count
        total_done += d_count

        if p_count > 0:
            item["process_status"] = "未処理"
        else:
            item["process_status"] = "完了"

        user_list.append(item)

    return render_template(
        "users.html", 
        users=user_list, 
        total_users=len(user_list),
        total_pending=total_pending,
        total_done=total_done
    )

# --- 先生画面 ---
@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT r.id, r.student_id, r.key, r.action, r.status, r.time, r.source, r.execution_status,
               s.name, s.department, s.course, s.class, s.number
        FROM requests r
        LEFT JOIN students s ON r.student_id = s.student_id
        WHERE r.status='申請中'
        ORDER BY r.time DESC
    """)
    pending_rows = cur.fetchall()

    cur.execute("""
        SELECT r.id, r.student_id, r.key, r.action, r.status, r.time, r.source, r.execution_status,
               s.name, s.department, s.course, s.class, s.number
        FROM requests r
        LEFT JOIN students s ON r.student_id = s.student_id
        WHERE r.status!='申請中'
        ORDER BY r.time DESC
    """)
    done_rows = cur.fetchall()

    device_event = cur.execute("""SELECT event_at FROM access_events
        WHERE device_id='esp32-01' AND event_type='heartbeat'
        ORDER BY id DESC LIMIT 1""").fetchone()
    conn.close()
    last_seen = device_event['event_at'] if device_event else None
    device_online = bool(last_seen and
        (datetime.now() - datetime.strptime(last_seen, '%Y-%m-%d %H:%M:%S')).total_seconds() < 90)

    pending = [dict(row) for row in pending_rows]
    done = [dict(row) for row in done_rows]

    import secrets
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(24)
    return render_template("admin.html", pending=pending, done=done, csrf=session['csrf'], device_online=device_online, last_seen=last_seen)

@app.get('/admin/api/lock-status')
def lock_status():
    if not session.get('logged_in'):
        return {'error': 'unauthorized'}, 401
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""SELECT id, status, execution_status, executed_at
            FROM requests ORDER BY id DESC LIMIT 100""").fetchall()
        last = conn.execute("""SELECT event_at FROM access_events
            WHERE device_id='esp32-01' AND event_type='heartbeat'
            ORDER BY id DESC LIMIT 1""").fetchone()
    seen = last['event_at'] if last else None
    online = bool(seen and (datetime.now() - datetime.strptime(seen, '%Y-%m-%d %H:%M:%S')).total_seconds() < 90)
    return {'online': online, 'last_seen': seen,
            'requests': [dict(r) for r in rows]}

# --- 管理者一覧画面 (MỚI BỔ SUNG) ---
@app.route("/admin/managers")
def admin_managers():

    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM managers ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()

    managers = [dict(row) for row in rows]
    return render_template("managers.html", managers=managers)
# --- 管理者追加 ---
@app.route("/admin/managers/add", methods=["GET", "POST"])
def manager_add():
    if not session.get("logged_in"):
        return redirect("/login")

    if request.method == "GET":
        return render_template("manager_add.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "Operator")
    status = request.form.get("status", "有効")

    if not username or not password or not name:
        return render_template(
            "manager_add.html",
            error="必須項目を入力してください。"
        )

    

    conn = sqlite3.connect(app.config["DATABASE"])
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO managers
            (username, password, name, email, role, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            username,
            generate_password_hash(password),
            name,
            email,
            role,
            status
        ))

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        return render_template(
            "manager_add.html",
            error="このユーザー名は既に使用されています。"
        )

    conn.close()
    return redirect("/admin/managers")


# --- 管理者詳細 ---
@app.route("/admin/managers/<int:manager_id>")
def manager_detail(manager_id):
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, username, name, email, role, status
        FROM managers
        WHERE id = ?
    """, (manager_id,))

    manager = cur.fetchone()
    conn.close()

    if not manager:
        return "管理者が見つかりません", 404

    return render_template(
        "manager_detail.html",
        manager=manager
    )


# --- 管理者編集 ---
@app.route("/admin/managers/<int:manager_id>/edit", methods=["GET", "POST"])
def manager_edit(manager_id):
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if request.method == "GET":
        cur.execute("""
            SELECT id, username, name, email, role, status
            FROM managers
            WHERE id = ?
        """, (manager_id,))

        manager = cur.fetchone()
        conn.close()

        if not manager:
            return "管理者が見つかりません", 404

        return render_template(
            "manager_edit.html",
            manager=manager
        )

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "Operator")
    status = request.form.get("status", "有効")

    if password:
        password_hash = generate_password_hash(password)

        cur.execute("""
            UPDATE managers
            SET username=?,
                password=?,
                name=?,
                email=?,
                role=?,
                status=?
            WHERE id=?
        """, (
            username,
            password_hash,
            name,
            email,
            role,
            status,
            manager_id
        ))

    else:
        cur.execute("""
            UPDATE managers
            SET username=?,
                name=?,
                email=?,
                role=?,
                status=?
            WHERE id=?
        """, (
            username,
            name,
            email,
            role,
            status,
            manager_id
        ))

    conn.commit()
    conn.close()

    return redirect("/admin/managers")


# --- 管理者削除 ---
@app.route("/admin/managers/<int:manager_id>/delete", methods=["POST"])
def manager_delete(manager_id):
    from rfid_api import valid_csrf
    if not valid_csrf():
        return "認証エラー", 403

    if session.get("manager_id") == manager_id:
        return redirect("/admin/managers")

    conn = sqlite3.connect(app.config["DATABASE"])
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM managers WHERE id=?",
        (manager_id,)
    )

    conn.commit()
    conn.close()

    return redirect("/admin/managers")

@app.route('/admin/access-settings', methods=['GET', 'POST'])
def access_settings():
    if not session.get('logged_in') or session.get('role') != 'Administrator':
        return 'アクセス権限がありません。', 403
    if request.method == 'POST':
        from rfid_api import valid_csrf
        if not valid_csrf():
            return '認証エラー', 403
        manager_id = request.form.get('manager_id', type=int)
        discord_id = request.form.get('discord_id', '').strip()
        student_id = request.form.get('student_id', '').strip()
        rooms = request.form.getlist('rooms')
        if discord_id and not re.fullmatch(r'\d{17,22}', discord_id):
            return 'DiscordユーザーIDの形式が正しくありません。', 400
        if any(room not in ROOMS for room in rooms):
            return '教室の指定が正しくありません。', 400
        with sqlite3.connect(app.config['DATABASE']) as conn:
            if not conn.execute('SELECT 1 FROM managers WHERE id=?', (manager_id,)).fetchone():
                return 'ユーザーが見つかりません。', 404
            if student_id and not conn.execute('SELECT 1 FROM students WHERE student_id=?', (student_id,)).fetchone():
                return '学籍番号が登録されていません。', 400
            conn.execute('UPDATE managers SET discord_id=?, student_id=? WHERE id=?', (discord_id, student_id, manager_id))
            conn.execute('DELETE FROM room_permissions WHERE manager_id=?', (manager_id,))
            conn.executemany('INSERT INTO room_permissions(manager_id,room) VALUES (?,?)', [(manager_id, x) for x in rooms])
        return redirect(url_for('access_settings'))
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.row_factory = sqlite3.Row
        accounts = [dict(r) for r in conn.execute('SELECT id,username,name,role,discord_id,student_id FROM managers ORDER BY id')]
        permissions = conn.execute('SELECT manager_id,room FROM room_permissions').fetchall()
    granted = {}
    for p in permissions:
        granted.setdefault(p['manager_id'], set()).add(p['room'])
    return render_template('access_settings.html', accounts=accounts, rooms=ROOMS, granted=granted,
                           csrf=session.get('csrf') or init_csrf())

def init_csrf():
    session['csrf'] = secrets.token_hex(24)
    return session['csrf']

# --- 承認・却下・削除 ---
@app.route("/approve/<int:req_id>", methods=["POST"])
def approve(req_id):
    if not session.get("logged_in"):
        return redirect("/login")
    from rfid_api import valid_csrf
    if not valid_csrf():
        return "Invalid CSRF", 403
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT * FROM requests WHERE id=? AND status='申請中'",(req_id,)).fetchone()
        if row and row['key'] in ROOMS and row['action'] in ACTIONS:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("UPDATE requests SET status='承認',approved_at=?,execution_status='待機中' WHERE id=?",(now,req_id))
            issue_command(conn,row['key'],row['action'],'teacher_approval',row['student_id'],req_id)
    return redirect('/admin')

@app.route("/reject/<int:req_id>", methods=["POST"])
def reject(req_id):
    if not session.get("logged_in"):
        return redirect("/login")
    from rfid_api import valid_csrf
    if not valid_csrf():
        return "Invalid CSRF", 403
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        conn.execute("UPDATE requests SET status='却下' WHERE id=? AND status='申請中'",(req_id,))
    return redirect('/admin')

@app.route("/delete/<int:req_id>", methods=["POST"])
def delete(req_id):
    from rfid_api import valid_csrf
    if not valid_csrf():
        return "認証エラー", 403
    if not session.get("logged_in"):
        return redirect("/login")
    conn = sqlite3.connect(app.config["DATABASE"])
    cur = conn.cursor()
    cur.execute("DELETE FROM requests WHERE id=?", (req_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

# --- 起動 ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

