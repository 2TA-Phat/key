
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).resolve().parent
CLIENT_FILE = BASE_DIR / "secrets" / "gmail_client.json"
TOKEN_FILE = BASE_DIR / "secrets" / "gmail_token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

if not CLIENT_FILE.is_file():
    raise FileNotFoundError(
        f"Không tìm thấy file: {CLIENT_FILE}"
    )

flow = InstalledAppFlow.from_client_secrets_file(
    str(CLIENT_FILE),
    scopes=SCOPES
)

credentials = flow.run_local_server(
    port=0,
    prompt="consent",
    access_type="offline"
)

if not credentials.valid:
    raise RuntimeError("Xác thực Gmail thất bại.")

TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
TOKEN_FILE.write_text(
    credentials.to_json(),
    encoding="utf-8"
)

print("=" * 45)
print("GMAIL API AUTHORIZATION SUCCESS!")
print("Scope:", ", ".join(credentials.scopes or []))
print("Token saved:", TOKEN_FILE)
print("=" * 45)
