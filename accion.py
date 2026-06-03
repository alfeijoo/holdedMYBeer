#!/data/data/com.termux/files/usr/bin/python3
"""
Ejecutado por at scheduler.
Uso: accion.py <ACTION> <ACUM_MIN>
ACTION: ENTRADA | INICIO_PAUSA | FIN_PAUSA | SALIDA
"""

import sys
import os
import json
import base64
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Rutas ─────────────────────────────────────────────────────────────────

HOME    = Path("/data/data/com.termux/files/home")
FICHAJE = HOME / "holdedMYBeer"
LOG_FILE = FICHAJE / "holdmybeer.log"
ADB_KEYS = HOME / ".android" / "adbkey"
ADB_HOST = "127.0.0.1:5555"

os.environ["ADB_VENDOR_KEYS"] = str(ADB_KEYS)
os.environ["PATH"] = "/data/data/com.termux/files/usr/bin:" + os.environ.get("PATH", "")

def _load_conf():
    cfg = {}
    conf = FICHAJE / "horario.conf"
    if conf.exists():
        for line in conf.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"')
    return cfg

_CONF = _load_conf()
UNLOCK_PIN = _CONF.get("UNLOCK_PIN", "0000")

# ── Args ──────────────────────────────────────────────────────────────────

if len(sys.argv) < 2:
    print(f"Uso: {sys.argv[0]} ACTION [ACUM_MIN]", file=sys.stderr)
    sys.exit(1)

ACTION   = sys.argv[1]
ACUM_MIN = int(sys.argv[2]) if len(sys.argv) > 2 else 0
ACUM_STR = f"{ACUM_MIN // 60}h{ACUM_MIN % 60:02d}m"

# ── Telegram ──────────────────────────────────────────────────────────────

def _load_tg():
    conf = FICHAJE / "telegram.conf"
    if not conf.exists():
        return None, None
    cfg = {}
    for line in conf.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg.get("TG_TOKEN"), cfg.get("TG_CHAT_ID")

def notify(msg):
    token, chat_id = _load_tg()
    if not token or not chat_id:
        return
    try:
        data = json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

# ── Log ───────────────────────────────────────────────────────────────────

DIAS  = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
MESES = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]

def _prefix():
    now = datetime.now()
    return f"[{DIAS[now.weekday()]} {now.day} {MESES[now.month-1]} {now.year}] [{now.strftime('%H:%M')}]"

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"{_prefix()} {msg}\n")

def err(msg):
    log(f"[ERROR] {msg}")

# ── Token ─────────────────────────────────────────────────────────────────

def _read_mmkv():
    r = subprocess.run(
        ["adb", "-s", ADB_HOST, "shell", "strings",
         "/data/data/com.holded.app/files/mmkv/mmkv.default"],
        capture_output=True, text=True
    )
    lines = r.stdout.splitlines()
    token = account_id = None
    for i, line in enumerate(lines):
        if line == "bg_session_token" and i + 1 < len(lines):
            token = lines[i + 1]
        if line == "bg_session_account_id" and i + 1 < len(lines):
            account_id = lines[i + 1][:24]
    return token, account_id

