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
from datetime import datetime, timezone, timedelta
from pathlib import Path

import horario_conf

HOME    = Path("/data/data/com.termux/files/home")
FICHAJE = HOME / "holdedMYBeer"
LOG     = FICHAJE / "holdmybeer.log"
OFFSET  = FICHAJE / "bot_offset.txt"
PYTHON  = "/data/data/com.termux/files/usr/bin/python3"
ACCION  = FICHAJE / "accion.py"

ADB_HOST    = "127.0.0.1:5555"
ADB_KEYS    = str(HOME / ".android" / "adbkey")
BASE_MOBILE = "https://mobile.holded.com"
BASE_APP    = "https://app.holded.com"

os.environ["ADB_VENDOR_KEYS"] = ADB_KEYS
os.environ["PATH"] = "/data/data/com.termux/files/usr/bin:" + os.environ.get("PATH", "")

def _help_text():
    return f"""\
🤖 {BOT_NAME} - Fichaje Holded

/entrada    - Fichar entrada
/pausa      - Iniciar pausa
/resume     - Volver del descanso
/salida     - Fichar salida
/estado     - Estado del timer actual
/log        - Últimas líneas del log
/plan       - Jobs programados (at)
/recalcular - Recalcular y reprogramar salida
/corregir   - Corregir fichaje (ayer, o /corregir DD-MM-YYYY)
/revisar    - Revisar y corregir últimos 7 días laborables
/festivo    - Próximos festivos del calendario
/horario    - Ver perfil de horario activo
/horario listar             - Listar perfiles disponibles
/horario usar <perfil|auto> - Forzar perfil activo
/horario nuevo <n> [meses]  - Crear perfil (ej: /horario nuevo verano 7,8)
/horario set <perfil> <clave> <valor> - Editar un valor
/horario borrar <perfil>    - Borrar perfil
/help       - Este mensaje"""


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


# ── API helpers ───────────────────────────────────────────────────────────

def _api_get(path, token, account_id, base=BASE_APP):
    req = urllib.request.Request(base + path, method="GET")
    req.add_header("token", token)
    req.add_header("accountid", account_id)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return None, {}

def _api_put(path, token, account_id, body, base=BASE_APP):
    data = json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="PUT")
    req.add_header("token", token)
    req.add_header("accountid", account_id)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return None, {}

def _corregir_fecha(date_str, target_min, token, account_id, cfg):
    import urllib.parse
    pausa_dur  = int(cfg.get("PAUSA_DURACION", "60"))
    tz_offset  = datetime.now().astimezone().strftime("%z")
    tz_colon   = tz_offset[:3] + ":" + tz_offset[3:]
    date_param = urllib.parse.quote(f"{date_str}T00:00:00{tz_colon}")

    status, data = _api_get(f"/internal/team/v2/day-timetracking?date={date_param}", token, account_id)
    if status != 200:
        return f"❌ GET {date_str}: status={status}"

    trackers = data.get("trackers", [])
    if not trackers:
        return f"⚪ {date_str}: sin tracker en Holded"

    tracker = trackers[0]
    if not tracker.get("done"):
        return f"⏳ {date_str}: tracker aún en curso"

    end_dt    = datetime.fromisoformat(tracker["end"]).astimezone()
    start_dt  = datetime.fromisoformat(tracker["startDateWithTimeZone"]).astimezone()
    start_min = start_dt.replace(second=0, microsecond=0)

    raw_pauses      = tracker.get("pauses", [])
    total_pause_min = pausa_dur * len(raw_pauses)
    new_end         = start_min + timedelta(minutes=target_min + total_pause_min)

    old_hhmm = end_dt.strftime("%H:%M")
    new_hhmm = new_end.strftime("%H:%M")

    if new_end == end_dt.replace(second=0, microsecond=0):
        return f"✅ {date_str}: {start_dt.strftime('%H:%M')}→{old_hhmm} ({target_min}min) OK"

    delta = round((new_end - end_dt).total_seconds() / 60)

    pauses = []
    for p in raw_pauses:
        p_start = datetime.fromisoformat(p["start"]).astimezone().replace(second=0, microsecond=0)
        p_end   = p_start + timedelta(minutes=pausa_dur)
        pauses.append({"start": p_start.strftime("%H:%M"), "end": p_end.strftime("%H:%M")})

    body = {"trackers": [{
        "id":          tracker["id"],
        "workplaceId": tracker.get("workplaceId"),
        "isRemote":    False,
        "start":       tracker["startDateWithTimeZone"],
        "end":         new_end.isoformat(),
        "pauses":      pauses,
    }]}

    status2, _ = _api_put("/internal/team/v2/bulk-timetracking-update", token, account_id, body)
    if status2 and status2 < 400:
        return f"🔧 {date_str}: {start_dt.strftime('%H:%M')}→{old_hhmm}→{new_hhmm} ({delta:+d}min)"
    else:
        return f"❌ {date_str}: PUT fallido status={status2}"

