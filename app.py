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

from flask import Flask, request, redirect, render_template, session, url_for, g
from rfid_api import rfid_api, initialize, issue_command, ROOMS, ACTIONS, ROOM_DEVICE
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from tab_sessions import TabSessionInterface, tab_redirect_location


app = Flask(__name__)

app.secret_key = os.environ.get("TIST_FLASK_SECRET", "CHANGE_ME_LOCAL_DEMO_ONLY")
if app.secret_key == "CHANGE_ME_LOCAL_DEMO_ONLY" and os.environ.get("TIST_ALLOW_LOCAL_DEMO") != "1":
    raise RuntimeError("TIST_FLASK_SECRET を設定してください。")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("TIST_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=3),
    SESSION_REFRESH_EACH_REQUEST=False,
)
app.config["DATABASE"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")
app.session_interface = TabSessionInterface()
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
    for field in ("phone", "student_id", "department", "school_class", "course"):
        if field not in mcols:
            cur.execute(f"ALTER TABLE managers ADD COLUMN {field} TEXT")
    if "number" not in mcols:
        cur.execute("ALTER TABLE managers ADD COLUMN number INTEGER")
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
    # Guest requests are never authenticated or automatically executed.
    cur.execute("PRAGMA table_info(requests)")
    request_cols = {row[1] for row in cur.fetchall()}
    if 'guest_name' not in request_cols:
        cur.execute("ALTER TABLE requests ADD COLUMN guest_name TEXT")
    cur.execute("""CREATE TABLE IF NOT EXISTS guest_request_limits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_address TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_guest_limits_time ON guest_request_limits(created_at)")
    conn.commit()
    conn.close()

init_db()
initialize(app.config["DATABASE"])

# Gmail SMTP: application password via environment, not source control.

def email_send_otp(address, code, purpose="ログイン"):
    import base64
    from pathlib import Path
    from email.message import EmailMessage
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_file = (
        Path(__file__).resolve().parent
        / "secrets" / "gmail_token.json"
    )

    scopes = [
        "https://www.googleapis.com/auth/gmail.send"
    ]

    try:
        credentials = Credentials.from_authorized_user_file(
            str(token_file), scopes
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_file.write_text(
                credentials.to_json(),
                encoding="utf-8"
            )

        if not credentials.valid:
            raise RuntimeError("Gmail OAuth credentials invalid")

        message = EmailMessage()
        message["From"] = "uongtriphat.wall@gmail.com"
        message["To"] = address
        message["Subject"] = (
            f"【TIST 鍵管理システム】{purpose}認証コード"
        )
        message.set_content(
            f"認証コード：{code}\n"
            "有効期限：5分\n"
            "このコードを他人に教えないでください。"
        )

        raw = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode("ascii")

        service = build(
            "gmail", "v1",
            credentials=credentials,
            cache_discovery=False
        )

        service.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()

        app.logger.info("Gmail API OTP sent successfully")
        return True

    except Exception:
        app.logger.exception("Gmail API OTP delivery failed")
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


def complete_login(manager):
    """Administrator: absolute 3 hours; other accounts: absolute 5 minutes."""
    session.clear()
    session.permanent = True
    session.update(
        logged_in=True,
        manager_id=manager['id'],
        username=manager['username'],
        name=manager['name'],
        role=manager['role'],
        student_id=manager['student_id'],
        otp_verified=True,
        auth_expires_at=int(time.time()) + (3 * 3600 if manager['role'] == 'Administrator' else 300),
    )
    session['csrf'] = secrets.token_hex(24)


@app.after_request
def preserve_tab_in_redirect(response):
    # Ensure every Flask redirect stays inside the originating tab's session.
    if response.status_code in (301, 302, 303, 307, 308):
        target = response.headers.get('Location', '')
        if target:
            response.headers['Location'] = tab_redirect_location(target, request)
    response.headers['Cache-Control'] = 'no-store' if request.path.startswith(('/admin', '/student_submit', '/guest/', '/login', '/verify-otp')) else response.headers.get('Cache-Control','no-cache')
    return response

@app.before_request
def admin_access_control():
    if session.get('logged_in'):
        # All roles use absolute timeouts: Administrator 3 hours, others 5 minutes.
        if int(time.time()) >= session.get('auth_expires_at', 0):
            session.clear()
            if request.path.startswith(('/admin', '/users', '/approve/', '/reject/', '/delete/')):
                return redirect(url_for('login'))
        else:
            with sqlite3.connect(app.config['DATABASE']) as con:
                info = con.execute("SELECT status,role FROM managers WHERE id=?", (session.get('manager_id'),)).fetchone()
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
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.row_factory = sqlite3.Row
            manager = conn.execute("SELECT * FROM managers WHERE username=?", (username,)).fetchone()
            if not (manager and manager['password'] and check_password_hash(manager['password'], password)):
                return render_template('login.html', error='ユーザー名またはパスワードが違います。'), 401
            if manager['status'] == '承認待ち':
                return render_template('login.html', error='先生の承認待ちです。承認後にログインできます。'), 403
            if manager['status'] != '有効':
                return render_template('login.html', error='このアカウントは現在利用できません。'), 403
            # Only the exact Administrator role may use the requested password-only login.
            # Other roles continue to require their email OTP.
            if manager['role'] == 'Administrator':
                complete_login(manager)
                return redirect(url_for('admin_choice'))
            # Teachers approve new students; no invitation code is required.
            now = int(time.time())
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
            manager = conn.execute("SELECT * FROM managers WHERE id=? AND status='有効'", (manager_id,)).fetchone()
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
            conn.execute('DELETE FROM login_otp WHERE manager_id=?', (manager_id,))
        complete_login(manager)
        return redirect(url_for('admin') if is_admin() else url_for('student_submit'))
    return render_template('verify_otp.html')

@app.route('/admin/choose', methods=['GET'])
def admin_choice():
    # Only an authenticated and active Administrator may use this landing page.
    if not (session.get('logged_in') and session.get('otp_verified')
            and session.get('role') == 'Administrator'):
        return redirect(url_for('login')) if not session.get('logged_in') else ('アクセス権限がありません。', 403)
    return render_template('admin_choice.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- 生徒画面 ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/student_submit', methods=['GET', 'POST'])
def student_submit(guest_mode=False):
    # Guest and authenticated submissions must remain separate PER REQUEST,
    # never by clearing or overwriting the shared browser session.
    authenticated = bool(not guest_mode and session.get('logged_in') and session.get('otp_verified'))
    teacher = authenticated and is_admin()
    csrf_key = 'guest_csrf' if guest_mode else 'csrf'
    if csrf_key not in session:
        session[csrf_key] = secrets.token_hex(24)

    # A teacher number must be stored on the authenticated account; if absent,
    # use the account username as an identifier, without treating it as a verified staff ID.
    account_identifier = ('' if guest_mode else
                          (session.get('student_id') or session.get('username') or '').strip()
                          if teacher else ('' if guest_mode else (session.get('student_id') or '').strip()))
    def page(status=200, **kwargs):
        context = dict(
            rooms=ROOMS,
            actions=ACTIONS,
            authenticated=authenticated,
            teacher=teacher,
            student_id=account_identifier,
            csrf=session[csrf_key],
            selected_room=ROOMS[0],
            selected_action=ACTIONS[0]
        )
        context.update(kwargs)
        html = render_template('student.html', **context)
        if guest_mode:
            # Keep POSTs on the guest-only endpoint, even if an Admin is logged
            # in on another tab. The existing Japanese template stays unchanged.
            def rewrite_form(match):
                tag = match.group(0)
                target = url_for('guest_student_submit')
                if re.search(r'\baction\s*=', tag, flags=re.IGNORECASE):
                    return re.sub(r'\baction\s*=\s*(["\']).*?\1',
                                  lambda _: f'action="{target}"', tag,
                                  count=1, flags=re.IGNORECASE)
                return tag[:-1] + f' action="{target}">'
            html = re.sub(r'<form\b[^>]*>', rewrite_form, html, count=1, flags=re.IGNORECASE)
            # The current student.html was not attached. Ensure a template that
            # reads session['csrf'] instead of the provided csrf variable still
            # submits the separate guest-only CSRF value.
            def rewrite_csrf_input(match):
                tag = match.group(0)
                if not re.search(r'\bname\s*=\s*(["\'])csrf\1', tag, flags=re.IGNORECASE):
                    return tag
                value = session[csrf_key]
                if re.search(r'\bvalue\s*=', tag, flags=re.IGNORECASE):
                    return re.sub(r'\bvalue\s*=\s*(["\']).*?\1',
                                  lambda _: f'value="{value}"', tag,
                                  count=1, flags=re.IGNORECASE)
                return tag[:-1] + f' value="{value}">'
            html = re.sub(r'<input\b[^>]*>', rewrite_csrf_input, html, flags=re.IGNORECASE)
        return html, status

    if request.method == 'GET':
        return page()[0]
    if not hmac.compare_digest(request.form.get('csrf', ''), session.get(csrf_key, '')):
        return '認証エラー', 403

    requested_id = request.form.get('student_id', '').strip()
    guest_name = request.form.get('guest_name', '').strip()
    room = request.form.get('key', '').strip()
    action = request.form.get('action', '').strip()
    if room not in ROOMS or action not in ACTIONS:
        return '教室または操作の指定が正しくありません。', 400

    # Never trust a client-supplied identifier for an authenticated user.
    identifier = account_identifier if authenticated else requested_id
    if authenticated and not identifier:
        return page(403, error='アカウントに番号が登録されていません。管理者にお問い合わせください。')
    if not re.fullmatch(r'[0-9A-Za-z_-]{3,64}', identifier):
        return page(400, student_id=identifier,
                    error=('先生番号' if teacher else '学籍番号') + 'を正しく入力してください。')
    if not authenticated and (not 1 <= len(guest_name) <= 100 or any(ord(c) < 32 for c in guest_name)):
        return page(400, student_id=identifier, error='名前を正しく入力してください。')

    with sqlite3.connect(app.config['DATABASE'], timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        if authenticated:
            # Re-check the account in the database at the moment the command is queued.
            account = conn.execute('SELECT id,username,student_id,name,role,status FROM managers WHERE id=?',
                                   (session.get('manager_id'),)).fetchone()
            if not account or account['status'] != '有効' or account['role'] != session.get('role'):
                return page(403, error='アカウントの認証を確認できませんでした。')
            if account['role'] == 'Student':
                if not account['student_id']:
                    return page(403, error='学籍番号が登録されていません。')
                identifier = account['student_id']
            elif account['role'] in ADMIN_ROLES:
                identifier = (account['student_id'] or account['username'] or '').strip()
            else:
                return page(403, error='アクセス権限がありません。')
            if not re.fullmatch(r'[0-9A-Za-z_-]{3,64}', identifier):
                return page(403, error='アカウント番号の設定を確認してください。')
        else:
            # Unregistered guests can request a review, but never get an automatic command.
            now_epoch = int(time.time())
            ip = request.remote_addr or 'unknown'
            conn.execute('DELETE FROM guest_request_limits WHERE created_at < ?', (now_epoch - 86400,))
            count = conn.execute('SELECT COUNT(*) FROM guest_request_limits WHERE ip_address=? AND created_at>=?',
                                 (ip, now_epoch - 3600)).fetchone()[0]
            if count >= 5:
                return page(429, student_id=identifier, error='申請回数の上限に達しました。時間をおいてお試しください。')
            conn.execute('INSERT INTO guest_request_limits(ip_address,created_at) VALUES (?,?)',
                         (ip, now_epoch))

        instant = authenticated
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        source = ('教員Web申請' if teacher else '認証済Web申請') if authenticated else '未認証Web申請'
        # Preserve teacher name for the admin list even if no student roster record exists.
        display_name = account['name'] if authenticated and teacher else (guest_name if not authenticated else None)
        cur = conn.execute("INSERT INTO requests(student_id,key,action,status,time,source,guest_name) VALUES (?,?,?,'申請中',?,?,?)",
                           (identifier, room, action, now, source, display_name))
        if instant:
            conn.execute("UPDATE requests SET status='承認',approved_at=?,execution_status='待機中' WHERE id=?",
                         (now, cur.lastrowid))
            issue_command(conn, room, action, 'verified_user', identifier, cur.lastrowid)

    session[csrf_key] = secrets.token_hex(24)
    return page(
        sent=True,
        student_id=identifier,
        selected_room=room,
        selected_action=action,
        message=(
            '開錠指令を登録しました。装置の応答をお待ちください。'
            if instant
            else '申請を受け付けました。教員の承認をお待ちください。'
        )
    )[0]
@app.route("/guest/student_submit", methods=["GET", "POST"])
def guest_student_submit():
    # Public submission must NOT log out an Administrator or another account.
    return student_submit(guest_mode=True)

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

DEPARTMENTS = (
    'こども未来学科', '医療・ビジネス学科', '建築環境学科',
    '自動車整備工学科', 'ITデジタル学科'
)
SCHOOL_CLASSES = ('1TA', '1TB', '1TE', '2TA', '2TB', '2TE', '3TA', '3TB', '3TE')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        session['register_csrf'] = secrets.token_hex(24)
        return render_template('register.html', csrf=session['register_csrf'],
                               departments=DEPARTMENTS, classes=SCHOOL_CLASSES)
    if not session.get('register_csrf') or not hmac.compare_digest(request.form.get('csrf', ''), session['register_csrf']):
        return '認証エラー', 403
    student_id = request.form.get('student_id', '').strip()
    username = request.form.get('username', '').strip()
    name = request.form.get('name', '').strip()
    department = request.form.get('department', '').strip()
    school_class = request.form.get('school_class', '').strip()
    course = request.form.get('course', '').strip()
    number_raw = request.form.get('number', '').strip()
    phone = request.form.get('phone', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    def invalid(message):
        values = {k: request.form.get(k, '') for k in ('student_id','username','name','department','school_class','course','number','phone','email')}
        return render_template('register.html', error=message, csrf=session['register_csrf'],
                               departments=DEPARTMENTS, classes=SCHOOL_CLASSES, values=values), 400
    if not re.fullmatch(r'[0-9A-Za-z-]{3,30}', student_id):
        return invalid('学籍番号を正しく入力してください。')
    if not (3 <= len(username) <= 64) or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in username):
        return invalid('ユーザー名は空白を含まない3～64文字で入力してください。')
    if not (1 <= len(name) <= 100):
        return invalid('名前を入力してください。')
    if department not in DEPARTMENTS or school_class not in SCHOOL_CLASSES:
        return invalid('学科とクラスを選択してください。')
    if not 1 <= len(course) <= 100 or any(ord(ch) < 32 for ch in course):
        return invalid('コースを入力してください（100文字以内）。')
    if not re.fullmatch(r'[0-9]{1,2}', number_raw) or not 1 <= int(number_raw) <= 99:
        return invalid('出席番号は1～99の数字で入力してください。')
    number = int(number_raw)
    if not re.fullmatch(r'[0-9-]{10,15}', phone) or len(phone.replace('-', '')) not in (10,11):
        return invalid('電話番号は10～11桁の数字で入力してください。')
    if len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        return invalid('メールアドレスの形式をご確認ください。')
    if not 8 <= len(password) <= 15:
        return invalid('パスワードは8～15文字にしてください。')
    with sqlite3.connect(app.config['DATABASE'], timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        claimed = conn.execute('SELECT 1 FROM managers WHERE student_id=? OR username=? OR lower(email)=?',
                               (student_id, username, email)).fetchone()
        if claimed:
            return invalid('学籍番号、ユーザー名、またはメールアドレスは既に登録されています。')
        try:
            conn.execute("""INSERT INTO managers
                (username,password,name,email,phone,department,school_class,course,number,role,status,student_id)
                VALUES (?,?,?,?,?,?,?,?,?,'Student','承認待ち',?)""",
                (username, generate_password_hash(password), name, email, phone,
                 department, school_class, course, number, student_id))
        except sqlite3.IntegrityError:
            return invalid('既に登録されている情報があります。')
    session.pop('register_csrf', None)
    return render_template('registration_pending.html')

@app.route('/admin/student-approvals', methods=['GET', 'POST'])
def student_approvals():
    if not session.get('logged_in') or not session.get('otp_verified') or session.get('role') not in {'Administrator', 'Admin', '管理者', '教員', 'Teacher'}:
        return 'アクセス権限がありません。', 403
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(24)
    error = None
    if request.method == 'POST':
        if not hmac.compare_digest(request.form.get('csrf', ''), session['csrf']):
            return '認証エラー', 403
        manager_id = request.form.get('manager_id', type=int)
        action = request.form.get('action', '')
        if not manager_id or action not in ('approve','reject'):
            return '入力内容が不正です。', 400
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            user = conn.execute("SELECT * FROM managers WHERE id=? AND role='Student' AND status='承認待ち'", (manager_id,)).fetchone()
            if not user:
                error = '対象の申請が見つかりません。'
            elif action == 'approve':
                existing = conn.execute('SELECT 1 FROM students WHERE student_id=?', (user['student_id'],)).fetchone()
                if existing:
                    error = '学籍番号が既に学生台帳にあります。管理者が確認してください。'
                else:
                    conn.execute('INSERT INTO students(student_id,name,department,course,class,number) VALUES(?,?,?,?,?,?)',
                                 (user['student_id'],user['name'],user['department'],user['course'],user['school_class'],user['number']))
                    conn.execute("UPDATE managers SET status='有効' WHERE id=?", (manager_id,))
            else:
                conn.execute("UPDATE managers SET status='却下' WHERE id=?", (manager_id,))
        if not error:
            return redirect(url_for('student_approvals'))
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.row_factory = sqlite3.Row
        pending = conn.execute("""SELECT id,student_id,username,name,department,school_class,phone,email
            FROM managers WHERE role='Student' AND status='承認待ち' ORDER BY id""").fetchall()
    return render_template('student_approvals.html', pending=pending, csrf=session['csrf'], error=error)

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
            COALESCE(NULLIF(r.guest_name, ''), s.name) AS name, s.department, s.course, s.class, s.number,
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

    # Match an active student account without multiplying request rows.
    request_details_sql = """
        SELECT
            r.id,
            r.student_id,
            r.key,
            r.action,
            r.status,
            r.time,
            r.source,
            r.execution_status,
            COALESCE(
                NULLIF(r.guest_name, ''),
                NULLIF(s.name, ''),
                NULLIF(m.name, ''),
                '未登録'
            ) AS name,
            COALESCE(NULLIF(s.department, ''), NULLIF(m.department, ''), '-') AS department,
            COALESCE(NULLIF(s.course, ''), NULLIF(m.course, ''), '-') AS course,
            COALESCE(NULLIF(s.class, ''), NULLIF(m.school_class, ''), '-') AS class,
            COALESCE(CAST(s.number AS TEXT), CAST(m.number AS TEXT), '-') AS number
        FROM requests r
        LEFT JOIN students s ON r.student_id = s.student_id
        LEFT JOIN managers m ON m.id = (
            SELECT MIN(m2.id)
            FROM managers m2
            WHERE m2.student_id = r.student_id
              AND m2.role = 'Student'
              AND m2.status = '有効'
        )
    """
    cur.execute(
        request_details_sql + " WHERE r.status = ? ORDER BY r.time DESC, r.id DESC",
        ('申請中',),
    )
    pending_rows = cur.fetchall()

    cur.execute(
        request_details_sql + " WHERE r.status != ? ORDER BY r.time DESC, r.id DESC",
        ('申請中',),
    )
    done_rows = cur.fetchall()

    device_status = read_device_status(conn)
    conn.close()
    device_online = all(v['online'] for v in device_status.values())
    last_seen = ', '.join(f"{key}: {value['last_seen'] or '記録なし'}" for key, value in device_status.items())

    pending = [dict(row) for row in pending_rows]
    done = [dict(row) for row in done_rows]

    import secrets
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(24)
    return render_template("admin.html", pending=pending, done=done, csrf=session['csrf'], device_online=device_online, last_seen=last_seen, device_status=device_status)

@app.get('/admin/api/lock-status')
def lock_status():
    if not session.get('logged_in'):
        return {'error': 'unauthorized'}, 401
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""SELECT id, status, execution_status, executed_at
            FROM requests ORDER BY id DESC LIMIT 100""").fetchall()
        device_status = read_device_status(conn)
    return {'online': all(v['online'] for v in device_status.values()),
            'devices': device_status, 'requests': [dict(r) for r in rows]}


def read_device_status(conn):
    result = {}
    for room, device_id in ROOM_DEVICE.items():
        row = conn.execute("""SELECT event_at FROM access_events
            WHERE device_id=? AND event_type='heartbeat' ORDER BY id DESC LIMIT 1""",
            (device_id,)).fetchone()
        seen = row['event_at'] if row else None
        try:
            online = bool(seen and (datetime.now() - datetime.strptime(
                seen, '%Y-%m-%d %H:%M:%S')).total_seconds() < 90)
        except ValueError:
            online = False
        result[device_id] = {'room': room, 'online': online, 'last_seen': seen}
    return result

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

