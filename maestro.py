#!/data/data/com.termux/files/usr/bin/python3
"""
Ejecutado por cron a las 23:00 cada noche.
Calcula tiempos aleatorios del dia siguiente y los programa con at.
"""

import os
import re
import sys
import json
import base64
import random
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta, date
from pathlib import Path

# ── Rutas ─────────────────────────────────────────────────────────────────

HOME           = Path("/data/data/com.termux/files/home")
FICHAJE        = HOME / "holdedMYBeer"
LOG_FILE       = FICHAJE / "holdmybeer.log"
CONFIG         = FICHAJE / "horario.conf"
ACCION         = FICHAJE / "accion.py"
AUSENCIAS      = FICHAJE / "ausencias.txt"
AUSENCIAS_CACHE = FICHAJE / "ausencias_cache.json"
ADB_KEYS       = HOME / ".android" / "adbkey"
ADB_HOST       = "127.0.0.1:5555"

os.environ["ADB_VENDOR_KEYS"] = str(ADB_KEYS)
os.environ["PATH"] = "/data/data/com.termux/files/usr/bin:" + os.environ.get("PATH", "")

PYTHON = "/data/data/com.termux/files/usr/bin/python3"

# ── Log ───────────────────────────────────────────────────────────────────

DIAS  = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
MESES = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]

def _prefix():
    now = datetime.now()
    return f"[{DIAS[now.weekday()]} {now.day} {MESES[now.month-1]} {now.year}] [{now.strftime('%H:%M')}] [MAESTRO]"

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"{_prefix()} {msg}\n")

def err(msg):
    log(f"[ERROR] {msg}")

def rotate_log(max_lines=500):
    if not LOG_FILE.exists():
        return
    lines = LOG_FILE.read_text().splitlines()
    if len(lines) > max_lines:
        LOG_FILE.write_text("\n".join(lines[-max_lines:]) + "\n")

# ── Telegram ──────────────────────────────────────────────────────────────

FRASES_FINDE = [
    "Hoy no se ficha. A descansar, campeón. 🛋️",
    "Fin de semana detectado. El robot también descansa. ⚽",
    "No hay fichaje hoy. Disfruta que te lo has ganado. 🍺",
    "Sistema en modo fin de semana. Que no te llamen. 📵",
    "Sábado/domingo = modo bestia activado. Sin fichajes. 🦁",
]

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

# ── Config ────────────────────────────────────────────────────────────────

def load_config():
    defaults = {
        "ENTRADA_BASE":      "08:00",
        "ENTRADA_VARIACION": "16",
        "PAUSA_BASE":        "13:00",
        "PAUSA_VARIACION":   "60",
        "PAUSA_DURACION":    "60",
        "HORAS_LJ":          "480",
        "HORAS_V":           "330",
    }
    if CONFIG.exists():
        for line in CONFIG.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'^(\w+)="?([^"#]*)"?', line)
            if m:
                defaults[m.group(1)] = m.group(2).strip()
    return defaults

