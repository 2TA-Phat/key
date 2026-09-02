import sqlite3
from flask import Flask, request, redirect, render_template, session, url_for
from datetime import datetime

app = Flask(__name__)
app.secret_key = "super_secret_key"

# Cấu hình Mặc định Tài khoản & Mật khẩu Admin
ADMIN_USER = "admin"
ADMIN_PASS = "123456"

# --- DB 初期化 ---
def init_db():
    conn = sqlite3.connect("app.db")
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
            username TEXT UNIQUE,
            name TEXT,
            email TEXT,
            role TEXT,
            status TEXT
        )
    """)

    # Thêm dữ liệu mẫu cho Managers nếu bảng còn trống
    cur.execute("SELECT COUNT(*) FROM managers")
    if cur.fetchone()[0] == 0:
        cur.executemany("""
            INSERT INTO managers (id, username, name, email, role, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            (1, "dtmp1", "管理者", "dtmp1@dtmp.jp", "Administrator", "有効"),
            (2, "dtmp2", "オペレーター", "2dtmp1@dtmp.jp", "Operator", "有効")
        ])

    conn.commit()
    conn.close()

init_db()

# --- XL ĐĂNG NHẬP / ĐĂNG XUẤT ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["logged_in"] = True
            return redirect("/admin")
        else:
            return render_template("login.html", error="ユーザー名またはパスワードが違います")
            
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

    conn = sqlite3.connect("app.db")
    cur = conn.cursor()

    cur.execute("SELECT * FROM students WHERE student_id=?", (student_id,))
    student = cur.fetchone()

    if not student:
        conn.close()
        return render_template("student.html", error="学籍番号が登録されていません")

    cur.execute("""
        INSERT INTO requests (student_id, key, action, status, time)
        VALUES (?, ?, ?, '申請中', ?)
    """, (student_id, key, action, now))

    conn.commit()
    conn.close()

    return render_template("student.html", sent=True)

@app.route("/status", methods=["POST"])
def status():
    student_id = request.form.get("student_id")

    conn = sqlite3.connect("app.db")
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

    conn = sqlite3.connect("app.db")
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

    conn = sqlite3.connect("app.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            s.student_id AS contact_id,
            s.name,
            s.department,
            s.course,
            s.class,
            s.number,
            MIN(r.time) AS first_login,
            MAX(r.time) AS last_login,
            SUM(CASE WHEN r.status = '申請中' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN r.status IN ('承認', '却下') THEN 1 ELSE 0 END) AS done_count
        FROM students s
        LEFT JOIN requests r ON s.student_id = r.student_id
        GROUP BY s.student_id
        ORDER BY last_login DESC
    """)
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

    conn = sqlite3.connect("app.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT r.id, r.student_id, r.key, r.action, r.status, r.time,
               s.name, s.department, s.course, s.class, s.number
        FROM requests r
        LEFT JOIN students s ON r.student_id = s.student_id
        WHERE r.status='申請中'
        ORDER BY r.time DESC
    """)
    pending_rows = cur.fetchall()

    cur.execute("""
        SELECT r.id, r.student_id, r.key, r.action, r.status, r.time,
               s.name, s.department, s.course, s.class, s.number
        FROM requests r
        LEFT JOIN students s ON r.student_id = s.student_id
        WHERE r.status!='申請中'
        ORDER BY r.time DESC
    """)
    done_rows = cur.fetchall()

    conn.close()

    pending = [dict(row) for row in pending_rows]
    done = [dict(row) for row in done_rows]

    return render_template("admin.html", pending=pending, done=done)

# --- 管理者一覧画面 (MỚI BỔ SUNG) ---
@app.route("/admin/managers")
def admin_managers():
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect("app.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM managers ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()

    managers = [dict(row) for row in rows]
    return render_template("managers.html", managers=managers)

# --- 承認・却下・削除 ---
@app.route("/approve/<int:req_id>")
def approve(req_id):
    if not session.get("logged_in"):
        return redirect("/login")
    conn = sqlite3.connect("app.db")
    cur = conn.cursor()
    cur.execute("UPDATE requests SET status='承認' WHERE id=?", (req_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/reject/<int:req_id>")
def reject(req_id):
    if not session.get("logged_in"):
        return redirect("/login")
    conn = sqlite3.connect("app.db")
    cur = conn.cursor()
    cur.execute("UPDATE requests SET status='却下' WHERE id=?", (req_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/delete/<int:req_id>")
def delete(req_id):
    if not session.get("logged_in"):
        return redirect("/login")
    conn = sqlite3.connect("app.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM requests WHERE id=?", (req_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

# --- 起動 ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)