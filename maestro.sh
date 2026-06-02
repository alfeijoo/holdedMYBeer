#!/data/data/com.termux/files/usr/bin/bash
# Ejecutado por cron a las 23:00 cada noche.
# Calcula tiempos aleatorios del dia siguiente y los programa con at.
export PATH=/data/data/com.termux/files/usr/bin:$PATH
export ADB_VENDOR_KEYS=$HOME/.android/adbkey

LOG="$HOME/fichaje/fichaje_simulacion.log"
AUSENCIAS="$HOME/fichaje/ausencias.txt"
ACCION="$HOME/fichaje/accion.sh"
CONFIG="$HOME/fichaje/horario.conf"
UI_DUMP="/data/local/tmp/holded_ausencias.xml"

# ── Helpers ──────────────────────────────────────────────────────────────

min_to_hhmm() {
    local m=$1
    printf "%02d:%02d" $((m / 60)) $((m % 60))
}

hhmm_to_min() {
    local h m
    h=$(echo "$1" | cut -d: -f1)
    m=$(echo "$1" | cut -d: -f2)
    echo $(( 10#$h * 60 + 10#$m ))
}

mes_abrev() {
    case "$1" in
        1) echo "ene" ;; 2) echo "feb" ;; 3) echo "mar" ;; 4) echo "abr" ;;
        5) echo "may" ;; 6) echo "jun" ;; 7) echo "jul" ;; 8) echo "ago" ;;
        9) echo "sep" ;; 10) echo "oct" ;; 11) echo "nov" ;; 12) echo "dic" ;;
    esac
}

mes_num() {
    case $(echo "$1" | tr '[:upper:]' '[:lower:]') in
        ene|jan|enero)       echo 1 ;;
        feb|febrero)         echo 2 ;;
        mar|marzo)           echo 3 ;;
        abr|apr|abril)       echo 4 ;;
        may|mayo)            echo 5 ;;
        jun|junio)           echo 6 ;;
        jul|julio)           echo 7 ;;
        ago|aug|agosto)      echo 8 ;;
        sep|septiembre)      echo 9 ;;
        oct|octubre)         echo 10 ;;
        nov|noviembre)       echo 11 ;;
        dic|dec|diciembre)   echo 12 ;;
        *)                   echo 0 ;;
    esac
}

fecha_humana() {
    local dow=$1 dia=$2 mon=$3
    local dname
    case "$dow" in
        1) dname="Lunes" ;; 2) dname="Martes" ;; 3) dname="Miercoles" ;;
        4) dname="Jueves" ;; 5) dname="Viernes" ;; 6) dname="Sabado" ;; 7) dname="Domingo" ;;
    esac
    echo "$dname $dia $(mes_abrev $mon) $(date +%Y)"
}

log() {
    local fh=$(fecha_humana $(date +%u) $(date +%-d) $(date +%-m))
    echo "[$fh] [$(date +%H:%M)] [MAESTRO] $*" >> "$LOG"
}

err() {
    local fh=$(fecha_humana $(date +%u) $(date +%-d) $(date +%-m))
    echo "[$fh] [$(date +%H:%M)] [MAESTRO] [ERROR] $*" >> "$LOG"
}

# ── Cargar configuracion ──────────────────────────────────────────────────

ENTRADA_BASE="08:00"
ENTRADA_VARIACION=16
PAUSA_BASE="13:00"
PAUSA_VARIACION=60
PAUSA_DURACION=60
HORAS_LJ=480
HORAS_V=330

if [ -f "$CONFIG" ]; then
    # shellcheck source=/dev/null
    . "$CONFIG"
fi

ENTRADA_BASE_MIN=$(hhmm_to_min "$ENTRADA_BASE")
PAUSA_BASE_MIN=$(hhmm_to_min "$PAUSA_BASE")

# ── ADB helper ────────────────────────────────────────────────────────────

adb_ok() {
    adb -s 127.0.0.1:5555 shell echo ok 2>/dev/null | grep -q ok
}

