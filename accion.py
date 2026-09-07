#!/data/data/com.termux/files/usr/bin/python3
"""
Ejecutado por at scheduler.
Uso: accion.py <ACTION> <ACUM_MIN>
ACTION: ENTRADA | INICIO_PAUSA | FIN_PAUSA | SALIDA
"""

import re
import sys
import os
import json
import base64
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
import urllib.parse
from pathlib import Path

import horario_conf

# ── Rutas ─────────────────────────────────────────────────────────────────

HOME      = Path("/data/data/com.termux/files/home")
FICHAJE   = HOME / "holdedMYBeer"
LOG_FILE  = FICHAJE / "holdmybeer.log"
PLAN_FILE = FICHAJE / "plan.json"
ACCION    = FICHAJE / "accion.py"
PYTHON_PATH = "/data/data/com.termux/files/usr/bin/python3"
ADB_KEYS  = HOME / ".android" / "adbkey"
ADB_HOST  = "127.0.0.1:5555"

os.environ["ADB_VENDOR_KEYS"] = str(ADB_KEYS)
os.environ["PATH"] = "/data/data/com.termux/files/usr/bin:" + os.environ.get("PATH", "")

PERFIL, _CONF = horario_conf.resolve()
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

# ── Reprogramacion adaptativa ────────────────────────────────────────────

