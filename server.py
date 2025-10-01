# server.py
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from dotenv import load_dotenv
import os, sqlite3, datetime, jwt, hashlib, json, requests

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET", "zPY0dzNJrAsZgXc10YsQfoRyqix7UdwwYYPZktDBCwjFc2WC42HNZ1CiI7h-rII7")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY no definida en env")

DB = "licenses.db"
app = FastAPI(title="Simple License Backend")

# DB init
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS licenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    license_key TEXT UNIQUE,
                    buyer TEXT,
                    max_devices INTEGER DEFAULT 1,
                    created_at TEXT,
                    status TEXT DEFAULT 'active'
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    license_key TEXT,
                    device_id TEXT,
                    token TEXT,
                    activated_at TEXT,
                    last_seen TEXT,
                    revoked INTEGER DEFAULT 0
                )""")
    conn.commit()
    conn.close()

init_db()

# Helpers
def gen_license_key():
    s = hashlib.sha256(os.urandom(32)).hexdigest()[:20]
    return s

def create_device_jwt(license_key, device_id, days=365):
    now = datetime.datetime.utcnow()
    payload = {
        "license_key": license_key,
        "device_id": device_id,
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(days=days)).timestamp())
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_device_jwt(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None

# API models
class CreateLicenseReq(BaseModel):
    buyer: str
    max_devices: int = 1

class ActivateReq(BaseModel):
    license_key: str
    device_id: str

class AskReq(BaseModel):
    base64_image: str

# Admin endpoint (crea licencia rapidamente)
@app.post("/admin/create_license")
def create_license(req: CreateLicenseReq):
    key = gen_license_key()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO licenses (license_key,buyer,max_devices,created_at) VALUES (?,?,?,?)",
              (key, req.buyer, req.max_devices, datetime.datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return {"license_key": key}

# Activación: cliente envía license_key + device_id -> server emite device_token
@app.post("/activate")
def activate(req: ActivateReq):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT license_key, max_devices, status FROM licenses WHERE license_key = ?", (req.license_key,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="License not found")
    if row[2] != "active":
        conn.close()
        raise HTTPException(status_code=403, detail="License not active")

    # comprobar número de dispositivos activos
    c.execute("SELECT COUNT(*) FROM devices WHERE license_key = ? AND revoked = 0", (req.license_key,))
    count = c.fetchone()[0]
    if count >= row[1]:
        conn.close()
        raise HTTPException(status_code=403, detail="Max devices activated for this license")

    token = create_device_jwt(req.license_key, req.device_id)
    now = datetime.datetime.utcnow().isoformat()
    c.execute("INSERT INTO devices (license_key, device_id, token, activated_at, last_seen) VALUES (?,?,?,?,?)",
              (req.license_key, req.device_id, token, now, now))
    conn.commit()
    conn.close()
    return {"device_token": token}

# Endpoint principal: recibir imagen, validar token y llamar a OpenAI
@app.post("/ask")
def ask(req_body: AskReq, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split()[1]
    data = decode_device_jwt(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    license_key = data.get("license_key")
    device_id = data.get("device_id")

    # comprobar en DB device no revocado
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, revoked FROM devices WHERE license_key = ? AND device_id = ? AND token = ?",
              (license_key, device_id, token))
    row = c.fetchone()
    if not row or row[1] == 1:
        conn.close()
        raise HTTPException(status_code=403, detail="Device not authorized")

    # actualizar last_seen
    c.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (datetime.datetime.utcnow().isoformat(), row[0]))
    conn.commit()
    conn.close()

    # Llamar a OpenAI (modelo que soporte imagenes)
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type":"application/json"}
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role":"user", "content":[
                {"type":"text", "text":"Responde solo con la respuesta a la pregunta en la imagen. No expliques."},
                {"type":"image_url", "image_url": {"url": f"data:image/png;base64,{req_body.base64_image}"}}
            ]}
        ],
        "max_tokens": 200
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {r.text}")
    answer = r.json()["choices"][0]["message"]["content"]
    return {"answer": answer}
