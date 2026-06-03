#!/data/data/com.termux/files/usr/bin/python3
"""
Bot Telegram para controlar fichaje Holded.
Ejecutar cada minuto via cron.
"""

import sys
import os
import re
import json
import base64
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

HOME    = Path("/data/data/com.termux/files/home")
FICHAJE = HOME / "holdedMYBeer"
LOG     = FICHAJE / "holdmybeer.log"
OFFSET  = FICHAJE / "bot_offset.txt"
PYTHON  = "/data/data/com.termux/files/usr/bin/python3"
ACCION  = FICHAJE / "accion.py"

ADB_HOST = "127.0.0.1:5555"
ADB_KEYS = str(HOME / ".android" / "adbkey")
BASE_MOBILE = "https://mobile.holded.com"

os.environ["ADB_VENDOR_KEYS"] = ADB_KEYS
os.environ["PATH"] = "/data/data/com.termux/files/usr/bin:" + os.environ.get("PATH", "")

def _help_text():
    return f"""\
🤖 {BOT_NAME} - Fichaje Holded

/entrada  - Fichar entrada
/pausa    - Iniciar pausa
/resume   - Volver del descanso
/salida   - Fichar salida
/estado   - Estado del timer actual
/log      - Ultimas lineas del log
/plan     - Jobs programados (at)
/help     - Este mensaje"""


# ── Telegram ──────────────────────────────────────────────────────────────

def _load_tg():
    conf = FICHAJE / "telegram.conf"
    cfg = {}
    for line in conf.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg["TG_TOKEN"], cfg["TG_CHAT_ID"], cfg.get("BOT_NAME", "Bot")

TG_TOKEN, TG_CHAT_ID, BOT_NAME = _load_tg()

def tg_get(path):
    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{TG_TOKEN}/{path}", timeout=10
        ) as r:
            return json.loads(r.read())
    except Exception:
        return None