def _hhmm_to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def _min_to_hhmm(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"

def _load_plan():
    if not PLAN_FILE.exists():
        return None
    try:
        plan = json.loads(PLAN_FILE.read_text())
        today = datetime.now().strftime("%Y-%m-%d")
        return plan if plan.get("date") == today else None
    except Exception:
        return None

def _update_plan():
    """Carga el plan una vez, guarda el TS de la accion y reprograma SALIDA si hay retraso. Una sola escritura."""
    plan = _load_plan()
    if not plan:
        return
    now = datetime.now()
    actual_min = now.hour * 60 + now.minute
    actual = plan.setdefault("actual", {})
    actual[f"{ACTION}_TS"] = now.timestamp()

    scheduled_hhmm = plan["scheduled"].get(ACTION)
    if not scheduled_hhmm:
        PLAN_FILE.write_text(json.dumps(plan))
        return

    if ACTION == "ENTRADA":
        delay = actual_min - _hhmm_to_min(scheduled_hhmm)
    elif ACTION == "FIN_PAUSA":
        inicio_ts = actual.get("INICIO_PAUSA_TS")
        pausa_dur = plan.get("pausa_dur", 60)
        if inicio_ts:
            inicio_min = datetime.fromtimestamp(inicio_ts).hour * 60 + datetime.fromtimestamp(inicio_ts).minute
            delay = actual_min - (inicio_min + pausa_dur)
        else:
            delay = actual_min - _hhmm_to_min(scheduled_hhmm)
    else:
        delay = 0

    if delay > 0:
        salida_job = plan["jobs"].get("SALIDA")
        current_salida = plan["scheduled"].get("SALIDA")
        if salida_job and current_salida:
            new_min   = _hhmm_to_min(current_salida) + delay
            new_hhmm  = _min_to_hhmm(new_min)
            today     = now.strftime("%Y-%m-%d")
            subprocess.run(["atrm", str(salida_job)], capture_output=True)
            horas_total = plan.get("horas_total", 480)
            cmd  = f"{PYTHON_PATH} {ACCION} SALIDA {horas_total}"
            proc = subprocess.run(["at", new_hhmm, today], input=cmd + "\n", capture_output=True, text=True)
            m = re.search(r'job (\d+)', proc.stderr)
            if m:
                plan["jobs"]["SALIDA"] = int(m.group(1))
            plan["scheduled"]["SALIDA"] = new_hhmm
            PLAN_FILE.write_text(json.dumps(plan))
            msg = f"⏰ Retraso {delay}min en {ACTION} → SALIDA reprogramada {current_salida}→{new_hhmm}"
            log(msg)
            notify(msg)
            return

    PLAN_FILE.write_text(json.dumps(plan))

def _wait_if_short():
    plan = _load_plan()
    if not plan:
        return
    entry_ts = plan.get("actual", {}).get("ENTRADA_TS")
    if entry_ts is None:
        return
    horas_total = plan.get("horas_total", 480)
    inicio_ts = plan.get("actual", {}).get("INICIO_PAUSA_TS")
    fin_ts    = plan.get("actual", {}).get("FIN_PAUSA_TS")
    if inicio_ts and fin_ts:
        pausa_sec = fin_ts - inicio_ts
    else:
        pausa_sec = plan.get("pausa_dur", 0) * 60
    required_exit_ts = entry_ts + horas_total * 60 + pausa_sec
    wait_sec = required_exit_ts - datetime.now().timestamp()
    if wait_sec > 10:
        required_hhmm = datetime.fromtimestamp(required_exit_ts).strftime("%H:%M")
        msg = f"⏳ Salida {round(wait_sec / 60)}min anticipada — esperando hasta {required_hhmm}"
        log(msg)
        notify(msg)
        time.sleep(wait_sec)

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
    """Devuelve (tracker|None, status). status permite distinguir:
       200 + None  -> timer realmente parado
       401         -> token caducado (el caller dispara relogin)
       otro/None   -> fallo transitorio tras 3 intentos
    """
    status = None
    for _ in range(3):
        status, body = api("GET", BASE_MOBILE, "/internal/team/employee/current/tracker", token, account_id)
        if status == 200:
            if body and body.strip() != "null":
                return json.loads(body), 200
            return None, 200
        if status == 401:
            return None, 401
        time.sleep(3)
    err(f"[{ACTION}] get_tracker sin respuesta util tras 3 intentos (ultimo status={status})")
    return None, status

def clock_in(token, account_id):
    return api("POST", BASE_APP, "/internal/team/employee/tracker/clock-in", token, account_id)

def clock_out(token, account_id):
    return api("POST", BASE_APP, "/internal/team/employee/tracker/clock-out", token, account_id)

def pause(token, account_id, tracker_id):
    return api("POST", BASE_APP, "/internal/team/tracker/pause", token, account_id, {"trackerId": tracker_id})

def resume(token, account_id, tracker_id):
    return api("POST", BASE_APP, "/internal/team/tracker/resume", token, account_id, {"trackerId": tracker_id})

# ── Corrección post-salida ────────────────────────────────────────────────

def corregir_salida(token, account_id):
    dow       = datetime.now().isoweekday()
    today_str = datetime.now().strftime("%Y-%m-%d")
    horas_lj  = int(_CONF.get("HORAS_LJ", "480"))
    horas_v   = int(_CONF.get("HORAS_V",  "330"))
    target    = horas_lj if dow <= 4 else horas_v

    tz_offset  = datetime.now().astimezone().strftime("%z")
    tz_colon   = tz_offset[:3] + ":" + tz_offset[3:]
    date_param = urllib.parse.quote(f"{today_str}T00:00:00{tz_colon}")

    status, body = api("GET", BASE_APP, f"/internal/team/v2/day-timetracking?date={date_param}", token, account_id)
    if status != 200:
        err(f"[CORREC] GET day-timetracking: {status}")
        return
    try:
        data = json.loads(body)
    except Exception:
        err(f"[CORREC] JSON parse error")
        return

    trackers = data.get("trackers", [])
    if not trackers or not trackers[0].get("done"):
        log(f"[CORREC] Sin tracker completado para {today_str}")
        notify(f"⚠️ CORREC: el tracker de {today_str} no quedó cerrado — corrige a mano")
        return

    tracker  = trackers[0]
    end_dt   = datetime.fromisoformat(tracker["end"]).astimezone()
    old_hhmm = end_dt.strftime("%H:%M")

    start_dt  = datetime.fromisoformat(tracker["startDateWithTimeZone"]).astimezone()
    start_min = start_dt.replace(second=0, microsecond=0)

    pausa_dur       = int(_CONF.get("PAUSA_DURACION", "60"))
    raw_pauses      = tracker.get("pauses", [])
    total_pause_min = pausa_dur * len(raw_pauses)

    new_end  = start_min + timedelta(minutes=target + total_pause_min)
    new_hhmm = new_end.strftime("%H:%M")

    effective_min = round(tracker.get("effectiveWorkedTime", 0) / 60)
    delta         = round((new_end - end_dt).total_seconds() / 60)

    log(f"[CORREC] perfil={PERFIL} start={start_min.strftime('%H:%M')} pausa={total_pause_min}min real={effective_min}min objetivo={target}min → {old_hhmm}→{new_hhmm} ({delta:+d}min)")

    if new_end == end_dt.replace(second=0, microsecond=0):
        return

    pauses = []
    for p in raw_pauses:
        p_start = datetime.fromisoformat(p["start"]).astimezone().replace(second=0, microsecond=0)
        p_end   = p_start + timedelta(minutes=pausa_dur)
        pauses.append({"start": p_start.strftime("%H:%M"), "end": p_end.strftime("%H:%M")})
    put_body = {"trackers": [{
        "id":          tracker["id"],
        "workplaceId": tracker.get("workplaceId"),
        "isRemote":    False,
        "start":       tracker["startDateWithTimeZone"],
        "end":         new_end.isoformat(),
        "pauses":      pauses,
    }]}

    s2, b2 = api("PUT", BASE_APP, "/internal/team/v2/bulk-timetracking-update", token, account_id, put_body)
    if s2 and s2 < 400:
        correc_hhmm = datetime.now().astimezone().strftime("%H:%M")
        msg = f"✅ Fichaje corregido a las {correc_hhmm}: salida {old_hhmm}→{new_hhmm} ({delta:+d}min)"
        log(f"[CORREC] {msg}")
        notify(msg)
    else:
        err(f"[CORREC] PUT: {s2} {b2[:100]}")
        notify(f"❌ CORREC FALLO: {s2}")

# ── Main ──────────────────────────────────────────────────────────────────

def run_action(token, account_id):
    if ACTION == "ENTRADA":
        return clock_in(token, account_id)

    elif ACTION == "INICIO_PAUSA":
        tracker, tstatus = get_tracker(token, account_id)
        if tstatus == 401:
            return 401, "tracker 401"
        if not tracker:
            return None, "Timer no activo"
        if tracker.get("paused"):
            return "SKIP", "el tracker ya estaba en pausa"
        return pause(token, account_id, tracker["id"])

    elif ACTION == "FIN_PAUSA":
        tracker, tstatus = get_tracker(token, account_id)
        if tstatus == 401:
            return 401, "tracker 401"
        if not tracker:
            return None, "Timer no activo"
        if not tracker.get("paused"):
            return "SKIP", "el tracker no estaba en pausa"
        return resume(token, account_id, tracker["id"])

    elif ACTION == "SALIDA":
        # Si quedo una pausa abierta (INICIO_PAUSA sin su FIN_PAUSA), cerrarla
        # antes de fichar salida para que el tracker quede 'done'. Luego
        # corregir_salida() ajusta esa pausa a PAUSA_DURACION y pone el resto
        # como trabajado hasta cuadrar el objetivo del dia.
        tracker, tstatus = get_tracker(token, account_id)
        if tstatus == 401:
            return 401, "tracker 401"
        if tracker and tracker.get("paused"):
            rs, _rb = resume(token, account_id, tracker["id"])
            log(f"[SALIDA] pausa abierta detectada -> resume previo (status {rs})")
            if not rs or rs >= 400:
                notify(f"⚠️ SALIDA: no pude cerrar la pausa abierta (status {rs}) — revisa a mano")
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

if ACTION == "SALIDA":
    _wait_if_short()

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

if status == "SKIP":
    log(f"[{ACTION}] omitido — {body}")
    notify(f"⚠️ {ACTION} omitido — {body}")
    sys.exit(0)

MENSAJES = {
    "ENTRADA":      f"✅ Entrada fichada",
    "INICIO_PAUSA": f"⏸ Pausa iniciada",
    "FIN_PAUSA":    f"▶️ De vuelta al trabajo",
    "SALIDA":       f"🏁 Salida fichada — total: {ACUM_STR}",
}

if status and status < 400:
    log(f"[{ACTION}] OK → {body[:80]}")
    notify(MENSAJES.get(ACTION, f"✅ {ACTION} OK"))
    if ACTION in ("ENTRADA", "INICIO_PAUSA", "FIN_PAUSA"):
        _update_plan()
    elif ACTION == "SALIDA":
        corregir_salida(token, account_id)
else:
    err(f"[{ACTION}] FALLO {status}: {body}")
    notify(f"❌ ERROR {ACTION}: {status} — {body[:100]}")
    sys.exit(1)

log(f"[{ACTION}] Acumulado: {ACUM_STR}")
if ACTION == "SALIDA":
    log(f"[FIN DIA] Total trabajado: {ACUM_STR} - OK")
    with open(LOG_FILE, "a") as f:
        f.write("\n")
