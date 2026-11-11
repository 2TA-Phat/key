CAP NHAT TRANG 管理者検索 - Import/Export
========================================
1) Sao luu thu muc key va app.db dang dung truoc khi thay file.
2) Giai nen goi cap nhat; sao chep app.py, templates/managers.html,
   templates/manager_detail.html va templates/manager_edit.html vao du an hien tai.
3) KHONG ghi de app.db dang su dung. Goi cap nhat khong chua database,
   secrets hoac .git; giu nguyen cac cau hinh va thong tin dang nhap cu.
4) Khoi dong lai Flask, dang nhap vai tro Administrator va vao:
   http://172.16.9.15:5000/admin/managers
5) Bang hien thi them: 学籍番号 / 学科 / コース / クラス / 出席番号.
6) Export Excel / Export CSV: tai file danh sach tai khoan, KHONG co mat khau.
7) Import: tai file Excel .xlsx hoac CSV (UTF-8), su dung cot theo file Export.
   - Cap nhat tai khoan Student trung username, khong doi mat khau, role, trang thai.
   - Them Student moi o trang thai 無効; quan tri vien phai xac minh thong tin,
     cap mat khau va kich hoat truoc khi cho phep dang nhap.
   - Tai khoan Administrator/Operator khong duoc sua qua Import.
   - Gioi han 2000 dong, 2MB; 1 loi se huy toan bo thay doi cua lan Import.
8) Gia tri 学籍番号 duoc giu duoi dang van ban; neu so co so 0 dau,
   can dat cot do thanh Text trong Excel TRUOC khi nhap/luu file.
9) Chay kiem tra ung dung va sao luu DB truoc khi dung voi du lieu that.
