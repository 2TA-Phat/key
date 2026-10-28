TIST-SmartLock: bản cập nhật giao diện student_submit

SAO LƯU toàn bộ dự án hiện tại trước khi ghi đè.

1. Giải nén ZIP tại C:\Users\phat5019\key và ghi đè ĐÚNG 2 file:
   - app.py
   - templates\student.html
2. KHÔNG thay đổi app.db, secrets, rfid_api.py, tab_sessions.py, ESP32.
3. Khởi động lại Flask; init_db() tự thêm cột requests.reason nếu chưa có.
4. Mở /student_submit. Đăng nhập kiểm tra tự điền hồ sơ, trạng thái cửa và lý do chọn.
5. Nếu trong profile thiếu số điện thoại hoặc khoa/lớp, kiểm tra bản ghi managers tương ứng.

Ghi chú:
- Gói nguồn hiện tại chỉ cấu hình phòng 1TA, 2TA, 2TB; chưa có 3TE.
- Trạng thái khóa lấy từ lệnh được ESP32 báo 'issued', KHÔNG phải xác nhận cảm biến khóa vật lý.
- Online/offline tính từ heartbeat, ngưỡng 90 giây theo app.py hiện tại.
- API /api/door-status chỉ cung cấp trạng thái thiết bị, không chứa dữ liệu học sinh.
- Sau khi cập nhật, lý do lưu ở requests.reason; giao diện quản trị cũ chưa thêm cột hiển thị lý do.
- Không sử dụng ZIP này làm bản đầy đủ để thay thế các file khác trong dự án.

TIST OTP SESSION FIX - 2026-10-28

1. Backup your existing key folder and app.db.
2. Copy app.py and tab_sessions.py into C:\Users\phat5019\key\
3. Copy tab_session.js into C:\Users\phat5019\key\ (same directory as app.py). This is REQUIRED for the new bootstrap URL.
4. Keep your existing templates/, static/, rfid_api.py, secrets/ and app.db unchanged.
5. Restart Flask in the terminal with its normal environment variables set.
6. Open /login in a normal browser tab (not private mode), hard refresh Ctrl+F5.
7. Check URL has ?_tab=<32 hex digits> BEFORE submitting credentials.
8. Check /_tist/tab-session.js returns JavaScript (HTTP 200).
9. Log in, enter the 6-digit OTP on /verify-otp.

Changes:
- Forces tab bootstrap on the login and OTP HTML screens.
- Refuses email sending from unidentified tabs.
- Allows reuse of still-valid OTP after re-entering password; no 60s resend needed.
- Keeps Administrator password-only login and existing other session behavior.

Do NOT share any credentials or commit secrets/. The supplied tab_sessions.py is identical to uploaded file.

