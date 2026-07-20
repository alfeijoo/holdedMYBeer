"""
Resolver de perfiles de horario (horario.conf) - compartido por accion.py, maestro.py, bot.py.

Formato: INI con secciones. [DEFAULT] son los valores base, heredados por
cualquier otra seccion (perfil). Cada perfil solo declara lo que cambia.
MESES = lista de meses (1-12) en que el perfil se activa automaticamente.
Un override manual (horario_active.txt) fuerza un perfil sin importar el mes.
"""

import re
import configparser
from pathlib import Path
from datetime import datetime

FICHAJE     = Path(__file__).resolve().parent
CONF_FILE   = FICHAJE / "horario.conf"
ACTIVE_FILE = FICHAJE / "horario_active.txt"

CLAVES_EDITABLES = (
    "ENTRADA_BASE", "ENTRADA_VARIACION",
    "PAUSA_BASE", "PAUSA_VARIACION", "PAUSA_DURACION", "PAUSA_VIERNES",
    "HORAS_LJ", "HORAS_V", "MESES",
)

_HEADER = (
    "# Horario de trabajo - Fichaje Holded\n"
    "# [DEFAULT] = valores base, heredados por cualquier otro perfil.\n"
    "# Cada perfil adicional solo declara lo que cambia respecto a DEFAULT.\n"
    "# MESES = lista de meses (1-12) en que el perfil se activa automaticamente.\n"
    "# Override manual: /horario usar <perfil|auto> en Telegram.\n"
)


def _parser():
    cp = configparser.ConfigParser()
    cp.optionxform = str  # preserva mayusculas en las claves
    cp.read(CONF_FILE)
    return cp


def _write(cp):
    with open(CONF_FILE, "w") as f:
        f.write(_HEADER + "\n")
        cp.write(f)


def _meses_de(cp, seccion):
    raw = cp[seccion].get("MESES", "") if seccion in cp else ""
    if not raw.strip():
        return []
    return sorted(int(x) for x in raw.split(",") if x.strip())


def active_override():
    if ACTIVE_FILE.exists():
        val = ACTIVE_FILE.read_text().strip()
        return val if val and val != "auto" else None
    return None


def set_active(nombre):
    if nombre == "auto":
        if ACTIVE_FILE.exists():
            ACTIVE_FILE.unlink()
        return
    cp = _parser()
    if nombre != "DEFAULT" and nombre not in cp.sections():
        raise ValueError(f"Perfil desconocido: {nombre}")
    ACTIVE_FILE.write_text(nombre)


def resolve(mes=None):
    """Devuelve (nombre_perfil, dict_config) del perfil activo."""
    cp = _parser()
    mes = mes or datetime.now().month
    forced = active_override()
    if forced and (forced == "DEFAULT" or forced in cp.sections()):
        nombre = forced
    else:
        nombre = None
        for s in cp.sections():
            if mes in _meses_de(cp, s):
                nombre = s
                break
        nombre = nombre or "DEFAULT"
    seccion = cp["DEFAULT"] if nombre == "DEFAULT" else cp[nombre]
    return nombre, dict(seccion)


def listar():
    """Lista (nombre, meses) de DEFAULT + todos los perfiles."""
    cp = _parser()
    out = [("DEFAULT", _meses_de(cp, "DEFAULT"))]
    for s in cp.sections():
        out.append((s, _meses_de(cp, s)))
    return out


def crear_perfil(nombre, meses=None):
    if not re.match(r'^[A-Za-z0-9_]+$', nombre) or nombre == "DEFAULT":
        raise ValueError("Nombre de perfil invalido (solo letras/numeros/_, no 'DEFAULT')")
    cp = _parser()
    if nombre in cp.sections():
        raise ValueError(f"Perfil ya existe: {nombre}")
    cp.add_section(nombre)
    if meses:
        cp[nombre]["MESES"] = validar("MESES", meses)
    _write(cp)


def borrar_perfil(nombre):
    if nombre == "DEFAULT":
        raise ValueError("No se puede borrar DEFAULT")
    cp = _parser()
    if nombre not in cp.sections():
        raise ValueError(f"Perfil desconocido: {nombre}")
    cp.remove_section(nombre)
    _write(cp)
    if active_override() == nombre:
        set_active("auto")


def validar(clave, valor):
    """Valida y normaliza un valor. Lanza ValueError si es invalido."""
    valor = valor.strip()
    if clave in ("ENTRADA_BASE", "PAUSA_BASE"):
        if not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', valor):
            raise ValueError(f"{clave} debe ser HH:MM (ej: 08:00)")
        return valor
    if clave in ("ENTRADA_VARIACION", "PAUSA_VARIACION", "PAUSA_DURACION", "HORAS_LJ", "HORAS_V"):
        if not re.match(r'^\d+$', valor) or not (0 <= int(valor) <= 1440):
            raise ValueError(f"{clave} debe ser un numero entre 0 y 1440")
        return valor
    if clave == "PAUSA_VIERNES":
        v = valor.lower()
        if v in ("si", "s", "true", "1", "yes"):
            return "si"
        if v in ("no", "n", "false", "0"):
            return "no"
        raise ValueError("PAUSA_VIERNES debe ser si/no")
    if clave == "MESES":
        try:
            nums = sorted(set(int(x) for x in valor.split(",") if x.strip()))
        except ValueError:
            raise ValueError("MESES debe ser una lista de numeros 1-12 separados por comas")
        if not nums or any(n < 1 or n > 12 for n in nums):
            raise ValueError("MESES debe ser una lista de numeros 1-12 separados por comas")
        return ",".join(str(n) for n in nums)
    raise ValueError(f"Clave no editable: {clave}")


def set_value(perfil, clave, valor):
    clave = clave.strip().upper()
    if clave not in CLAVES_EDITABLES:
        raise ValueError(f"Clave no editable: {clave}. Validas: {', '.join(CLAVES_EDITABLES)}")
    valor_ok = validar(clave, valor)
    cp = _parser()
    if perfil != "DEFAULT" and perfil not in cp.sections():
        raise ValueError(f"Perfil desconocido: {perfil}")
    cp[perfil][clave] = valor_ok
    _write(cp)
    return valor_ok