def cmd_corregir(date_arg=None):
    token, account_id = _read_mmkv()
    if not token or not account_id:
        return "❌ No se pudo leer token de MMKV"

    if date_arg:
        try:
            d = datetime.strptime(date_arg, "%d-%m-%Y").date()
        except ValueError:
            return "❌ Formato incorrecto. Usa: /corregir DD-MM-YYYY (ej: /corregir 11-06-2026)"
    else:
        d = datetime.now().date() - timedelta(days=1)
        while d.isoweekday() >= 6:
            d -= timedelta(days=1)

    if d.isoweekday() >= 6:
        return f"❌ {d} es fin de semana — no hay fichaje que corregir"

    _, cfg   = horario_conf.resolve(mes=d.month)
    horas_lj = int(cfg.get("HORAS_LJ", "480"))
    horas_v  = int(cfg.get("HORAS_V",  "330"))
    target   = horas_lj if d.isoweekday() <= 4 else horas_v
    return _corregir_fecha(d.strftime("%Y-%m-%d"), target, token, account_id, cfg)


def cmd_revisar():
    token, account_id = _read_mmkv()
    if not token or not account_id:
        return "❌ No se pudo leer token de MMKV"

    dias_laborables = []
    d = datetime.now().date() - timedelta(days=1)
    while len(dias_laborables) < 7:
        if d.isoweekday() <= 5:
            dias_laborables.append(d)
        d -= timedelta(days=1)

    lines = ["🔍 Revisión últimos 7 días laborables:"]
    for dia in dias_laborables:
        _, cfg   = horario_conf.resolve(mes=dia.month)
        horas_lj = int(cfg.get("HORAS_LJ", "480"))
        horas_v  = int(cfg.get("HORAS_V",  "330"))
        target   = horas_lj if dia.isoweekday() <= 4 else horas_v
        lines.append(_corregir_fecha(dia.strftime("%Y-%m-%d"), target, token, account_id, cfg))

    return "\n".join(lines)


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
                    try:
                        start_ts = int(start) / 1000
                    except (ValueError, TypeError):
                        start_ts = datetime.fromisoformat(str(start)).timestamp()
                    acum = int((datetime.now(timezone.utc).timestamp() - start_ts) / 60)

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
    if start_ms:
        try:
            start_ms = int(start_ms)
        except (ValueError, TypeError):
            from datetime import timezone as _tz
            start_ms = int(datetime.fromisoformat(str(start_ms)).timestamp() * 1000)
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