adb_connect() {
    adb_ok && return 0
    adb connect 127.0.0.1:5555 2>/dev/null && sleep 2
    adb_ok && return 0
    adb tcpip 5555 2>/dev/null && sleep 3
    adb connect 127.0.0.1:5555 2>/dev/null && sleep 2
    adb_ok
}

ADB="adb -s 127.0.0.1:5555 shell"

# ── Resolucion y helpers de tap escalado ─────────────────────────────────
# Se detectan dentro de es_ausencia_holded() cuando ADB ya esta conectado.
_tap() {
    # Uso: _tap BASE_X BASE_Y  (requiere SW/SH definidos)
    local x=$(( $1 * SW / 1440 ))
    local y=$(( $2 * SH / 3040 ))
    $ADB input tap "$x" "$y"
}

_swipe_b() {
    local x1=$(( $1 * SW / 1440 )) y1=$(( $2 * SH / 3040 ))
    local x2=$(( $3 * SW / 1440 )) y2=$(( $4 * SH / 3040 ))
    $ADB input swipe "$x1" "$y1" "$x2" "$y2" "$5"
}

# ── Fecha de manana ───────────────────────────────────────────────────────

TOMORROW=$(date -d "tomorrow" +%Y-%m-%d)
T_DAY=$(date -d "tomorrow" +%-d)
T_MON=$(date -d "tomorrow" +%-m)
T_DOW=$(date -d "tomorrow" +%u)
T_MMDD=$((T_MON * 100 + T_DAY))

case "$T_DOW" in
    1) T_DNAME="Lunes" ;;   2) T_DNAME="Martes" ;;  3) T_DNAME="Miercoles" ;;
    4) T_DNAME="Jueves" ;;  5) T_DNAME="Viernes" ;; 6) T_DNAME="Sabado" ;;
    7) T_DNAME="Domingo" ;;
esac

log "Planificando $TOMORROW ($T_DNAME)"

# ── Fin de semana ─────────────────────────────────────────────────────────

if [ "$T_DOW" -ge 6 ]; then
    log "$T_DNAME: no se trabaja. Nada programado."
    exit 0
fi

# ── Funcion comun: chequear si T_MMDD cae en una linea de ausencia ────────

