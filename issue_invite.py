"""Run locally by trusted school admin only. Generates enrollment invite for an existing, verified roster student."""
import sys,sqlite3,time,secrets,hmac,hashlib,os
from pathlib import Path
if len(sys.argv)!=2:
    sys.exit('Usage: python issue_invite.py STUDENT_ID')
secret=os.environ.get('TIST_FLASK_SECRET','')
if len(secret)<32:
    sys.exit('Please set TIST_FLASK_SECRET (32+ random chars) first')
student_id=sys.argv[1]
token=secrets.token_urlsafe(24)
hash_=hmac.new(secret.encode(),('invite:'+token).encode(),hashlib.sha256).hexdigest()
with sqlite3.connect(Path(__file__).with_name('app.db')) as con:
    if not con.execute('SELECT 1 FROM students WHERE student_id=?',(student_id,)).fetchone():
        sys.exit('Student not in the school-approved roster. Do not create public enrollment records.')
    if not con.execute("SELECT 1 FROM managers WHERE student_id=? AND role='Student' AND status IN ('有効','メール未確認')",(student_id,)).fetchone():
        sys.exit('Student account is not registered yet')
    con.execute('INSERT OR REPLACE INTO enrollment_invites(student_id,token_hash,expires_at,used_at) VALUES(?,?,?,NULL)',(student_id,hash_,int(time.time())+300))
print('Student ID:',student_id)
print('ONE-TIME invitation (expires in 5 minutes):',token)
print('Give securely to the verified student; never publish this token.')
