TIST 鍵管理システム — Gmail SMTP + password + email OTP
======================================================
VI: HUONG DAN CAI DAT (giao dien web van 100% tieng Nhat)

1) SAO LUU project C:\Users\phat5019\key, dac biet app.db.
   KHONG thay the app.db hien tai bang DB moi. File ZIP nay KHONG co database.
2) Copy app.py vao thu muc key; copy templates/*.html vao key/templates/.
   rfid_api.py trong ZIP la ban tham chieu tu file da gui. Neu ban da sua
   rfid_api.py sau do thi GIU FILE HIEN TAI (giao thuc device khong thay doi).
   Copy issue_invite.py vao thu muc key.
3) Tren tai khoan Google dung de gui email: bat 2-Step Verification,
   tao App Password trong Google Account > Security > App passwords.
   Co the tai khoan Google khong cho tao App Password (vi du Workspace policy).
   KHONG dung mat khau Gmail thong thuong.
4) Mo PowerShell trong key, chay (THAY GIA TRI VI DU):
   $env:TIST_FLASK_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(48))")
   $env:TIST_SMTP_EMAIL = 'sender@gmail.com'
   $env:TIST_SMTP_APP_PASSWORD = 'YOUR_16_CHAR_APP_PASSWORD'
   $env:TIST_DEVICE_TOKEN = 'YOUR_EXISTING_ESP32_TOKEN'
   python app.py
   QUAN TRONG: Dung CHINH TIST_FLASK_SECRET on dinh giua cac lan khoi dong.
   KHONG doi secret khi dang co OTP/moi dang ky chua hoan tat; luu secret
   trong kho bi mat an toan, khong luu vao Git.
   PowerShell variables chi ap dung trong cua so hien tai.
   Neu su dung HTTPS sau proxy, set TIST_HTTPS=1 va dung HTTPS that.
5) ADMIN CU: Phai bo sung EMAIL THUC cua tai khoan Admin.
   Trong PowerShell tai project:
   python -c "import sqlite3; c=sqlite3.connect('app.db'); c.execute('UPDATE managers SET email=? WHERE username=?',('your_admin_mail@example.com','Admin')); c.commit(); c.close()"
   Thay email minh hoa bang email ban quan ly. Mat khau Admin KHONG thay doi.
6) HOC SINH (MA MOI TAI LOGIN):
   - Nha truong doi chieu danh sach hoc sinh truoc khi cap tai khoan/quyen truy cap.
   - Hoc sinh nhap STUDENT_ID, username, email, password 8-15 ky tu tai /register; KHONG can ma moi.
   - Xac minh Email OTP 6 so de hoan tat dang ky. Buoc nay chi xac minh quyen truy cap email,
     CHUA tu dong xac minh nguoi dang ky la chu thuc su cua STUDENT_ID.
   - Nhan vien truong xac minh danh tinh truoc khi phat ma dang nhap:
       python issue_invite.py STUDENT_ID
   - Hoc sinh dang nhap bang username + password + invite (5 phut), sau do Email OTP.
   - Invite chi duoc danh dau da dung SAU KHI OTP dung; neu invite het han truoc luc xac minh OTP,
     hoc sinh phai xin invite moi. Moi lan dang nhap can invite moi.
   - Admin khong can invite, nhung van can password + Email OTP.
   - Truoc khi trien khai thuc te, can co bien phap ngan nguoi ngoai 'chiem' STUDENT_ID khi dang ky,
     vi chi tra ma OTP ve email do nguoi dang ky nhap khong chung minh ho la hoc sinh do.
7) TEST:
   - Dung tai khoan Admin da co email, login -> kiem tra hop thu/spam -> OTP.
   - Hoc sinh dang ky -> OTP email -> nhan vien xac minh va cap invite -> dang nhap -> OTP.
   - Test admin approve -> ESP32 receives command; khong can nap lai firmware.

AN TOAN:
- DUNG HTTPS truoc khi su dung thuc te (khong su dung HTTP cho password/OTP).
- Co rate limit theo IP / account o reverse proxy; SMTP quota / abuse monitoring.
- Roster, invite va email OTP khong tu dong chung minh hoc sinh con dang hoc;
  can thu hoi tai khoan khi hoc sinh ra truong, ghi log va phan quyen tung phong.
- RFID UID-only va HTTP device API la he thong demo, KHONG su dung cho cua that.
- Neu thay doi rfid_api.py trong du an sau khi upload, kiem tra xung dot truoc
  khi copy, vi goi nay giu nguyen ban cung cap chu khong sua file do.

UPDATED FLOW (2026-10-14): Student registers WITHOUT invitation; password 8-15 characters. After email confirmation, school issues a 5-minute invite using issue_invite.py STUDENT_ID. Student must enter invitation on LOGIN along with username/password, and then the emailed OTP. Admin accounts do not require invitation. Invitation is consumed after successful login OTP. A NEW school invitation is needed for each new student login. IMPORTANT: Email verification alone does not establish real-world student identity. Verify the school roster, issue invitations only after in-person or equivalent verification, protect registrations against account pre-claiming, and use HTTPS before real deployment.

【新規登録の変更】
登録するボタンで「メール未確認」の学生アカウントを作成します。
学生は学校で本人確認して5分間の招待コードを受け取り、初回ログインでOTPをメール受信し認証します。認証成功時のみ「有効」になります。
メール未確認の登録が他者に占有されることを防ぐため、実運用では学校による本人確認・事前発行またはアカウント解除の仕組みが必要です。
