#!/data/data/com.termux/files/usr/bin/bash
# Llamado por at scheduler. Args: ACTION ACUM_MIN
export PATH=/data/data/com.termux/files/usr/bin:$PATH
export ADB_VENDOR_KEYS=$HOME/.android/adbkey

LOG="$HOME/fichaje/fichaje_simulacion.log"
BTN_CACHE="$HOME/fichaje/btn_coords.txt"
ACTION="$1"
ACUM_MIN="${2:-0}"

# Fecha en formato humano
DIA_NUM=$(date +%u)
case "$DIA_NUM" in
    1) DIA="Lunes" ;;     2) DIA="Martes" ;;  3) DIA="Miercoles" ;;
    4) DIA="Jueves" ;;    5) DIA="Viernes" ;; 6) DIA="Sabado" ;;
    7) DIA="Domingo" ;;
esac
MES_NUM=$(date +%m)
case "$MES_NUM" in
    01) MES="ene" ;; 02) MES="feb" ;; 03) MES="mar" ;; 04) MES="abr" ;;
    05) MES="may" ;; 06) MES="jun" ;; 07) MES="jul" ;; 08) MES="ago" ;;
    09) MES="sep" ;; 10) MES="oct" ;; 11) MES="nov" ;; 12) MES="dic" ;;
esac
FECHA="$DIA $(date +%-d) $MES $(date +%Y)"
HORA=$(date +%H:%M)
ACUM_STR=$(printf "%dh%02dm" $((ACUM_MIN/60)) $((ACUM_MIN%60)))

log() { echo "[$FECHA] [$HORA] $*" >> "$LOG"; }
err() { echo "[$FECHA] [$HORA] [ERROR] $*" >> "$LOG"; }

# ── ADB ──────────────────────────────────────────────────────────────────
adb_ok() { adb -s 127.0.0.1:5555 shell echo ok 2>/dev/null | grep -q ok; }

if ! adb_ok; then adb connect 127.0.0.1:5555 2>/dev/null; sleep 2; fi
if ! adb_ok; then adb tcpip 5555 2>/dev/null; sleep 3; adb connect 127.0.0.1:5555 2>/dev/null; sleep 2; fi
if ! adb_ok; then err "ADB no disponible. Accion $ACTION NO ejecutada."; exit 1; fi

ADB="adb -s 127.0.0.1:5555 shell"

# ── Resolución y helpers de tap escalado ─────────────────────────────────
# Coordenadas base calibradas para 1440x3040. Se escalan a la resolución real.
SCREEN_SIZE=$($ADB wm size 2>/dev/null | grep -o '[0-9]*x[0-9]*' | tail -1)
SW=$(echo "$SCREEN_SIZE" | cut -dx -f1)
SH=$(echo "$SCREEN_SIZE" | cut -dx -f2)
: "${SW:=1440}"
: "${SH:=3040}"

tap() {
    # Uso: tap BASE_X BASE_Y
    local x=$(( $1 * SW / 1440 ))
    local y=$(( $2 * SH / 3040 ))
    $ADB input tap "$x" "$y"
}

swipe_b() {
    # Uso: swipe_b BASE_X1 BASE_Y1 BASE_X2 BASE_Y2 DURACION_MS
    local x1=$(( $1 * SW / 1440 )) y1=$(( $2 * SH / 3040 ))
    local x2=$(( $3 * SW / 1440 )) y2=$(( $4 * SH / 3040 ))
    $ADB input swipe "$x1" "$y1" "$x2" "$y2" "$5"
}

# ── Detección dinámica del botón Play/Pause/Resume ────────────────────────
# Solo funciona cuando el timer está PARADO o PAUSADO (UI idle).
# Busca el nodo "Fichaje..." para anclar la zona del widget, luego encuentra
# el elemento clickable más a la derecha en esa franja vertical.
find_fichaje_play() {
    local TMP_XML="/data/local/tmp/holded_btn.xml"
    $ADB uiautomator dump --compressed "$TMP_XML" >/dev/null 2>&1 || return 1
    $ADB cat "$TMP_XML" 2>/dev/null | gawk '
BEGIN { RS="<node "; ymid=-1; max_cx=-1 }
NR > 1 {
    node = $0
    if (match(node, /text="Fichaje[^"]*"/) && ymid < 0) {
        if (match(node, /bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/, b))
            ymid = (b[2]+0 + b[4]+0) / 2
    }
    if (node ~ /clickable="true"/) {
        if (match(node, /bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/, b))
            candidates[n++] = b[1] "," b[2] "," b[3] "," b[4]
    }
}
END {
    if (ymid < 0) exit 1
    for (i = 0; i < n; i++) {
        split(candidates[i], b, ",")
        bx1=b[1]+0; bx2=b[3]+0; cy=(b[2]+0+b[4]+0)/2
        cx=(bx1+bx2)/2
        dy=cy-ymid; if (dy<0) dy=-dy
        if (dy<200 && bx1>900 && cx>max_cx) { max_cx=cx; best_x=int(cx); best_y=int(cy) }
    }
    if (max_cx < 0) exit 1
    print best_x, best_y
}
' 2>/dev/null
}

