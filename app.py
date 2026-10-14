import sqlite3
import os
import hmac

from flask import Flask, request, redirect, render_template, session, url_for
from rfid_api import rfid_api, initialize, issue_command, ROOMS, ACTIONS
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

app.secret_key = os.environ.get("TIST_FLASK_SECRET", "CHANGE_ME_LOCAL_DEMO_ONLY")
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
    conn.commit()
    conn.close()

init_db()
initialize(app.config["DATABASE"])

# --- XL ĐĂNG NHẬP / ĐĂNG XUẤT ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = sqlite3.connect(app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM managers
            WHERE username = ?
              AND status = '有効'
        """, (username,))

        manager = cur.fetchone()
        conn.close()

        if manager and check_password_hash(manager["password"], password):
            session["logged_in"] = True
            session["manager_id"] = manager["id"]
            session["username"] = manager["username"]
            session["name"] = manager["name"]
            session["role"] = manager["role"]

            return redirect("/admin")

        return render_template(
            "login.html",
            error="ユーザー名またはパスワードが違います"
        )

    return render_template("login.html")
@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/login")

# --- 生徒画面 ---
@app.route("/")
def index():
    return redirect("/student_submit")

@app.route("/student_submit", methods=["GET", "POST"])
def student_submit():
    if request.method == "GET":
        return render_template("student.html")

    student_id = request.form.get("student_id")
    key = request.form.get("key")
    action = request.form.get("action")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(app.config["DATABASE"])
    cur = conn.cursor()

    cur.execute("SELECT * FROM students WHERE student_id=?", (student_id,))
    student = cur.fetchone()

    if not student:
        conn.close()
        return render_template("student.html", error="学籍番号が登録されていません")

    cur.execute("""
        INSERT INTO requests (student_id, key, action, status, time, source)
        VALUES (?, ?, ?, '申請中', ?, 'Web申請')
    """, (student_id, key, action, now))

    conn.commit()
    conn.close()

    return render_template("student.html", sent=True)

@app.route("/status", methods=["POST"])
def status():
    student_id = request.form.get("student_id")

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

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    data = (
        request.form["student_id"],
        request.form["name"],
        request.form["department"],
        request.form["course"],
        request.form["class"],
        request.form["number"]
    )

    conn = sqlite3.connect(app.config["DATABASE"])
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO students (student_id, name, department, course, class, number)
        VALUES (?, ?, ?, ?, ?, ?)
    """, data)

    conn.commit()
    conn.close()

    return "登録完了しました！"

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
@app.route("/admin/managers/<int:manager_id>/delete")
def manager_delete(manager_id):
    if not session.get("logged_in"):
        return redirect("/login")

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

@app.route("/delete/<int:req_id>")
def delete(req_id):
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

