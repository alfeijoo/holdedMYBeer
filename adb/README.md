# holdedMYBeer

<p align="center">
  <img src="./images/hmb2.png" width="300"/>
</p>

Automatización del fichaje diario en la app **Holded** para Android usando Termux y ADB local. Sin root. Sin intervención manual.

> **Versión bash (legacy).** La versión activa en producción es [holdedMYBeer-TokenEdition](../holdedMYBeer-TokenEdition) (Python). Esta versión se mantiene como referencia y fallback.

## Qué hace

Cada noche a las 23:00 un cron calcula horas de entrada, pausa y salida para el día siguiente con variación aleatoria, consulta ausencias directamente en Holded y programa los taps en la app mediante `at jobs`.

### Flujo diario

| Día | Entrada | Pausa | Salida | Total |
|-----|---------|-------|--------|-------|
| Lunes-Jueves | 08:00 + random | 13:00 + random (1h fija) | variable | 8h exactas |
| Viernes | 08:00 + random | - | variable | 5h30m exactas |
| Sábado / Domingo / Ausencia | - | - | - | nada |

Todos los rangos son configurables en `horario.conf`.

## Ficheros

| Fichero | Descripción |
|---------|-------------|
| `maestro.sh` | Lanzado por cron a las 23:00. Lee ausencias de Holded vía ADB, calcula tiempos aleatorios y programa `at jobs`. |
| `accion.sh` | Ejecutado por cada `at job`. Despierta la pantalla, abre Holded y realiza el tap correspondiente. |
| `horario.conf` | Configuración de horas base y variaciones. |
| `ausencias.txt` | Festivos nacionales de fallback (los que no aparecen en Holded como aprobados). |
| `simulacro.sh` | Ejecuta el ciclo completo del día con esperas cortas para pruebas. |

## Instalación en el dispositivo

Ver `preflight.md` para requisitos previos.

```bash
DEST=/data/data/com.termux/files/home/holdedMYBeer
adb push maestro.sh    $DEST/maestro.sh
adb push accion.sh     $DEST/accion.sh
adb push horario.conf  $DEST/horario.conf
adb push ausencias.txt $DEST/ausencias.txt
adb push simulacro.sh  $DEST/simulacro.sh
adb shell "chmod +x $DEST/*.sh"
```

## Arranque automático con Termux:Boot

Instalar **Termux:Boot** desde F-Droid y abrirlo al menos una vez para activarlo.

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-services.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
sleep 10
crond
atd
adb tcpip 5555
sleep 2
adb connect 127.0.0.1:5555
EOF
chmod +x ~/.termux/boot/start-services.sh
```

## ADB local persistente

Los scripts se controlan a sí mismos vía `adb -s 127.0.0.1:5555`. Para que el puerto 5555 sobreviva reinicios:

```bash
adb tcpip 5555
adb shell setprop persist.adb.tcp.port 5555
```

Verificar:

```bash
adb connect 127.0.0.1:5555
adb -s 127.0.0.1:5555 shell echo ok
# debe devolver: ok
```

## Crontab

```bash
crontab -e
```

```
0 23 * * * /data/data/com.termux/files/home/holdedMYBeer/maestro.sh
@reboot sleep 10 && atd && adb tcpip 5555 && sleep 2 && adb connect 127.0.0.1:5555
```

## Configurar horario

```bash
vi ~/holdedMYBeer/horario.conf
```

```ini
ENTRADA_BASE="08:00"    # hora base de entrada
ENTRADA_VARIACION=16    # random +0..16 min
PAUSA_BASE="13:00"      # hora base inicio pausa (L-J)
PAUSA_VARIACION=60      # random +0..60 min
PAUSA_DURACION=60       # duracion pausa en minutos
HORAS_LJ=480            # total minutos L-J (480 = 8h)
HORAS_V=330             # total minutos viernes (330 = 5h30m)
```

## Ausencias manuales

Si hay un festivo que Holded no registra, añadirlo a `ausencias.txt`:

```
# formato: DD MMM  o  DD MMM - DD MMM (rango)
25 dic
24 jun
3 nov - 20 nov
```

La fuente primaria es siempre Holded (lee la lista de ausencias aprobadas directamente de la app).

## Probar

```bash
# Via ADB desde PC
adb shell "/data/data/com.termux/files/home/holdedMYBeer/simulacro.sh 8"

# Via SSH desde PC
ssh -p 8022 192.168.1.139 "~/holdedMYBeer/simulacro.sh 8"

# Ver log
adb shell "tail -30 /data/data/com.termux/files/home/holdedMYBeer/fichaje_simulacion.log"
```

## Cómo detecta los botones

`accion.sh` no usa coordenadas fijas. Para cada tap:

- **ENTRADA / FIN_PAUSA** (timer parado/pausado): `uiautomator dump` -> parsea XML con `gawk` -> localiza el botón por posición relativa al widget "Fichaje".
- **INICIO_PAUSA** (timer corriendo): reutiliza la posición cacheada del botón Play.
- **SALIDA** (timer corriendo): posición cacheada - offset proporcional -> Stop.
- **Fallback universal**: coordenadas base escaladas por resolución real (`wm size`).

Funciona en cualquier resolución (HD+, FHD+, WQHD+) sin tocar nada.

## Dependencias Termux

```bash
pkg install android-tools gawk at
```

## Dispositivo de referencia

Samsung Galaxy S10+ (beyond2lte) - LineageOS Android 16 - 1440x3040