# ── Despertar pantalla ────────────────────────────────────────────────────
$ADB input keyevent 224 2>/dev/null
sleep 1
swipe_b 720 1800 720 900 300   # swipe desbloquear
sleep 1

# ── Abrir Holded y asegurar tab Inicio ───────────────────────────────────
LAUNCH=$($ADB am start -n com.holded.app/com.holded.MainActivity 2>&1)
if echo "$LAUNCH" | grep -qi "error\|exception"; then
    err "No se pudo abrir Holded: $LAUNCH"; exit 1
fi
sleep 3

tap 240 2762   # tab Inicio
sleep 2

# ── Ejecutar acción ───────────────────────────────────────────────────────
$ADB screencap -p "/data/local/tmp/fichaje_before_${ACTION}.png" 2>/dev/null

case "$ACTION" in
    ENTRADA)
        # Timer parado: detección dinámica disponible
        PLAY_XY=$(find_fichaje_play)
        if [ -n "$PLAY_XY" ]; then
            px=$(echo "$PLAY_XY" | cut -d' ' -f1)
            py=$(echo "$PLAY_XY" | cut -d' ' -f2)
            $ADB input tap "$px" "$py"
            echo "$px $py" > "$BTN_CACHE"
            log "[ENTRADA] Play detectado dinámicamente: ($px,$py)"
        else
            tap 1246 566
            log "[ENTRADA] Play por coordenadas escaladas (${SW}x${SH})"
        fi
        sleep 2
        ;;
    INICIO_PAUSA)
        # Timer corriendo: uiautomator falla. Pause = misma posición que Play cacheado.
        if [ -f "$BTN_CACHE" ]; then
            coords=$(cat "$BTN_CACHE")
            $ADB input tap $coords
            log "[INICIO_PAUSA] Pause por caché: ($coords)"
        else
            tap 1254 548
            log "[INICIO_PAUSA] Pause por coordenadas escaladas (${SW}x${SH})"
        fi
        sleep 2
        ;;
    FIN_PAUSA)
        # Timer pausado: detección dinámica disponible
        PLAY_XY=$(find_fichaje_play)
        if [ -n "$PLAY_XY" ]; then
            px=$(echo "$PLAY_XY" | cut -d' ' -f1)
            py=$(echo "$PLAY_XY" | cut -d' ' -f2)
            $ADB input tap "$px" "$py"
            echo "$px $py" > "$BTN_CACHE"
            log "[FIN_PAUSA] Resume detectado dinámicamente: ($px,$py)"
        else
            tap 1254 548
            log "[FIN_PAUSA] Resume por coordenadas escaladas (${SW}x${SH})"
        fi
        sleep 2
        ;;
    SALIDA)
        # Timer corriendo: Stop está a la izquierda de Play/Pause.
        # Se calcula como Play_X - 176px (calibrado en 1440px) escalado a resolución real.
        if [ -f "$BTN_CACHE" ]; then
            play_x=$(cut -d' ' -f1 < "$BTN_CACHE")
            play_y=$(cut -d' ' -f2 < "$BTN_CACHE")
            stop_offset=$(( 176 * SW / 1440 ))
            stop_x=$(( play_x - stop_offset ))
            $ADB input tap "$stop_x" "$play_y"
            log "[SALIDA] Stop por caché+offset: ($stop_x,$play_y)"
        else
            tap 1070 548
            log "[SALIDA] Stop por coordenadas escaladas (${SW}x${SH})"
        fi
        sleep 3
        tap 719 2763   # Finalizar (diálogo centrado, siempre escalado)
        sleep 2
        ;;
    *)
        err "Accion desconocida: $ACTION"; exit 1
        ;;
esac

$ADB screencap -p "/data/local/tmp/fichaje_after_${ACTION}.png" 2>/dev/null

# ── Log ───────────────────────────────────────────────────────────────────
log "[$ACTION] Acumulado: $ACUM_STR"

if [ "$ACTION" = "SALIDA" ]; then
    log "[FIN DIA] Total trabajado: $ACUM_STR - OK"
    echo "" >> "$LOG"
fi
