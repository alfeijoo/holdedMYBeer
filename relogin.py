#!/data/data/com.termux/files/usr/bin/python3
"""
Automatiza el re-login en Holded via ADB cuando la sesion ha caducado.
Ejecutar desde Termux: python3 ~/holdedMYBeer/relogin.py
"""

import sys
import os
import subprocess
import time
import re
import json
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ADB_HOST  = "127.0.0.1:5555"
ADB_KEYS  = "/data/data/com.termux/files/home/.android/adbkey"
MMKV_PATH = "/data/data/com.holded.app/files/mmkv/mmkv.default"
TMP_XML   = "/data/local/tmp/holded_ui.xml"
CONF_PATH = "/data/data/com.termux/files/home/holdedMYBeer/horario.conf"

os.environ["ADB_VENDOR_KEYS"] = ADB_KEYS
os.environ["PATH"] = "/data/data/com.termux/files/usr/bin:" + os.environ.get("PATH", "")

def _load_conf():
    cfg = {}
    try:
        for line in open(CONF_PATH).read().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"')
    except Exception:
        pass
    return cfg

_CONF          = _load_conf()
UNLOCK_PIN     = _CONF.get("UNLOCK_PIN", "0000")
GOOGLE_ACCOUNT = _CONF.get("GOOGLE_ACCOUNT", "")
HOLDED_COMPANY = _CONF.get("HOLDED_COMPANY", "")


def adb(*args):
    return subprocess.run(["adb", "-s", ADB_HOST, *args], capture_output=True, text=True)

def shell(*args):
    return adb("shell", *args)

def tap(x, y):
    shell("input", "tap", str(x), str(y))
    time.sleep(2)

def dump_ui():
    shell("uiautomator", "dump", "--compressed", TMP_XML)
    r = shell("cat", TMP_XML)
    try:
        return ET.fromstring(r.stdout)
    except ET.ParseError:
        return None

def find_node(root, text=None, content_desc=None, partial=False):
    for node in root.iter("node"):
        t = node.get("text", "")
        d = node.get("content-desc", "")
        if text:
            match = text.lower() in t.lower() if partial else t == text
        elif content_desc:
            match = content_desc.lower() in d.lower() if partial else d == content_desc
        else:
            match = False
        if match:
            return node
    return None

def node_center(node):
    b = node.get("bounds", "")
    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', b)
    if m:
        x1, y1, x2, y2 = map(int, m.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2
    return None

def tap_node(root, text=None, content_desc=None, partial=False, label=""):
    node = find_node(root, text=text, content_desc=content_desc, partial=partial)
    if node is None:
        print(f"  [!] No encontrado: {label or text or content_desc}")
        return False
    xy = node_center(node)
    if xy is None:
        print(f"  [!] Sin bounds: {label or text or content_desc}")
        return False
    print(f"  tap {xy} → {label or text or content_desc}")
    tap(*xy)
    return True

def read_token():
    r = shell("strings", MMKV_PATH)
    lines = r.stdout.splitlines()
    token = account_id = None
    for i, line in enumerate(lines):
        if line == "bg_session_token" and i + 1 < len(lines):
            token = lines[i + 1]
        if line == "bg_session_account_id" and i + 1 < len(lines):
            account_id = lines[i + 1][:24]
    return token, account_id

def token_exp(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.b64decode(payload))["exp"]
    except Exception:
        return None


print("=== Holded Re-Login ===\n")

# Token antes
token_before, _ = read_token()
exp_before = token_exp(token_before) if token_before else None

# 1. Despertar y desbloquear
print("[1] Despertando y desbloqueando...")
shell("input", "keyevent", "224")
time.sleep(1)
shell("input", "swipe", "720", "1800", "720", "900", "300")
time.sleep(1)
shell("input", "text", UNLOCK_PIN)
time.sleep(0.5)
shell("input", "keyevent", "66")
time.sleep(1)

# 2. Abrir Holded
print("[2] Abriendo Holded...")
shell("am", "start", "-n", "com.holded.app/com.holded.MainActivity")
time.sleep(4)

# 3. Tap "Iniciar sesión con Google"
print("[3] Buscando botón Google...")
root = dump_ui()
if root is None:
    print("  [!] No se pudo leer UI")
    exit(1)
if not tap_node(root, content_desc="Iniciar sesión con Google", label="Iniciar sesión con Google"):
    sys.exit(1)
time.sleep(3)

# 4. Seleccionar cuenta
print(f"[4] Seleccionando cuenta {GOOGLE_ACCOUNT}...")
root = dump_ui()
if root is None:
    print("  [!] No se pudo leer UI")
    exit(1)
if not tap_node(root, text=GOOGLE_ACCOUNT, label=GOOGLE_ACCOUNT):
    sys.exit(1)
time.sleep(4)

# 5. Seleccionar empresa
print(f"[5] Seleccionando {HOLDED_COMPANY}...")
root = dump_ui()
if root is None:
    print("  [!] No se pudo leer UI")
    exit(1)
if not tap_node(root, text=HOLDED_COMPANY, partial=True, label=HOLDED_COMPANY):
    sys.exit(1)
time.sleep(6)

# 6. Volver a home y bloquear pantalla
print("[6] Volviendo a home y bloqueando pantalla...")
shell("input", "keyevent", "3")
time.sleep(1)
shell("input", "keyevent", "26")

# 7. Leer nuevo token
print("[7] Leyendo nuevo token de MMKV...")
token_new, account_id = read_token()
exp_new = token_exp(token_new) if token_new else None

if not token_new:
    print("\n  [!] No se pudo leer token nuevo")
    sys.exit(1)

if exp_new and exp_before and exp_new > exp_before:
    exp_dt = datetime.fromtimestamp(exp_new, tz=timezone.utc).strftime("%Y-%m-%d")
    print(f"\n  Token renovado correctamente")
    print(f"  account_id : {account_id}")
    print(f"  expira     : {exp_dt}")
    print(f"  token      : {token_new[:40]}...")
else:
    print("\n  Token con misma expiracion — sesion ya era valida")