def reply(text):
    data = json.dumps({"chat_id": TG_CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=data, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


# ── Token (para /estado) ──────────────────────────────────────────────────

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

def _get_tracker(token, account_id):
    req = urllib.request.Request(
        BASE_MOBILE + "/internal/team/employee/current/tracker"
    )
    req.add_header("token", token)
    req.add_header("accountid", account_id)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
            if body and body.strip() != "null":
                return json.loads(body)
    except Exception:
        pass
    return None


# ── Comandos ──────────────────────────────────────────────────────────────

def cmd_fichar(action):
    acum = 0
    if action in ("INICIO_PAUSA", "FIN_PAUSA", "SALIDA"):
        token, account_id = _read_mmkv()
        if token and account_id:
            tracker = _get_tracker(token, account_id)
            if tracker:
                start = tracker.get("startTimestamp") or tracker.get("start")
                if start:
                    acum = int((datetime.now(timezone.utc).timestamp() - start / 1000) / 60)

    reply(f"⏳ Procesando {action}...")
    subprocess.run([PYTHON, str(ACCION), action, str(acum)])


def cmd_estado():
    token, account_id = _read_mmkv()
    if not token or not account_id:
        return "❌ No se pudo leer token de MMKV"

    tracker = _get_tracker(token, account_id)
    if not tracker:
        return "⏹ Timer parado — sin fichaje activo"

    start_ms = tracker.get("startTimestamp") or tracker.get("start")
    estado   = tracker.get("status", "?")
    tid      = tracker.get("id", "?")

    lines = [f"📍 Estado: {estado}", f"🔑 Tracker: {tid[:10]}..."]

    if start_ms:
        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).astimezone()
        elapsed  = int((datetime.now(timezone.utc).timestamp() - start_ms / 1000) / 60)
        lines.append(f"🕐 Inicio: {start_dt.strftime('%H:%M')}")
        lines.append(f"⏱ Transcurrido: {elapsed // 60}h{elapsed % 60:02d}m")

    pauses = tracker.get("pauses", [])
    if pauses:
        lines.append(f"⏸ Pausas: {len(pauses)}")

    return "\n".join(lines)


_LINE_RE  = re.compile(r'^\[([^\]]+)\] \[(\d{2}:\d{2})\] (.+)$')
_DIAS_C   = {"Lunes":"Lun","Martes":"Mar","Miercoles":"Mie",
              "Jueves":"Jue","Viernes":"Vie","Sabado":"Sab","Domingo":"Dom"}

def _fmt_content(time, rest):
    if "[ENTRADA] OK"      in rest: return f"✅ {time} Entrada"
    if "[INICIO_PAUSA] OK" in rest: return f"⏸ {time} Pausa"
    if "[FIN_PAUSA] OK"    in rest: return f"▶️ {time} Vuelta"
    if "[SALIDA] OK"       in rest: return f"🏁 {time} Salida"
    if "[FIN DIA]"         in rest:
        m = re.search(r'Total trabajado: (\S+)', rest)
        return f"📊 Total: {m.group(1) if m else '?'}"
    if "[ERROR]" in rest:
        clean = re.sub(r'\[[\w\s]+\]\s*', '', rest).strip()
        return f"❌ {time} {clean[:70]}"
    if "[TOKEN]" in rest:
        if "relogin OK"    in rest: return f"🔑 {time} relogin OK"
        if "relogin FALLO" in rest: return f"❌ {time} relogin FALLO"
        if "expira"        in rest: return f"🔑 {time} Token: refrescando"
        if "Sesion"        in rest: return f"🔑 {time} Sesión caducada → relogin"
        return None
    if "Acumulado:" in rest:
        return None
    return None

def cmd_log():
    if not LOG.exists():
        return "Log vacío"

    days = {}
    day_order = []
    for line in LOG.read_text().splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        day_raw, time, rest = m.group(1), m.group(2), m.group(3)
        parts = day_raw.split()
        short = f"{_DIAS_C.get(parts[0], parts[0])} {parts[1]} {parts[2]}" if len(parts) >= 3 else day_raw
        fmt = _fmt_content(time, rest)
        if fmt is None:
            continue
        if short not in days:
            days[short] = []
            day_order.append(short)
        days[short].append(fmt)

    if not days:
        return "Log vacío"

    out = []
    for day in day_order[-5:]:
        out.append(f"── {day} ──")
        out.extend(days[day])
        out.append("")

    text = "\n".join(out).strip()
    return text[:4000] if len(text) > 4000 else text


def cmd_plan():
    r = subprocess.run(["atq"], capture_output=True, text=True)
    if not r.stdout.strip():
        return "Sin jobs programados en at"
    lines = []
    for line in r.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 6:
            lines.append(f"  [{parts[0]}] {parts[3]} {parts[2]} {parts[4]}")
        else:
            lines.append(f"  {line}")
    return "📅 Jobs programados:\n" + "\n".join(lines)


# ── Dispatch ──────────────────────────────────────────────────────────────

ACCIONES = {
    "/entrada": lambda: cmd_fichar("ENTRADA"),
    "/pausa":   lambda: cmd_fichar("INICIO_PAUSA"),
    "/resume":  lambda: cmd_fichar("FIN_PAUSA"),
    "/salida":  lambda: cmd_fichar("SALIDA"),
}

def handle(text):
    cmd = text.strip().split()[0].lower().split("@")[0]

    if cmd in ACCIONES:
        ACCIONES[cmd]()
    elif cmd == "/estado":
        reply(cmd_estado())
    elif cmd == "/log":
        reply(cmd_log())
    elif cmd == "/plan":
        reply(cmd_plan())
    elif cmd in ("/help", "/start", "/ayuda"):
        reply(_help_text())
    else:
        reply(f"Comando desconocido: {cmd}\n\n{_help_text()}")


# ── Main ──────────────────────────────────────────────────────────────────

offset = int(OFFSET.read_text()) if OFFSET.exists() else 0
updates = tg_get(f"getUpdates?offset={offset}&timeout=0&allowed_updates=[\"message\"]")

if not updates or not updates.get("ok"):
    sys.exit(0)

for upd in updates["result"]:
    new_offset = upd["update_id"] + 1
    if new_offset > offset:
        offset = new_offset

    msg     = upd.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text    = msg.get("text", "")

    if chat_id != TG_CHAT_ID or not text.startswith("/"):
        continue

    handle(text)

OFFSET.write_text(str(offset))