def cmd_recalcular():
    plan_file = FICHAJE / "plan.json"
    if not plan_file.exists():
        return "❌ Sin plan.json para hoy"
    try:
        plan = json.loads(plan_file.read_text())
    except Exception:
        return "❌ plan.json corrupto"

    if plan.get("date") != datetime.now().strftime("%Y-%m-%d"):
        return "❌ plan.json no es de hoy"

    actual = plan.get("actual", {})
    entrada_ts = actual.get("ENTRADA_TS")
    if not entrada_ts:
        return "❌ Sin ENTRADA registrada hoy"

    horas_total = plan.get("horas_total", 480)
    inicio_ts   = actual.get("INICIO_PAUSA_TS")
    fin_ts      = actual.get("FIN_PAUSA_TS")

    if inicio_ts and fin_ts:
        pausa_sec = fin_ts - inicio_ts
        inicio_hhmm = datetime.fromtimestamp(inicio_ts).strftime("%H:%M")
        fin_hhmm    = datetime.fromtimestamp(fin_ts).strftime("%H:%M")
        pausa_str = f"{inicio_hhmm}-{fin_hhmm} ({int(pausa_sec // 60)}min)"
    elif inicio_ts:
        inicio_hhmm = datetime.fromtimestamp(inicio_ts).strftime("%H:%M")
        pausa_sec = plan.get("pausa_dur", 0) * 60
        pausa_str = f"{inicio_hhmm}-? (en pausa, {int(pausa_sec // 60)}min plan.)"
    else:
        pausa_sec = plan.get("pausa_dur", 0) * 60
        pausa_str = f"planificada {int(pausa_sec // 60)}min"

    required_ts   = entrada_ts + horas_total * 60 + pausa_sec
    required_dt   = datetime.fromtimestamp(required_ts)
    required_hhmm = required_dt.strftime("%H:%M")
    required_min  = required_dt.hour * 60 + required_dt.minute

    entrada_hhmm  = datetime.fromtimestamp(entrada_ts).strftime("%H:%M")
    current_salida = plan["scheduled"].get("SALIDA", "?")

    def _hhmm_to_min(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    lines = [
        "📊 Recálculo salida:",
        f"🟢 Entrada real : {entrada_hhmm}",
        f"⏸ Pausa        : {pausa_str}",
        f"⏱ Horas        : {horas_total // 60}h{horas_total % 60:02d}m",
        f"🔴 Salida exacta: {required_hhmm}",
    ]

    current_min = _hhmm_to_min(current_salida) if ":" in current_salida else None
    if current_min is not None and current_min != required_min:
        salida_job = plan["jobs"].get("SALIDA")
        if salida_job:
            subprocess.run(["atrm", str(salida_job)], capture_output=True)
        today = datetime.now().strftime("%Y-%m-%d")
        cmd   = f"{PYTHON} {ACCION} SALIDA {horas_total}"
        proc  = subprocess.run(
            ["at", required_hhmm, today],
            input=cmd + "\n",
            capture_output=True, text=True
        )
        m = re.search(r'job (\d+)', proc.stderr)
        if m:
            plan["jobs"]["SALIDA"] = int(m.group(1))
        plan["scheduled"]["SALIDA"] = required_hhmm
        plan_file.write_text(json.dumps(plan))
        lines.append(f"⚠️ Reprogramada: {current_salida} → {required_hhmm}")
    else:
        lines.append("✅ Salida ya correcta")

    return "\n".join(lines)


def cmd_festivo():
    cache = FICHAJE / "ausencias_cache.json"
    ausencias_txt = FICHAJE / "ausencias.txt"

    dias = set()
    if cache.exists():
        try:
            data = json.loads(cache.read_text())
            from datetime import date as _date
            dias = {_date.fromisoformat(d) for d in data.get("dates", [])}
        except Exception:
            pass

    if ausencias_txt.exists():
        from datetime import date as _date
        for line in ausencias_txt.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                parts = line.split("-")
                if len(parts) == 3:
                    dias.add(_date(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

    if not dias:
        return "❌ Sin datos de ausencias/festivos (cache vacía)"

    hoy = datetime.now().date()
    proximos = sorted(d for d in dias if d > hoy and d.weekday() < 5)

    if not proximos:
        return "🤷 Sin festivos laborables próximos en el calendario"

    DIAS_ES  = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    MESES_ES = ["enero","febrero","marzo","abril","mayo","junio",
                "julio","agosto","septiembre","octubre","noviembre","diciembre"]

    def _fmt(d):
        return f"{DIAS_ES[d.weekday()]} {d.day} {MESES_ES[d.month-1]}"

    # Agrupar días consecutivos (tolerancia 3 días para salvar fines de semana)
    bloques = []
    inicio = fin = proximos[0]
    for d in proximos[1:]:
        if (d - fin).days <= 3:
            fin = d
        else:
            bloques.append((inicio, fin))
            inicio = fin = d
    bloques.append((inicio, fin))

    lines = ["📅 Próximos festivos:"]
    for ini, fin in bloques[:5]:
        dias_para = (ini - hoy).days
        cuando = f"en {dias_para} día{'s' if dias_para != 1 else ''}"
        if ini == fin:
            lines.append(f"  {_fmt(ini)} {ini.year} ({cuando})")
        else:
            n_lab = sum(1 for d in proximos if ini <= d <= fin)
            lines.append(f"  {_fmt(ini)} → {_fmt(fin)} {fin.year} — {n_lab} días laborables ({cuando})")

    return "\n".join(lines)


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


def cmd_horario(args):
    if not args:
        nombre, cfg = horario_conf.resolve()
        forced = horario_conf.active_override()
        modo = "forzado" if forced else "automático (mes actual)"
        lines = [f"⚙️ Perfil activo: {nombre} ({modo})", ""]
        for k in ("ENTRADA_BASE", "ENTRADA_VARIACION", "PAUSA_BASE",
                  "PAUSA_VARIACION", "PAUSA_DURACION", "HORAS_LJ", "HORAS_V"):
            lines.append(f"  {k} = {cfg.get(k, '?')}")
        return "\n".join(lines)

    sub = args[0].lower()

    if sub == "listar":
        activo, _ = horario_conf.resolve()
        lines = ["📋 Perfiles:"]
        for nombre, meses in horario_conf.listar():
            meses_str = ",".join(str(m) for m in meses) if meses else "-"
            marca = " ← activo" if nombre == activo else ""
            lines.append(f"  {nombre}  meses={meses_str}{marca}")
        return "\n".join(lines)

    if sub == "usar":
        if len(args) < 2:
            return "❌ Uso: /horario usar <perfil|auto>"
        try:
            horario_conf.set_active(args[1])
        except ValueError as e:
            return f"❌ {e}"
        return f"✅ Perfil activo forzado a: {args[1]}"

    if sub == "nuevo":
        if len(args) < 2:
            return "❌ Uso: /horario nuevo <nombre> [meses, ej: 7,8]"
        try:
            horario_conf.crear_perfil(args[1], args[2] if len(args) > 2 else None)
        except ValueError as e:
            return f"❌ {e}"
        return f"✅ Perfil creado: {args[1]}"

    if sub == "borrar":
        if len(args) < 2:
            return "❌ Uso: /horario borrar <perfil>"
        try:
            horario_conf.borrar_perfil(args[1])
        except ValueError as e:
            return f"❌ {e}"
        return f"✅ Perfil borrado: {args[1]}"

    if sub == "set":
        if len(args) < 4:
            return "❌ Uso: /horario set <perfil> <clave> <valor>"
        try:
            valor_ok = horario_conf.set_value(args[1], args[2], args[3])
        except ValueError as e:
            return f"❌ {e}"
        return f"✅ {args[1]}.{args[2]} = {valor_ok}"

    return "❌ Subcomando desconocido. Usa: /horario [listar|usar|nuevo|borrar|set]"


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
    elif cmd == "/recalcular":
        reply(cmd_recalcular())
    elif cmd == "/corregir":
        parts = text.strip().split()
        reply(cmd_corregir(parts[1] if len(parts) > 1 else None))
    elif cmd == "/revisar":
        reply(cmd_revisar())
    elif cmd == "/festivo":
        reply(cmd_festivo())
    elif cmd == "/horario":
        reply(cmd_horario(text.strip().split()[1:]))
    elif cmd in ("/help", "/start", "/ayuda"):
        reply(_help_text())
    else:
        reply(f"Comando desconocido: {cmd}\n\n{_help_text()}")


# ── Main ──────────────────────────────────────────────────────────────────

import time as _time

PID_FILE = FICHAJE / "bot.pid"

def _already_running():
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        Path(f"/proc/{pid}").stat()
        return pid != os.getpid()
    except Exception:
        return False

def _process_updates(updates, offset):
    for upd in updates["result"]:
        new_offset = upd["update_id"] + 1
        if new_offset > offset:
            offset = new_offset
        msg     = upd.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text    = msg.get("text", "")
        if chat_id == TG_CHAT_ID and text.startswith("/"):
            handle(text)
    return offset

if _already_running():
    sys.exit(0)

PID_FILE.write_text(str(os.getpid()))

try:
    offset = int(OFFSET.read_text()) if OFFSET.exists() else 0
    while True:
        updates = tg_get(f"getUpdates?offset={offset}&timeout=30&allowed_updates=%5B%22message%22%5D")
        if updates and updates.get("ok"):
            offset = _process_updates(updates, offset)
            OFFSET.write_text(str(offset))
        else:
            _time.sleep(5)
finally:
    try:
        PID_FILE.unlink()
    except Exception:
        pass
