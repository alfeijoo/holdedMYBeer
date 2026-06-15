#!/data/data/com.termux/files/usr/bin/python3
"""
Prueba de corrección de fichaje para una fecha concreta.
Uso: python3 test_correc.py [YYYY-MM-DD] [--dry-run]
     python3 test_correc.py              → usa el último dia laborable
     python3 test_correc.py 2026-06-11  → fecha concreta
     python3 test_correc.py --dry-run   → solo muestra, no modifica
"""

import sys
import os
import json
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

HOME    = Path("/data/data/com.termux/files/home")
FICHAJE = HOME / "holdedMYBeer"
ADB_KEYS = HOME / ".android" / "adbkey"
ADB_HOST = "127.0.0.1:5555"
BASE_APP = "https://app.holded.com"

os.environ["ADB_VENDOR_KEYS"] = str(ADB_KEYS)
os.environ["PATH"] = "/data/data/com.termux/files/usr/bin:" + os.environ.get("PATH", "")

# ── Args ──────────────────────────────────────────────────────────────────

DRY_RUN = "--dry-run" in sys.argv
args    = [a for a in sys.argv[1:] if a != "--dry-run"]

if args:
    DATE = args[0]
else:
    d = datetime.now().date() - timedelta(days=1)
    while d.isoweekday() >= 6:
        d -= timedelta(days=1)
    DATE = d.strftime("%Y-%m-%d")

try:
    check_date = datetime.strptime(DATE, "%Y-%m-%d")
except ValueError:
    print(f"Fecha inválida: {DATE}")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────

def load_conf():
    cfg = {}
    conf = FICHAJE / "horario.conf"
    if conf.exists():
        for line in conf.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.split("#")[0].strip().strip('"')
    return cfg

cfg      = load_conf()
HORAS_LJ = int(cfg.get("HORAS_LJ", "480"))
HORAS_V  = int(cfg.get("HORAS_V",  "330"))
dow      = check_date.isoweekday()
TARGET   = HORAS_LJ if dow <= 4 else HORAS_V

DIAS = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
print(f"\n{'='*50}")
print(f"Fecha    : {DATE} ({DIAS[dow-1]})")
print(f"Objetivo : {TARGET}min ({TARGET//60}h{TARGET%60:02d}m)")
print(f"Modo     : {'DRY-RUN (sin cambios)' if DRY_RUN else 'REAL (aplicará corrección si hay delta)'}")
print(f"{'='*50}\n")

# ── Token ─────────────────────────────────────────────────────────────────

def read_mmkv():
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

print("Leyendo token de MMKV...")
token, account_id = read_mmkv()
if not token or not account_id:
    print("❌ No se pudo leer token de MMKV")
    sys.exit(1)
print(f"Token OK (account: {account_id[:8]}...)\n")

# ── API ───────────────────────────────────────────────────────────────────

def _do_req(req):
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
            return r.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:300]
        except Exception:
            body = ""
        return e.code, {"_raw": body}
    except Exception as ex:
        return None, {"_error": str(ex)}

def api_get(path):
    req = urllib.request.Request(BASE_APP + path, method="GET")
    req.add_header("token", token)
    req.add_header("accountid", account_id)
    req.add_header("Accept", "application/json")
    return _do_req(req)

def api_put(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE_APP + path, data=data, method="PUT")
    req.add_header("token", token)
    req.add_header("accountid", account_id)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    return _do_req(req)

# ── Consulta ──────────────────────────────────────────────────────────────

tz_offset  = datetime.now().astimezone().strftime("%z")
tz_colon   = tz_offset[:3] + ":" + tz_offset[3:]
date_param = urllib.parse.quote(f"{DATE}T00:00:00{tz_colon}")

print(f"Consultando Holded para {DATE}...")
status, data = api_get(f"/internal/team/v2/day-timetracking?date={date_param}")
print(f"GET status: {status}\n")

if status != 200:
    print(f"❌ Error: {json.dumps(data, indent=2)[:400]}")
    sys.exit(1)

trackers = data.get("trackers", [])
if not trackers:
    print(f"⚠️  Sin trackers para {DATE}")
    print(f"Respuesta: {json.dumps(data, indent=2)[:300]}")
    sys.exit(0)

tracker = trackers[0]

start_local = datetime.fromisoformat(tracker["startDateWithTimeZone"])
end_utc     = datetime.fromisoformat(tracker["end"])
end_local   = end_utc.astimezone()
effective_min = round(tracker.get("effectiveWorkedTime", 0) / 60)
delta = effective_min - TARGET

print(f"Entrada  : {start_local.strftime('%H:%M')}")
for p in tracker.get("pauses", []):
    ps = datetime.fromisoformat(p["start"]).astimezone().strftime("%H:%M")
    pe = datetime.fromisoformat(p["end"]).astimezone().strftime("%H:%M")
    print(f"Pausa    : {ps} - {pe}")
print(f"Salida   : {end_local.strftime('%H:%M')}")
print(f"Estado   : {'✅ completado' if tracker.get('done') else '🔄 en curso'}")
print(f"\n{'─'*40}")
print(f"Efectivo : {effective_min}min ({effective_min//60}h{effective_min%60:02d}m)")
print(f"Objetivo : {TARGET}min ({TARGET//60}h{TARGET%60:02d}m)")
print(f"Delta    : {delta:+d}min")
print(f"{'─'*40}\n")

if not tracker.get("done"):
    print("⚠️  Tracker aún en curso — no se puede corregir.")
    sys.exit(0)

if delta == 0:
    print("✅ Fichaje exacto. Sin corrección necesaria.")
    sys.exit(0)

# ── Corrección ────────────────────────────────────────────────────────────

new_end  = (end_utc - timedelta(minutes=delta)).astimezone()
old_hhmm = end_local.strftime("%H:%M")
new_hhmm = new_end.strftime("%H:%M")

pauses = [
    {"start": datetime.fromisoformat(p["start"]).astimezone().strftime("%H:%M"),
     "end":   datetime.fromisoformat(p["end"]).astimezone().strftime("%H:%M")}
    for p in tracker.get("pauses", [])
]

print(f"Corrección : salida {old_hhmm} → {new_hhmm} ({delta:+d}min)")
print(f"Tracker id : {tracker['id']}\n")

if DRY_RUN:
    print("🔍 DRY-RUN: no se ha modificado nada.")
    print(f"   Para aplicar: python3 test_correc.py {DATE}")
    sys.exit(0)

body = {"trackers": [{
    "id":          tracker["id"],
    "workplaceId": tracker.get("workplaceId"),
    "isRemote":    False,
    "start":       tracker["startDateWithTimeZone"],
    "end":         new_end.isoformat(),
    "pauses":      pauses,
}]}

print("Aplicando corrección...")
status2, resp2 = api_put("/internal/team/v2/bulk-timetracking-update", body)
print(f"PUT status: {status2}")

if status2 and status2 < 400:
    print(f"\n✅ Fichaje corregido: salida {old_hhmm} → {new_hhmm} ({delta:+d}min)")
else:
    print(f"\n❌ Error en PUT:")
    print(json.dumps(resp2, indent=2)[:400])
    sys.exit(1)
