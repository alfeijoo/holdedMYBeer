#!/data/data/com.termux/files/usr/bin/bash
# Simulacro completo del día: ENTRADA → INICIO_PAUSA → FIN_PAUSA → SALIDA
# Usa valores realistas de acumulado pero esperas cortas entre acciones.
export PATH=/data/data/com.termux/files/usr/bin:$PATH
HOME=/data/data/com.termux/files/home
export ADB_VENDOR_KEYS=$HOME/.android/adbkey

ACCION="$HOME/fichaje/accion.sh"
LOG="$HOME/fichaje/fichaje_simulacion.log"
ESPERA="${1:-8}"   # segundos entre acciones (default 8)

# Valores de acumulado representativos de un L-J normal
ACUM_PAUSA=182     # 3h02m trabajados antes de pausar (aleatorio realista)
TOTAL=480          # 8h exactas al final

echo "============================================"
echo "SIMULACRO - $(date '+%A %d %b %Y %H:%M:%S')"
echo "Espera entre acciones: ${ESPERA}s"
echo "Acumulado en pausa: ${ACUM_PAUSA}min | Total: ${TOTAL}min"
echo "============================================"
echo ""

run_accion() {
    local nombre="$1" accion="$2" acum="$3"
    echo "── [$nombre] $(date +%H:%M:%S) ──────────────────"
    "$ACCION" "$accion" "$acum"
    local rc=$?
    if [ $rc -eq 0 ]; then
        echo "   OK"
    else
        echo "   ERROR (exit $rc)"
    fi
    echo ""
}

run_accion "1/4 ENTRADA"      ENTRADA      0
echo "Esperando ${ESPERA}s antes de pausa..."
sleep "$ESPERA"

run_accion "2/4 INICIO_PAUSA" INICIO_PAUSA $ACUM_PAUSA
echo "Esperando ${ESPERA}s antes de reanudar..."
sleep "$ESPERA"

run_accion "3/4 FIN_PAUSA"    FIN_PAUSA    $ACUM_PAUSA
echo "Esperando ${ESPERA}s antes de salida..."
sleep "$ESPERA"

run_accion "4/4 SALIDA"       SALIDA       $TOTAL

echo "============================================"
echo "SIMULACRO COMPLETADO - $(date +%H:%M:%S)"
echo ""
echo "Últimas líneas del log:"
tail -20 "$LOG"
echo "============================================"
