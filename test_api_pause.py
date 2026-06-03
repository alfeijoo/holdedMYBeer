#!/data/data/com.termux/files/usr/bin/python3
"""
Prueba a ciegas de endpoints pause/resume.
Ejecutar con timer activo (despues de clock-in manual).
Uso: python3 test_api_pause.py
"""

import subprocess
import json
import urllib.request
import urllib.error
import os
import sys

ADB_HOST = "127.0.0.1:5555"
ADB_KEYS  = "/data/data/com.termux/files/home/.android/adbkey"
BASE_MOBILE = "https://mobile.holded.com"
BASE_APP    = "https://app.holded.com"

os.environ["ADB_VENDOR_KEYS"] = ADB_KEYS
os.environ["PATH"] = "/data/data/com.termux/files/usr/bin:" + os.environ.get("PATH", "")


def adb_shell(*args):
    return subprocess.run(
        ["adb", "-s", ADB_HOST, "shell", *args],
        capture_output=True, text=True
    )


def extract_token():
    r = adb_shell("strings", "/data/data/com.holded.app/files/mmkv/mmkv.default")
    lines = r.stdout.splitlines()
    token = account_id = None
    for i, line in enumerate(lines):
        if line == "bg_session_token" and i + 1 < len(lines):
            token = lines[i + 1]
        if line == "bg_session_account_id" and i + 1 < len(lines):
            account_id = lines[i + 1][:24]
    return token, account_id


def api(method, base, path, token, account_id, body=None):
    url = base + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("token", token)
    req.add_header("accountid", account_id)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode()
            return resp.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, str(e)


def get_tracker(token, account_id):
    status, body = api("GET", BASE_MOBILE, "/internal/team/employee/current/tracker", token, account_id)
    print(f"GET tracker → {status}: {body}")
    if status == 200 and body and body != "null":
        try:
            return json.loads(body)
        except Exception:
            pass
    return None


def try_pause(token, account_id, tracker):
    tracker_id = tracker.get("_id") or tracker.get("id") or tracker.get("trackerId")
    print(f"\ntracker_id detectado: {tracker_id}")
    print(f"tracker completo: {json.dumps(tracker, indent=2)}")

    candidates = [
        (BASE_MOBILE, "/internal/team/tracker/pause", {"trackerId": tracker_id}),
        (BASE_APP,    "/internal/team/tracker/pause", {"trackerId": tracker_id}),
        (BASE_MOBILE, "/internal/team/tracker/pause", {"id": tracker_id}),
        (BASE_APP,    "/internal/team/tracker/pause", {"id": tracker_id}),
        (BASE_MOBILE, "/internal/team/tracker/pause", {}),
    ]

    for base, path, body in candidates:
        print(f"\nPOST {base}{path} body={body}")
        status, resp = api("POST", base, path, token, account_id, body)
        print(f"  → {status}: {resp}")
        if status and status < 400:
            print("  *** EXITO ***")
            return True

    return False


def try_resume(token, account_id, tracker_id):
    candidates = [
        (BASE_MOBILE, "/internal/team/tracker/resume", {"trackerId": tracker_id}),
        (BASE_APP,    "/internal/team/tracker/resume", {"trackerId": tracker_id}),
        (BASE_MOBILE, "/internal/team/tracker/resume", {"id": tracker_id}),
        (BASE_APP,    "/internal/team/tracker/resume", {"id": tracker_id}),
        (BASE_MOBILE, "/internal/team/tracker/resume", {}),
    ]

    for base, path, body in candidates:
        print(f"\nPOST {base}{path} body={body}")
        status, resp = api("POST", base, path, token, account_id, body)
        print(f"  → {status}: {resp}")
        if status and status < 400:
            print("  *** EXITO ***")
            return True

    return False


print("=== Extrayendo token de MMKV ===")
token, account_id = extract_token()
if not token or not account_id:
    print("ERROR: no se pudo extraer token. ¿ADB conectado?")
    sys.exit(1)
print(f"token: {token[:30]}...")
print(f"account_id: {account_id}")

print("\n=== Estado del tracker ===")
tracker = get_tracker(token, account_id)
if not tracker:
    print("Timer no activo. Inicia el timer manualmente y vuelve a ejecutar.")
    sys.exit(1)

tracker_id = tracker.get("_id") or tracker.get("id") or tracker.get("trackerId")

print("\n=== Probando PAUSE ===")
ok = try_pause(token, account_id, tracker)

if ok:
    input("\nPausa aplicada. Pulsa Enter para probar RESUME...")
    print("\n=== Probando RESUME ===")
    try_resume(token, account_id, tracker_id)
