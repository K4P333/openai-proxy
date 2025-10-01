# server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import sqlite3, os, datetime, json, requests

import os

load_dotenv()  # Carga las variables del archivo .env


# LEER la clave desde variable de entorno (NUNCA en el código)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY no está definida en las variables de entorno")

# Se usa un secreto admin para crear/gestionar usuarios (define esto en Render)
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change_this_admin_secret")

DB_PATH = "usage.db"
app = FastAPI(title="OpenAI Proxy - simple")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT,
                    user_id TEXT,
                    prompt TEXT,
                    response TEXT,
                    usage TEXT
                )""")
    # usuario de ejemplo (puedes cambiarlo desde admin endpoint)
    c.execute("INSERT OR IGNORE INTO users (user_id, token) VALUES (?,?)", ("nacho", "clave_usuario123"))
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_db()

class AskRequest(BaseModel):
    user_id: str
    token: str
    image: str  # base64

class CreateUser(BaseModel):
    admin_secret: str
    user_id: str
    token: str

@app.post("/admin/create_user")
def create_user(req: CreateUser):
    if req.admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Admin secret inválido")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, token) VALUES (?,?)", (req.user_id, req.token))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/ask")
def ask(req: AskRequest):
    # Validar user/token
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT token FROM users WHERE user_id = ?", (req.user_id,))
    row = c.fetchone()
    if not row or row[0] != req.token:
        conn.close()
        raise HTTPException(status_code=401, detail="Token inválido")

    ts = datetime.datetime.utcnow().isoformat()
    c.execute("INSERT INTO logs (ts, user_id, prompt) VALUES (?,?,?)", (ts, req.user_id, "[screenshot]"))
    log_id = c.lastrowid
    conn.commit()

    # Preparar petición a OpenAI (ejemplo con data URL en el mensaje)
    payload = {
        "model": "gpt-4o",   # si no tienes acceso, cambia a "gpt-3.5-turbo"
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Responde solo con la respuesta a la pregunta en la imagen. No expliques."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{req.image}"}}
                ]
            }
        ],
        "max_tokens": 300
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        r = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        result = r.json()
        # extraer texto si está donde esperamos
        answer = ""
        try:
            answer = result["choices"][0]["message"]["content"]
        except Exception:
            answer = json.dumps(result)  # fallback
        usage = result.get("usage")
    except Exception as e:
        c.execute("UPDATE logs SET response = ? WHERE id = ?", (f"ERROR: {e}", log_id))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

    c.execute("UPDATE logs SET response = ?, usage = ? WHERE id = ?", (answer, json.dumps(usage), log_id))
    conn.commit()
    conn.close()
    return {"answer": answer}
