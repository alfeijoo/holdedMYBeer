# holdedMYBeer

<p align="center">
  <img src="./images/hmb2.png" width="300"/>
</p>

Automatización del fichaje diario en la app **Holded** para Android usando Termux y ADB local. Sin root. Sin intervención manual.

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
| `horario.conf` | Configuración de horas base y variaciones. Editar aquí para cambiar el horario. |
| `ausencias.txt` | Festivos nacionales de fallback (los que no aparecen en Holded como aprobados). |
| `simulacro.sh` | Ejecuta el ciclo completo del día con esperas cortas para pruebas. |

## Instalación

Ver `preflight.md` para requisitos previos del dispositivo.

```bash
# Copiar ficheros al móvil (desde PC con ADB)
DEST=/data/data/com.termux/files/home/fichaje
adb push maestro.sh    $DEST/maestro.sh
adb push accion.sh     $DEST/accion.sh
adb push horario.conf  $DEST/horario.conf
adb push ausencias.txt $DEST/ausencias.txt
adb push simulacro.sh  $DEST/simulacro.sh

# Permisos
adb shell "chmod +x $DEST/maestro.sh $DEST/accion.sh $DEST/simulacro.sh"
```

## Arranque automático con Termux:Boot

Para que crond y atd arranquen solos al encender el dispositivo, instalar **Termux:Boot** desde F-Droid y crear el script de arranque:

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

Abrir Termux:Boot al menos una vez para activarlo.

## ADB local persistente

Los scripts se controlan a sí mismos vía `adb -s 127.0.0.1:5555`. Para que el puerto 5555 sobreviva reinicios:

```bash
# En Termux
adb tcpip 5555
adb shell setprop persist.adb.tcp.port 5555
```

Verificar que funciona:

```bash
adb connect 127.0.0.1:5555
adb -s 127.0.0.1:5555 shell echo ok
# debe devolver: ok
```

Añadir también al crontab para que reconecte tras cualquier reinicio:

```bash
crontab -e
```

```
0 23 * * * /data/data/com.termux/files/home/fichaje/maestro.sh
@reboot sleep 10 && atd && adb tcpip 5555 && sleep 2 && adb connect 127.0.0.1:5555
```

## Configurar horario

```bash
vi ~/fichaje/horario.conf
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

## Probar sin esperar al cron

```bash
# Simulacro completo con 8s entre acciones
adb shell "/data/data/com.termux/files/home/fichaje/simulacro.sh 8"

# Ver log
adb shell "tail -30 /data/data/com.termux/files/home/fichaje/fichaje_simulacion.log"
```

## Cómo detecta los botones

`accion.sh` no usa coordenadas fijas. Para cada tap:

- **ENTRADA / FIN_PAUSA** (timer parado/pausado): `uiautomator dump` -> parsea el XML -> localiza el botón por posición relativa al widget "Fichaje".
- **INICIO_PAUSA** (timer corriendo): reutiliza la posición cacheada del botón Play.
- **SALIDA** (timer corriendo): posición cacheada - offset proporcional -> Stop.
- **Fallback universal**: coordenadas base escaladas por resolución real (`wm size`).

Funciona en cualquier resolución (HD+, FHD+, WQHD+) sin tocar nada.

## Dispositivo de referencia

Samsung Galaxy S10+ (beyond2lte) - LineageOS Android 16 - Holded 1440x3040
