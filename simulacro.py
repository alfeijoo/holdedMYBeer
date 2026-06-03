#!/data/data/com.termux/files/usr/bin/python3
"""
Simulacro completo: ENTRADA -> INICIO_PAUSA -> FIN_PAUSA -> SALIDA
Uso: simulacro.py [ESPERA_SEGUNDOS]
"""

import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

HOME    = Path("/data/data/com.termux/files/home")
FICHAJE = HOME / "holdedMYBeer"
LOG     = FICHAJE / "holdmybeer.log"
ACCION  = FICHAJE / "accion.py"
PYTHON  = "/data/data/com.termux/files/usr/bin/python3"

ESPERA     = int(sys.argv[1]) if len(sys.argv) > 1 else 8
ACUM_PAUSA = 182
TOTAL      = 480

def run(nombre, action, acum):
    print(f"-- [{nombre}] {datetime.now().strftime('%H:%M:%S')} --")
    r = subprocess.run([PYTHON, str(ACCION), action, str(acum)])
    print(f"   {'OK' if r.returncode == 0 else f'ERROR (exit {r.returncode})'}\n")

print("=" * 44)
print(f"SIMULACRO - {datetime.now().strftime('%A %d %b %Y %H:%M:%S')}")
print(f"Espera entre acciones: {ESPERA}s")
print(f"Acumulado pausa: {ACUM_PAUSA}min | Total: {TOTAL}min")
print("=" * 44 + "\n")

run("1/4 ENTRADA",      "ENTRADA",      0)
print(f"Esperando {ESPERA}s...\n"); time.sleep(ESPERA)

run("2/4 INICIO_PAUSA", "INICIO_PAUSA", ACUM_PAUSA)
print(f"Esperando {ESPERA}s...\n"); time.sleep(ESPERA)

run("3/4 FIN_PAUSA",    "FIN_PAUSA",    ACUM_PAUSA)
print(f"Esperando {ESPERA}s...\n"); time.sleep(ESPERA)

run("4/4 SALIDA",       "SALIDA",       TOTAL)

print("=" * 44)
print(f"SIMULACRO COMPLETADO - {datetime.now().strftime('%H:%M:%S')}\n")
print("Ultimas lineas del log:")
if LOG.exists():
    lines = LOG.read_text().splitlines()
    print("\n".join(lines[-20:]))
print("=" * 44)
