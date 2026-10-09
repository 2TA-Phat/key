// LAB DEMO ONLY — Do not deploy UID-only RC522 at real doors.
// Libraries: ArduinoJson v7, MFRC522, ESP32Servo. ESP32 Arduino core.
#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";
const char* SERVER = "http://192.168.1.100:5000";  // PC LAN IPv4
const char* DEVICE_TOKEN = "PASTE_LONG_RANDOM_DEVICE_TOKEN";
const char* DEVICE_ID = "esp32-01";
const char* ROOMS[] = {"1TA", "2TA", "2TB", "3TE"};
const int SERVO_PINS[] = {13, 14, 25, 26};
constexpr int RFID_SS = 21, RFID_RST = 22;
constexpr int ROOM_BUTTON = 32;
constexpr int LOCK_ANGLE = 0, UNLOCK_ANGLE = 120;
MFRC522 reader(RFID_SS, RFID_RST);
Servo servo[4];
int selectedRoom = 0;
unsigned long lastPoll = 0, lastButton = 0, lastScan = 0, lastHeartbeat = 0;
String previousUID;
// Record recent IDs in RAM to prevent re-execution if repeated unexpectedly.
int recentIds[20] = {0};
size_t recentPos = 0;

bool httpJson(const String& path, const String& payload, bool get, JsonDocument& response, int& code) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.setTimeout(2500);
  http.begin(String(SERVER) + path);
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  http.addHeader("X-Device-ID", DEVICE_ID);
  if (!get) http.addHeader("Content-Type", "application/json");
  code = get ? http.GET() : http.POST(payload);
  if (code <= 0) { http.end(); return false; }
  String body = http.getString();
  http.end();
  return deserializeJson(response, body) == DeserializationError::Ok;
}

String uidString() {
  String s;
  for (byte i = 0; i < reader.uid.size; i++) {
    if (reader.uid.uidByte[i] < 16) s += "0";
    s += String(reader.uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

bool recentlyExecuted(int id) {
  for (int x : recentIds) if (id == x) return true;
  return false;
}

void sendResult(int commandId, const char* result) {
  JsonDocument doc, reply;
  doc["command_id"] = commandId;
  doc["result"] = result;
  String payload;
  serializeJson(doc, payload);
  int status;
  if (!httpJson("/api/device/result", payload, false, reply, status) || status != 200) {
    Serial.println("WARNING: result delivery failed; reconcile server before retrying.");
  }
}

void executeCommand(JsonDocument& instruction) {
  if (!instruction["allowed"].as<bool>()) return;
  int commandId = instruction["command_id"].as<int>();
  String room = instruction["room"].as<String>();
  String action = instruction["action"].as<String>();
  int idx = -1;
  for (int i = 0; i < 4; i++) if (room == ROOMS[i]) idx = i;
  if (idx < 0 || commandId <= 0 || (action != "開ける" && action != "閉める")) {
    if (commandId > 0) sendResult(commandId, "failed");
    return;
  }
  if (recentlyExecuted(commandId)) { sendResult(commandId, "issued"); return; }
  // Prevent accidental repeat within one runtime. After reset, server's one-time delivery is authoritative.
  recentIds[recentPos] = commandId;
  recentPos = (recentPos + 1) % 20;
  servo[idx].write(action == "開ける" ? UNLOCK_ANGLE : LOCK_ANGLE);
  delay(700);
  Serial.printf("Room %s, action %s, command %d\n", room.c_str(), action.c_str(), commandId);
  sendResult(commandId, "issued"); // Issued to servo, NOT sensor-confirmed physical unlock.
}

void scanRFID() {
  String uid = uidString();
  if (uid == previousUID && millis() - lastScan < 3500) return;
  previousUID = uid;
  lastScan = millis();
  JsonDocument requestData, reply;
  requestData["uid"] = uid;
  requestData["room"] = ROOMS[selectedRoom];
  String payload;
  serializeJson(requestData, payload);
  int status;
  Serial.println("Scan: " + uid + " room: " + ROOMS[selectedRoom]);
  if (!httpJson("/api/rfid/scan", payload, false, reply, status)) {
    Serial.println("Offline: no unlock");
    return;
  }
  if (status == 200 && reply["allowed"].as<bool>()) {
    executeCommand(reply); // Direct card => instant unlock (after server authorization).
  } else if (reply["requires_approval"].as<bool>()) {
    Serial.println("Approval card: request sent. Teacher approval will unlock automatically.");
  } else {
    Serial.println("RFID denied: " + reply["reason"].as<String>());
  }
}

void pollCommands() {
  JsonDocument doc;
  int status;
  if (httpJson("/api/device/commands", "", true, doc, status) && status == 200) {
    if (doc["has_command"].as<bool>()) executeCommand(doc);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(ROOM_BUTTON, INPUT_PULLUP);
  for (int i = 0; i < 4; i++) {
    servo[i].setPeriodHertz(50);
    servo[i].attach(SERVO_PINS[i], 500, 2400);
    servo[i].write(LOCK_ANGLE);
  }
  SPI.begin(18, 19, 23, RFID_SS);
  reader.PCD_Init();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.println("Boot. Selected room: 1TA");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(600);
    return;
  }
  unsigned long now = millis();
  if (now - lastPoll >= 500) { lastPoll = now; pollCommands(); }
  if (now - lastHeartbeat >= 60000) {
    lastHeartbeat = now;
    JsonDocument out;
    int status;
    httpJson("/api/device/heartbeat", "{}", false, out, status);
  }
  if (digitalRead(ROOM_BUTTON) == LOW && now - lastButton > 400) {
    selectedRoom = (selectedRoom + 1) % 4;
    lastButton = now;
    Serial.printf("Selected room: %s\n", ROOMS[selectedRoom]);
  }
  if (reader.PICC_IsNewCardPresent() && reader.PICC_ReadCardSerial()) {
    scanRFID();
    reader.PICC_HaltA();
    reader.PCD_StopCrypto1();
  }
}
