TIST 3 ESP32 LAB TEST - Fixed per-device tokens (2026-10-21)

Mappings: ESP32_01 => 1TA; ESP32_02 => 2TA; ESP32_03 => 2TB.

1) Backup C:\Users\phat5019\key\rfid_api.py and DB first.
2) Replace project rfid_api.py with rfid_api.py in this ZIP. (app.py unchanged.)
3) Copy tist_device_tokens.ps1 to C:\Users\phat5019\key\ (or private location OUTSIDE Git).
4) Open PowerShell in the PROJECT directory:
   cd C:\Users\phat5019\key
   . .\tist_device_tokens.ps1
   python app.py
   Dot + space is important: it loads fixed tokens into same PowerShell process.
   Do not start Flask from another terminal lacking those variables.
   If TIST_FLASK_SECRET was already configured, retain it; do not replace it.
5) Upload each .ino to its matching ESP32 through Arduino IDE.
6) Check GET /api/device/commands no longer gives HTTP 401.
   Expect HTTP 200 if authentication succeeds, even without a pending command.
7) Keep ESP32 tokens and tist_device_tokens.ps1 SECRET. Do not push to GitHub.
   Add tist_device_tokens.ps1 to .gitignore. Note that Git tracks files already added.
8) WARNING: This is local LAB DEMONSTRATION ONLY. HTTP on Wi-Fi exposes credentials; UID-only RC522 can be cloned. Never use to secure real doors.
9) If server computer IP changes, update SERVER constant in ALL .ino sketches.
10) ESP32_03 support requires this updated rfid_api.py and restart of Flask.

Existing app.py, students, requests, Web UI, OTP and DB are not overwritten by this package.
