BẢN SỬA TIST 管理者編集 / EXPORT / IMPORT
=======================================
Thay thế đúng 3 file trong thư mục dự án hiện có:
  app.py
  templates/manager_edit.html
  templates/managers.html

1) Sao lưu app.py, toàn bộ thư mục templates và app.db đang sử dụng.
2) Không thay thế/xóa app.db, secrets, file môi trường hay thông tin cấu hình hiện có.
3) Chép ba file đè vào đúng đường dẫn tương ứng và khởi động lại Flask.
4) Đăng nhập Administrator -> 管理者 -> 編集, kiểm tra 5 trường 学籍番号/学科/コース/クラス/出席番号 có dữ liệu.
5) Export Excel/CSV: 12 cột theo đúng Edit, mật khẩu luôn để trống.
6) Import: hỗ trợ file 12 cột mới và cả file 8 cột cũ. Tài khoản quản trị trong file chỉ được giữ nguyên; thay đổi dữ liệu của họ sẽ báo lỗi. Tài khoản Student hiện có chỉ cập nhật thông tin cá nhân, không đổi mật khẩu/vai trò/trạng thái; Student mới được tạo ở trạng thái 無効.
7) Cột ID phải khớp với username đã có khi cập nhật; Student mới có thể để trống ID. Cột 新しいパスワード phải để trống khi Import.
8) Nếu đã có một số trường chưa được đăng ký trong DB, Edit sẽ để trống (đây là đúng). Nhập rồi Save để lưu.

KIỂM TRA: Python cú pháp OK; kiểm tra file XLSX/XML/ZIP và đọc lại 12 cột thành công.
LƯU Ý: Chưa chạy thử server Flask thực tế vì môi trường kiểm thử không có module Flask.