def _jwt_days_left(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        exp = json.loads(base64.b64decode(payload))["exp"]
        remaining = exp - datetime.now(timezone.utc).timestamp()
        return int(remaining / 86400)
    except Exception:
        return None

def _refresh_token_via_app():
    log("[TOKEN] JWT expira pronto — abriendo Holded para refrescar")
    notify("🔑 JWT expira pronto — refrescando token")
    subprocess.run(["adb", "-s", ADB_HOST, "shell", "input", "keyevent", "224"], capture_output=True)
    time.sleep(1)
    subprocess.run(["adb", "-s", ADB_HOST, "shell", "input", "swipe", "720", "1800", "720", "900", "300"], capture_output=True)
    time.sleep(1)
    subprocess.run(["adb", "-s", ADB_HOST, "shell", "input", "text", UNLOCK_PIN], capture_output=True)
    time.sleep(0.5)
    subprocess.run(["adb", "-s", ADB_HOST, "shell", "input", "keyevent", "66"], capture_output=True)
    time.sleep(1)
    subprocess.run(
        ["adb", "-s", ADB_HOST, "shell", "am", "start",
         "-n", "com.holded.app/com.holded.MainActivity"],
        capture_output=True
    )
    time.sleep(5)
    subprocess.run(["adb", "-s", ADB_HOST, "shell", "input", "keyevent", "3"], capture_output=True)
    time.sleep(1)
    subprocess.run(["adb", "-s", ADB_HOST, "shell", "input", "keyevent", "26"], capture_output=True)

def relogin():
    log("[TOKEN] Sesion caducada — ejecutando relogin automatico")
    r = subprocess.run(
        ["python3", str(FICHAJE / "relogin.py")],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        log(f"[TOKEN] relogin FALLO: {r.stderr.strip()}")
        notify("❌ relogin FALLO — sesion no renovada")
        return False
    log("[TOKEN] relogin OK")
    notify("🔑 relogin OK — sesion renovada")
    return True

def extract_token():
    token, account_id = _read_mmkv()
    if token:
        days = _jwt_days_left(token)
        if days is not None and days < 7:
            _refresh_token_via_app()
            token, account_id = _read_mmkv()
    return token, account_id

# ── API ───────────────────────────────────────────────────────────────────

BASE_MOBILE = "https://mobile.holded.com"
BASE_APP    = "https://app.holded.com"

def api(method, base, path, token, account_id, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("token", token)
    req.add_header("accountid", account_id)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, str(e)

def get_tracker(token, account_id):
    status, body = api("GET", BASE_MOBILE, "/internal/team/employee/current/tracker", token, account_id)
    if status == 200 and body and body.strip() != "null":
        return json.loads(body)
    return None

def clock_in(token, account_id):
    return api("POST", BASE_APP, "/internal/team/employee/tracker/clock-in", token, account_id)

def clock_out(token, account_id):
    return api("POST", BASE_APP, "/internal/team/employee/tracker/clock-out", token, account_id)

def pause(token, account_id, tracker_id):
    return api("POST", BASE_APP, "/internal/team/tracker/pause", token, account_id, {"trackerId": tracker_id})

def resume(token, account_id, tracker_id):
    return api("POST", BASE_APP, "/internal/team/tracker/resume", token, account_id, {"trackerId": tracker_id})

# ── Main ──────────────────────────────────────────────────────────────────

def run_action(token, account_id):
    if ACTION == "ENTRADA":
        return clock_in(token, account_id)

    elif ACTION == "INICIO_PAUSA":
        tracker = get_tracker(token, account_id)
        if not tracker:
            return None, "Timer no activo"
        return pause(token, account_id, tracker["id"])

    elif ACTION == "FIN_PAUSA":
        tracker = get_tracker(token, account_id)
        if not tracker:
            return None, "Timer no activo"
        return resume(token, account_id, tracker["id"])

    elif ACTION == "SALIDA":
        return clock_out(token, account_id)

    else:
        err(f"Accion desconocida: {ACTION}")
        sys.exit(1)


token, account_id = extract_token()
if not token or not account_id:
    notify("🔑 Token no encontrado — ejecutando re-login automatico")
    if relogin():
        token, account_id = _read_mmkv()
    if not token or not account_id:
        msg = f"[{ACTION}] Token no encontrado tras relogin — accion NO ejecutada"
        err(msg)
        notify(f"❌ ERROR: {msg}")
        sys.exit(1)

status, body = run_action(token, account_id)

if status == 401:
    notify("🔑 Sesion caducada — ejecutando re-login automatico")
    if relogin():
        token, account_id = _read_mmkv()
        status, body = run_action(token, account_id)
    else:
        msg = f"[{ACTION}] relogin fallido — accion NO ejecutada"
        err(msg)
        sys.exit(1)

MENSAJES = {
    "ENTRADA":      f"✅ Entrada fichada",
    "INICIO_PAUSA": f"⏸ Pausa iniciada",
    "FIN_PAUSA":    f"▶️ De vuelta al trabajo",
    "SALIDA":       f"🏁 Salida fichada — total: {ACUM_STR}",
}

if status and status < 400:
    log(f"[{ACTION}] OK → {body[:80]}")
    notify(MENSAJES.get(ACTION, f"✅ {ACTION} OK"))
else:
    err(f"[{ACTION}] FALLO {status}: {body}")
    notify(f"❌ ERROR {ACTION}: {status} — {body[:100]}")
    sys.exit(1)

log(f"[{ACTION}] Acumulado: {ACUM_STR}")
if ACTION == "SALIDA":
    log(f"[FIN DIA] Total trabajado: {ACUM_STR} - OK")
    with open(LOG_FILE, "a") as f:
        f.write("\n")
