# TIST: ESP32 + Flask + RFID — two card types (LAB DEMO)

## Operation
- Web request -> teacher **承認** -> Flask enqueues a 20-second command -> ESP32 polls `/api/device/commands` every 500ms -> servo moves -> ESP32 reports `issued`.
- `direct` RFID -> Flask validates active card, expiry, authorized room -> responds with servo command immediately; no teacher approval.
- `approval` RFID -> Flask validates card, creates `requests.status='申請中'` -> teacher **承認** -> ESP32 receives command; no additional scan needed.
- Each scan sends a server-side access event. `issued` only means servo command was issued, not that the door physically unlocked.

## Files
`app.py` is based on the prior integration of your Flask app, preserving its student/admin routes. `rfid_api.py` adds the APIs and database tables. `templates/rfid_admin.html` is the admin card management screen. `templates/admin.html` switches approve/reject to POST and adds an RFID management link. `esp32_rfid_lock.ino` is the ESP32 sketch.

## Windows setup
1. **Back up** your real `app.db` first; copy it next to `app.py` (database not bundled because it contains personal data). If your original templates differ, reconcile before deploying.
2. Open PowerShell inside this folder:
   ```powershell
   pip install flask werkzeug
   $env:TIST_FLASK_SECRET='PASTE_A_LONG_RANDOM_SECRET'
   $env:TIST_DEVICE_TOKEN='PASTE_A_DIFFERENT_LONG_RANDOM_SECRET'
   python app.py
   ```
3. Access `http://127.0.0.1:5000/login`, sign in as Administrator, open `/admin/rfid`, and register the UID, student number, one of the `direct`/`approval` modes, expiry (optional), and authorized room(s). The student must exist in `students`.
4. Use Arduino IDE with ESP32 board support, **MFRC522, ArduinoJson v7, ESP32Servo**. In the sketch, set Wi-Fi, your laptop's LAN IPv4 from `ipconfig`, and the same `TIST_DEVICE_TOKEN`. Flash to your board. Laptop and ESP32 must be on the same reachable Wi-Fi/LAN and the Windows firewall must permit inbound port 5000 on the **private** network.
5. Visit the student form `/student_submit` to submit a request. As teacher, approve at `/admin`; no RFID scan necessary. For direct RFID, place the authorized card on the reader. For approval RFID, scan and approve the newly created request.
6. SQLite: inspect `access_events`, `device_commands` and `requests.execution_status`. Commands expire after 20 seconds and delivered commands are not re-delivered after a lost response; investigate uncertain delivery rather than automatically replaying a door-opening action.

## Demo wiring
RC522: SDA/SS GPIO21, RST GPIO22, SCK GPIO18, MISO GPIO19, MOSI GPIO23, VCC **3.3V**, GND GND. Servo signals: 1TA GPIO13, 2TA GPIO14, 2TB GPIO25, 3TE GPIO26. Use an external regulated 5V servo supply sized for stall currents, with common GND. Room switch GPIO32-to-GND (`INPUT_PULLUP`).

## Constraints and security
This is for a **tabletop demonstration**. UID-only RC522 credentials are clonable, HTTP transmits secrets in the clear, and the underlying student registration/admin routes still require security hardening (role authorization, CSRF throughout, input constraints, rate limits). Do not use this on actual occupied school doors. A physical system requires fire-safe egress, manual override, anti-tailgating, cryptographic credentials, TLS or secure MQTT, per-reader trusted room assignment, device-safe command idempotency, command acknowledgment/recovery, a sensor to verify door/lock position, and durable acknowledgement retries. The demo's single RFID reader with a selectable room button is NOT a secure door-to-reader association.