linea_es_ausencia() {
    local linea="$1"
    linea=$(echo "$linea" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [ -z "$linea" ] && return 1
    echo "$linea" | grep -q '^#' && return 1

    if echo "$linea" | grep -q ' - '; then
        local inicio fin ini_d ini_m fin_d fin_m ini_mmdd fin_mmdd
        inicio=$(echo "$linea" | sed 's/ -.*//')
        fin=$(echo "$linea" | sed 's/.*- //')
        ini_d=$(echo "$inicio" | awk '{print $1}')
        ini_m=$(mes_num "$(echo "$inicio" | awk '{print $2}')")
        fin_d=$(echo "$fin" | awk '{print $1}')
        fin_m=$(mes_num "$(echo "$fin" | awk '{print $2}')")
        ini_mmdd=$((ini_m * 100 + ini_d))
        fin_mmdd=$((fin_m * 100 + fin_d))
        [ "$T_MMDD" -ge "$ini_mmdd" ] && [ "$T_MMDD" -le "$fin_mmdd" ] && return 0
    else
        local aus_d aus_m
        aus_d=$(echo "$linea" | awk '{print $1}')
        aus_m=$(mes_num "$(echo "$linea" | awk '{print $2}')")
        [ "$aus_d" -eq "$T_DAY" ] && [ "$aus_m" -eq "$T_MON" ] && return 0
    fi
    return 1
}

# ── Verificar ausencias en Holded (fuente primaria) ───────────────────────

es_ausencia_holded() {
    if ! adb_connect; then
        err "ADB no disponible, saltando lectura de Holded. Usando solo ausencias.txt."
        return 1
    fi

    # Detectar resolucion real para escalar taps
    local SCREEN_SIZE
    SCREEN_SIZE=$($ADB wm size 2>/dev/null | grep -o '[0-9]*x[0-9]*' | tail -1)
    SW=$(echo "$SCREEN_SIZE" | cut -dx -f1); : "${SW:=1440}"
    SH=$(echo "$SCREEN_SIZE" | cut -dx -f2); : "${SH:=3040}"

    # Despertar, desbloquear (sin PIN), ir a home y abrir Holded
    $ADB input keyevent 224 2>/dev/null       # encender pantalla
    sleep 1
    _swipe_b 720 1800 720 900 300             # swipe up para desbloquear
    sleep 1
    $ADB input keyevent 3 2>/dev/null          # HOME
    sleep 1
    $ADB am start -n com.holded.app/com.holded.MainActivity 2>/dev/null
    sleep 5
    $ADB input keyevent 3 2>/dev/null          # HOME (por si quedo algun panel)
    sleep 1
    $ADB am start -n com.holded.app/com.holded.MainActivity 2>/dev/null
    sleep 3
    _tap 720 1460                              # "Proxima ausencia"
    sleep 3
    _tap 211 361                               # icono "Vista lista"
    sleep 4

    # Desactivar animaciones para uiautomator
    $ADB settings put global window_animation_scale 0 2>/dev/null
    $ADB settings put global transition_animation_scale 0 2>/dev/null
    $ADB settings put global animator_duration_scale 0 2>/dev/null
    sleep 1

    # Dump UI y leer
    $ADB uiautomator dump --compressed "$UI_DUMP" 2>/dev/null
    local xml_content
    xml_content=$($ADB cat "$UI_DUMP" 2>/dev/null)

    # Restaurar animaciones y volver al inicio
    $ADB settings put global window_animation_scale 1 2>/dev/null
    $ADB settings put global transition_animation_scale 1 2>/dev/null
    $ADB settings put global animator_duration_scale 1 2>/dev/null
    $ADB input keyevent 4 2>/dev/null
    sleep 1
    $ADB input keyevent 4 2>/dev/null
    sleep 1

    if [ -z "$xml_content" ]; then
        err "No se pudo obtener UI de Holded. Usando solo ausencias.txt."
        return 1
    fi

    # Extraer fechas del listado en dos formatos:
    # 1) Combinado: "24 Jun", "4 Sept", "3 Nov - 20 Nov"  (ausencias personales)
    # 2) Separado:  "15" + "AUG" en elementos distintos   (festivos nacionales)
    local raw_texts
    raw_texts=$(echo "$xml_content" | grep -o 'text="[^"]*"' | sed 's/text="//;s/"//')

    local combinadas separadas
    combinadas=$(echo "$raw_texts" \
        | grep -iE '^[0-9]+ (ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic|jan|aug|dec)' \
        | sed 's/ → / - /')

    # Patron: dia - (tipo: Festivo/Vacaciones) - MES  (hasta 2 elementos entre medio)
    separadas=$(echo "$raw_texts" | awk '
        /^[0-9]+$/ { day=$0; gap=0; next }
        day != "" && /^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)$/ {
            print day " " $0; day=""; gap=0; next
        }
        day != "" && gap < 2 { gap++; next }
        { day=""; gap=0 }
    ' | sed 'y/ABCDEFGHIJKLMNOPQRSTUVWXYZ/abcdefghijklmnopqrstuvwxyz/')

    local ausencias_holded
    ausencias_holded=$(printf '%s\n%s\n' "$combinadas" "$separadas" | grep -v '^$' | sort -u)

    if [ -z "$ausencias_holded" ]; then
        log "Holded: no se encontraron ausencias en la lista."
        return 1
    fi

    log "Holded: ausencias detectadas: $(echo "$ausencias_holded" | tr '\n' '|')"

    while IFS= read -r linea; do
        [ -z "$linea" ] && continue
        if linea_es_ausencia "$linea"; then
            return 0
        fi
    done <<< "$ausencias_holded"

    return 1
}

# ── Verificar ausencias en fichero (fuente secundaria) ───────────────────

es_ausencia_fichero() {
    [ ! -f "$AUSENCIAS" ] && return 1
    while IFS= read -r linea || [ -n "$linea" ]; do
        linea_es_ausencia "$linea" && return 0
    done < "$AUSENCIAS"
    return 1
}

# ── Comprobar ambas fuentes ───────────────────────────────────────────────

if es_ausencia_holded; then
    log "$TOMORROW: AUSENCIA detectada en Holded. Nada programado."
    exit 0
fi

if es_ausencia_fichero; then
    log "$TOMORROW: AUSENCIA detectada en ausencias.txt. Nada programado."
    exit 0
fi

# ── Calcular tiempos ──────────────────────────────────────────────────────

ENTRADA_MIN=$((ENTRADA_BASE_MIN + RANDOM % (ENTRADA_VARIACION + 1)))

if [ "$T_DOW" -le 4 ]; then
    PAUSA_INI_MIN=$((PAUSA_BASE_MIN + RANDOM % (PAUSA_VARIACION + 1)))
    PAUSA_FIN_MIN=$((PAUSA_INI_MIN + PAUSA_DURACION))
    SALIDA_MIN=$((ENTRADA_MIN + HORAS_LJ + PAUSA_DURACION))
    TRABAJADO=$((SALIDA_MIN - ENTRADA_MIN - PAUSA_DURACION))
    if [ "$TRABAJADO" -ne "$HORAS_LJ" ]; then
        err "Verificacion L-J: trabajado=${TRABAJADO}min esperado=${HORAS_LJ}min. Abortando."
        exit 1
    fi
    TOTAL_MIN=$HORAS_LJ
    TIPO="L-J ($(( HORAS_LJ / 60 ))h)"
else
    SALIDA_MIN=$((ENTRADA_MIN + HORAS_V))
    TRABAJADO=$((SALIDA_MIN - ENTRADA_MIN))
    if [ "$TRABAJADO" -ne "$HORAS_V" ]; then
        err "Verificacion V: trabajado=${TRABAJADO}min esperado=${HORAS_V}min. Abortando."
        exit 1
    fi
    TOTAL_MIN=$HORAS_V
    TIPO="Viernes ($(( HORAS_V / 60 ))h$(( HORAS_V % 60 ))m)"
fi

# ── Formatear y loguear plan ──────────────────────────────────────────────

H_ENTRADA=$(min_to_hhmm $ENTRADA_MIN)
H_SALIDA=$(min_to_hhmm $SALIDA_MIN)

log "Plan $TOMORROW ($T_DNAME / $TIPO)"
log "  ENTRADA : $H_ENTRADA"

if [ "$T_DOW" -le 4 ]; then
    H_PAUSA_INI=$(min_to_hhmm $PAUSA_INI_MIN)
    H_PAUSA_FIN=$(min_to_hhmm $PAUSA_FIN_MIN)
    ACUM_PAUSA=$((PAUSA_INI_MIN - ENTRADA_MIN))
    log "  PAUSA   : $H_PAUSA_INI - $H_PAUSA_FIN (${PAUSA_DURACION}min)"
fi

log "  SALIDA  : $H_SALIDA"
log "  TOTAL   : ${TOTAL_MIN}min verificado OK"

# ── Programar con at ──────────────────────────────────────────────────────

schedule() {
    local hhmm="$1" cmd="$2"
    echo "$cmd" | at "$hhmm" "$TOMORROW" 2>&1 | grep -v "^warning:" || true
}

schedule "$H_ENTRADA" "$ACCION ENTRADA 0"

if [ "$T_DOW" -le 4 ]; then
    schedule "$H_PAUSA_INI" "$ACCION INICIO_PAUSA $ACUM_PAUSA"
    schedule "$H_PAUSA_FIN" "$ACCION FIN_PAUSA $ACUM_PAUSA"
fi

schedule "$H_SALIDA" "$ACCION SALIDA $TOTAL_MIN"

log "Jobs at programados para $TOMORROW: OK"
log "----------------------------------------"