def hhmm_to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def min_to_hhmm(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"

# ── Token (ADB → MMKV) ────────────────────────────────────────────────────

def extract_token():
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

# ── API Holded ────────────────────────────────────────────────────────────

BASE_MOBILE = "https://mobile.holded.com"
BASE_APP    = "https://app.holded.com"

def api_get(path, token, account_id, base=BASE_APP):
    req = urllib.request.Request(base + path, method="GET")
    req.add_header("token", token)
    req.add_header("accountid", account_id)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return None, {}

def _parse_ausencias_txt():
    dias = set()
    if not AUSENCIAS.exists():
        return dias
    MES_MAP = {
        "ene":1,"jan":1,"feb":2,"mar":3,"abr":4,"apr":4,"may":5,"jun":6,
        "jul":7,"ago":8,"aug":8,"sep":9,"oct":10,"nov":11,"dic":12,"dec":12,
    }
    now = datetime.now()
    for linea in AUSENCIAS.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        try:
            if " - " in linea:
                ini, fin = linea.split(" - ", 1)
                ip = ini.strip().split(); fp = fin.strip().split()
                d = date(now.year, MES_MAP[ip[1].lower()], int(ip[0]))
                e = date(now.year, MES_MAP[fp[1].lower()], int(fp[0]))
            else:
                parts = linea.split()
                d = e = date(now.year, MES_MAP[parts[1].lower()], int(parts[0]))
            while d <= e:
                dias.add(d)
                d += timedelta(days=1)
        except Exception:
            continue
    return dias

def _api_to_dates(data):
    dias = set()
    for grupo in ("employeeTimeOffs", "workplaceTimeOffs"):
        for item in data.get(grupo, []):
            if item.get("status") != "accepted":
                continue
            start = item.get("start", "")[:10]
            end   = (item.get("end") or start)[:10]
            if not start:
                continue
            try:
                d = datetime.strptime(start, "%Y-%m-%d").date()
                e = datetime.strptime(end, "%Y-%m-%d").date()
                while d <= e:
                    dias.add(d)
                    d += timedelta(days=1)
            except Exception:
                continue
    return dias

def _save_cache(dias):
    try:
        AUSENCIAS_CACHE.write_text(json.dumps({
            "fetched": datetime.now().isoformat(),
            "dates": [d.isoformat() for d in dias]
        }))
    except Exception:
        pass

def _load_cache():
    if not AUSENCIAS_CACHE.exists():
        return set()
    try:
        data = json.loads(AUSENCIAS_CACHE.read_text())
        dias = {date.fromisoformat(d) for d in data.get("dates", [])}
        log(f"Cache ausencias: {len(dias)} dias (fetch: {data.get('fetched','?')[:10]})")
        return dias
    except Exception:
        return set()

def relogin():
    log("[TOKEN] Sesion caducada — ejecutando relogin automatico")
    r = subprocess.run(
        ["python3", str(FICHAJE / "relogin.py")],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        log(f"[TOKEN] relogin FALLO: {r.stderr.strip()}")
        return False
    log("[TOKEN] relogin OK")
    return True

def fetch_ausencias(token, account_id):
    api_dias = set()
    api_ok = False
    needs_relogin = False

    for year in [datetime.now().year, datetime.now().year + 1]:
        status, data = api_get(
            f"/internal/team/v2/timeoff-year-summary?year={year}",
            token, account_id
        )
        if status == 200:
            api_dias |= _api_to_dates(data)
            api_ok = True
        elif status == 401:
            needs_relogin = True
            err(f"timeoff-year-summary {year}: 401 sesion caducada")
        else:
            err(f"timeoff-year-summary {year}: status {status}")

    if needs_relogin and not api_ok:
        notify("🔑 MAESTRO: sesion caducada — ejecutando re-login")
        if relogin():
            token, account_id = extract_token()
            return fetch_ausencias(token, account_id)
        else:
            notify("❌ MAESTRO: relogin fallido — usando cache")

    if api_ok:
        _save_cache(api_dias)
        log(f"Ausencias API: {len(api_dias)} dias cargados y cache actualizada")
    else:
        api_dias = _load_cache()
        log("Ausencias API no disponible — usando cache")

    manuales = _parse_ausencias_txt()
    if manuales:
        log(f"Ausencias manuales (ausencias.txt): {len(manuales)} dias")

    return api_dias | manuales

# ── Próximo festivo ───────────────────────────────────────────────────────

def proximo_festivo(desde, ausencias):
    candidatos = [d for d in ausencias if d > desde and d.weekday() < 5]
    if not candidatos:
        return None
    return min(candidatos)

# ── Programar at job ──────────────────────────────────────────────────────

def cancel_tomorrow_jobs(tomorrow_str):
    # formato atq: "ID\tDOW MON DD HH:MM:SS YYYY queue user"
    r = subprocess.run(["atq"], capture_output=True, text=True)
    target = datetime.strptime(tomorrow_str, "%Y-%m-%d").date()
    cancelled = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        job_id = parts[0]
        try:
            # parts[1]=DOW parts[2]=MON parts[3]=DD parts[4]=HH:MM:SS parts[5]=YYYY
            job_day = datetime.strptime(f"{parts[3]} {parts[2]} {parts[5]}", "%d %b %Y").date()
            if job_day == target:
                subprocess.run(["atrm", job_id], capture_output=True)
                cancelled.append(job_id)
        except Exception:
            continue
    if cancelled:
        log(f"Jobs previos cancelados: {', '.join(cancelled)}")

def schedule(hhmm, action, acum, tomorrow_str):
    cmd = f"{PYTHON} {ACCION} {action} {acum}"
    proc = subprocess.run(
        ["at", hhmm, tomorrow_str],
        input=cmd + "\n",
        capture_output=True, text=True
    )
    output = "\n".join(
        l for l in proc.stderr.splitlines() if not l.startswith("warning:")
    )
    if output:
        log(f"at {hhmm} {action}: {output.strip()}")
    m = re.search(r'job (\d+)', proc.stderr)
    return int(m.group(1)) if m else None

# ── Main ──────────────────────────────────────────────────────────────────

rotate_log()
cfg = load_config()

entrada_base = hhmm_to_min(cfg["ENTRADA_BASE"])
entrada_var  = int(cfg["ENTRADA_VARIACION"])
pausa_base   = hhmm_to_min(cfg["PAUSA_BASE"])
pausa_var    = int(cfg["PAUSA_VARIACION"])
pausa_dur    = int(cfg["PAUSA_DURACION"])
horas_lj     = int(cfg["HORAS_LJ"])
horas_v      = int(cfg["HORAS_V"])

tomorrow = datetime.now() + timedelta(days=1)
t_dow    = tomorrow.isoweekday()
t_day    = tomorrow.day
t_mon    = tomorrow.month
t_str    = tomorrow.strftime("%Y-%m-%d")
t_dname  = DIAS[tomorrow.weekday()]
t_date   = tomorrow.date()

log(f"Planificando {t_str} ({t_dname})")

if t_dow >= 6:
    log(f"{t_dname}: no se trabaja. Nada programado.")
    notify(random.choice(FRASES_FINDE))
    sys.exit(0)

token, account_id = extract_token()
if not token or not account_id:
    err("No se pudo extraer token. Abortando.")
    notify("❌ MAESTRO: no se pudo extraer token de MMKV")
    sys.exit(1)

cancel_tomorrow_jobs(t_str)
ausencias = fetch_ausencias(token, account_id)

if t_date in ausencias:
    log(f"{t_str}: AUSENCIA detectada via API. Nada programado.")
    notify(f"📅 Mañana ({t_dname} {t_day} {MESES[t_mon-1]}) es festivo/ausencia. No se ficha.")
    sys.exit(0)

entrada_min = entrada_base + random.randint(0, entrada_var)

if t_dow <= 4:
    pausa_ini  = pausa_base + random.randint(0, pausa_var)
    pausa_fin  = pausa_ini + pausa_dur
    salida_min = entrada_min + horas_lj + pausa_dur
    trabajado  = salida_min - entrada_min - pausa_dur
    if trabajado != horas_lj:
        msg = f"Verificacion L-J: trabajado={trabajado}min esperado={horas_lj}min. Abortando."
        err(msg)
        notify(f"❌ MAESTRO ERROR: {msg}")
        sys.exit(1)
    total_min = horas_lj
    tipo      = f"L-J ({horas_lj // 60}h)"
else:
    salida_min = entrada_min + horas_v
    trabajado  = salida_min - entrada_min
    if trabajado != horas_v:
        msg = f"Verificacion V: trabajado={trabajado}min esperado={horas_v}min. Abortando."
        err(msg)
        notify(f"❌ MAESTRO ERROR: {msg}")
        sys.exit(1)
    total_min = horas_v
    tipo      = f"Viernes ({horas_v // 60}h{horas_v % 60}m)"

h_entrada = min_to_hhmm(entrada_min)
h_salida  = min_to_hhmm(salida_min)

log(f"Plan {t_str} ({t_dname} / {tipo})")
log(f"  ENTRADA : {h_entrada}")

if t_dow <= 4:
    h_pausa_ini = min_to_hhmm(pausa_ini)
    h_pausa_fin = min_to_hhmm(pausa_fin)
    acum_pausa  = pausa_ini - entrada_min
    log(f"  PAUSA   : {h_pausa_ini} - {h_pausa_fin} ({pausa_dur}min)")

log(f"  SALIDA  : {h_salida}")
log(f"  TOTAL   : {total_min}min verificado OK")

schedule(h_entrada, "ENTRADA", 0, t_str)

if t_dow <= 4:
    schedule(h_pausa_ini, "INICIO_PAUSA", acum_pausa, t_str)
    job_fin_pausa = schedule(h_pausa_fin, "FIN_PAUSA", acum_pausa, t_str)

job_salida = schedule(h_salida, "SALIDA", total_min, t_str)

plan = {
    "date": t_str,
    "scheduled": {"ENTRADA": h_entrada, "SALIDA": h_salida},
    "jobs": {"SALIDA": job_salida},
    "horas_total": total_min,
}
if t_dow <= 4:
    plan["scheduled"]["FIN_PAUSA"] = h_pausa_fin
    plan["jobs"]["FIN_PAUSA"] = job_fin_pausa
    plan["pausa_dur"] = pausa_dur
(FICHAJE / "plan.json").write_text(json.dumps(plan))

log(f"Jobs at programados para {t_str}: OK")
log("-" * 40)

# ── Notificacion Telegram ──────────────────────────────────────────────────

if t_dow <= 4:
    msg = (
        f"📋 Plan fichaje {t_dname} {t_day} {MESES[t_mon-1]}\n"
        f"🟢 Entrada  : {h_entrada}\n"
        f"⏸ Pausa    : {h_pausa_ini} - {h_pausa_fin}\n"
        f"🔴 Salida   : {h_salida}\n"
        f"⏱ Total    : {total_min // 60}h{total_min % 60:02d}m"
    )
else:
    msg = (
        f"📋 Plan fichaje {t_dname} {t_day} {MESES[t_mon-1]}\n"
        f"🟢 Entrada  : {h_entrada}\n"
        f"🔴 Salida   : {h_salida}\n"
        f"⏱ Total    : {total_min // 60}h{total_min % 60:02d}m"
    )

if t_dow == 4:
    prox = proximo_festivo(t_date, ausencias)
    if prox:
        dias_para = (prox - t_date).days
        msg += f"\n\n🎉 Próximo festivo: {prox.strftime('%d %b %Y')} ({dias_para} días)"

notify(msg)
