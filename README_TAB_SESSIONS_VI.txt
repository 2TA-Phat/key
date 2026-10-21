TIST - PHIEN DANG NHAP DOC LAP CHO TUNG TAB (DEMO)

1) Sao luu du an va app.db truoc khi thay doi.
2) Giai nen noi dung ZIP vao thu muc key hien tai, giu nguyen app.db va secrets.
3) Khong doi TIST_FLASK_SECRET dang su dung; mo PowerShell moi va nap lai bien moi truong neu can.
4) Chay: python app.py
5) Dong cac tab TIST cu. Mo 2 tab moi bang cach go dia chi http://172.16.9.15:5000/ vao tung tab (khong Duplicate tab).
6) Tab 1 login Administrator; Tab 2 login Student (OTP email).
7) Kiem tra refresh, logout tung tab, va gui yeu cau guest.

Admin: 3 gio tinh tu khi dang nhap thanh cong (co dinh, F5 khong gia han).
Student va cac vai tro khac: 5 phut tu khi dang nhap thanh cong.
Ma OTP: 5 phut.

Moi tab duoc phan biet bang ma _tab (32 ky tu hexa) tren URL va request form.
Ma _tab CHI la ma chon phien, khong phai token bao mat; Flask xac thuc
bang cookie trinh duyet duoc ky va ban ghi session trong SQLite.
SQLite tu them bang browser_tab_sessions vao app.db; khong xoa du lieu cu.
Khi nhan Logout, chi session cua tab hien tai bi xoa.
Tai khoan Admin va Student cua hai tab co the cung ton tai trong mot profile Edge.

HAN CHE: Day la demo noi bo, khong bao ve khoi nguoi khac cung su dung
cung mot profile browser; nguoi nay co the mo URL tab cua phien khac.
Trinh duyet bat buoc bat JavaScript va cho phep cookie.
Khong su dung HTTP / RFID UID-only de bao ve cua thuc te.

File thay doi: app.py, tab_sessions.py, static/js/tab_session.js,
17 templates/*.html (chi chen script, khong doi giao dien).
File rfid_api.py giu nguyen, code ESP32 giu nguyen.

Luu y: ban ZIP goc co .git, app.db va Gmail OAuth secrets. Goi ZIP
ket qua co y loai bo .git, app.db, secrets va cac khoa bi mat.
Neu da chia se ZIP ngoai pham vi tin cay, can thu hoi/doi Gmail OAuth token.
