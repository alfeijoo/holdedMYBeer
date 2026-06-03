# holdedMYBeer

<p align="center">
  <img src="./images/hmb2.png" width="300"/>
</p>

Automatización del fichaje diario en **Holded** para Android usando Termux. Sin intervención manual.

> **Version activa en produccion:** Python + API REST (raiz de este repo).
> La version bash legacy (ADB + taps) esta en [`adb/`](./adb/).

## Estructura

```
holdedMYBeer/
|- maestro.py       # Planificador diario (cron 23:00)
|- accion.py        # Fichaje via REST API (ejecutado por at)
|- bot.py           # Bot Telegram - comandos manuales (cron cada minuto)
|- relogin.py       # Re-login automatico cuando caduca la sesion
|- simulacro.py     # Test completo ENTRADA->PAUSA->RESUME->SALIDA
|- horario.conf     # Horas base, variaciones, PIN, cuenta Google
|- ausencias.txt    # Festivos de fallback manual
|- telegram.conf    # Token y chat_id del bot (no en repo)
|- telegram.conf.example  # Plantilla
`- adb/             # Version legacy bash (obsoleta, referencia)
```

## Flujo diario

| Dia | Entrada | Pausa | Salida | Total |
|-----|---------|-------|--------|-------|
| Lunes-Jueves | 08:00 + random | 13:00 + random (1h fija) | variable | 8h exactas |
| Viernes | 08:00 + random | - | variable | 5h30m exactas |
| Sabado / Domingo / Ausencia | - | - | - | nada |

## Proceso de fichaje (accion.py)

Cada at job ejecuta `accion.py` con la accion correspondiente. Este es el flujo completo:

```
1. Leer token JWT de MMKV via ADB
   |- Token encontrado -> continuar
   `- Token NO encontrado -> notificar Telegram + ejecutar relogin.py
        |- relogin OK -> releer MMKV -> continuar
        `- relogin FALLO -> notificar Telegram + exit(1)

2. Comprobar expiracion del JWT
   |- Quedan > 7 dias -> continuar
   `- Quedan <= 7 dias -> abrir Holded para refrescar + releer MMKV

3. Ejecutar accion via REST API
   |- 2xx OK -> log + notificar Telegram (exito)
   |- 401 Unauthorized -> ejecutar relogin.py
   |    |- relogin OK -> reintentar accion
   |    `- relogin FALLO -> log + notificar Telegram + exit(1)
   `- Otro error -> log + notificar Telegram + exit(1)
```

### Acciones disponibles

| Accion | Que hace |
|--------|----------|
| `ENTRADA` | clock-in: inicia el timer del dia |
| `INICIO_PAUSA` | obtiene tracker activo -> pausa el timer |
| `FIN_PAUSA` | obtiene tracker activo -> reanuda el timer |
| `SALIDA` | clock-out: finaliza el timer del dia |

### Notificaciones Telegram por accion

| Evento | Mensaje |
|--------|---------|
| Entrada OK | `✅ Entrada fichada` |
| Pausa OK | `⏸ Pausa iniciada` |
| Resume OK | `▶️ De vuelta al trabajo` |
| Salida OK | `🏁 Salida fichada - total: Xh00m` |
| JWT expira pronto | `🔑 JWT expira pronto — refrescando token` |
| Token no encontrado | `🔑 Token no encontrado — ejecutando re-login` |
| Sesion caducada (401) | `🔑 Sesion caducada — ejecutando re-login` |
| relogin OK | `🔑 relogin OK — sesion renovada` |
| relogin FALLO | `❌ relogin FALLO — sesion no renovada` |
| Token no encontrado tras relogin | `❌ ERROR: Token no encontrado tras relogin — accion NO ejecutada` |
| Error API | `❌ ERROR ACCION: <codigo> - <detalle>` |

## Proceso de planificacion (maestro.py)

Ejecutado cada noche a las 23:00 por cron:

```
1. Rotar log (mantener < 500 lineas)
2. Cancelar at jobs del dia siguiente (evitar duplicados)
3. Consultar ausencias en API Holded
   |- OK -> guardar cache en ausencias_cache.json
   |- 401 -> relogin + reintentar
   `- Fallo -> leer cache -> leer ausencias.txt
4. Calcular si manana es laborable
   |- Fin de semana / ausencia -> notificar frase divertida + no programar nada
   `- Dia laborable -> calcular tiempos aleatorios + programar 4 at jobs
5. Notificar plan del dia via Telegram
   |- Jueves -> incluir proximo festivo con dias restantes
```

## Proceso de re-login (relogin.py)

Ejecutado automaticamente por `accion.py` cuando la API devuelve 401:

```
1. Despertar pantalla
2. Desbloquear con PIN (UNLOCK_PIN de horario.conf)
3. Abrir Holded via am start
4. Tap "Iniciar sesion con Google" (busqueda dinamica via uiautomator)
5. Seleccionar cuenta Google (GOOGLE_ACCOUNT de horario.conf)
6. Seleccionar empresa (HOLDED_COMPANY de horario.conf)
7. Volver a home + bloquear pantalla
8. Leer nuevo JWT de MMKV
9. Verificar que la fecha de expiracion es posterior a la anterior
```

## Token JWT

El JWT de sesion se almacena en MMKV (libreria de WeChat), fichero binario privado de la app:

```
/data/data/com.holded.app/files/mmkv/mmkv.default
```

Claves: `bg_session_token` (JWT) y `bg_session_account_id`.
Solo accesible con root via ADB. No se cachea localmente - se lee en cada ejecucion.

## API REST Holded

| Accion | Metodo | Base | Endpoint |
|--------|--------|------|----------|
| Estado timer | GET | mobile.holded.com | `/internal/team/employee/current/tracker` |
| Entrada | POST | app.holded.com | `/internal/team/employee/tracker/clock-in` |
| Salida | POST | app.holded.com | `/internal/team/employee/tracker/clock-out` |
| Pausa | POST | app.holded.com | `/internal/team/tracker/pause` |
| Resume | POST | app.holded.com | `/internal/team/tracker/resume` |
| Ausencias | GET | app.holded.com | `/internal/team/v2/timeoff-year-summary?year=YYYY` |

> `mobile.holded.com` redirige POST como GET (405). Usar `app.holded.com` para escritura.

## Bot Telegram

Permite controlar el fichaje manualmente desde Telegram.

| Comando | Accion |
|---------|--------|
| `/entrada` | Fichar entrada |
| `/pausa` | Iniciar pausa |
| `/resume` | Volver del descanso |
| `/salida` | Fichar salida |
| `/estado` | Estado actual del timer via API |
| `/log` | Ultimas jornadas del log (formato legible, agrupado por dia) |
| `/plan` | Jobs at programados para hoy |
| `/help` | Lista de comandos |

## Instalacion en el dispositivo

```bash
DEST=/data/data/com.termux/files/home/holdedMYBeer
for f in maestro.py accion.py bot.py relogin.py simulacro.py horario.conf ausencias.txt telegram.conf; do
    adb push $f /data/local/tmp/$f
    adb shell "cp /data/local/tmp/$f $DEST/$f && chown u0_a174:u0_a174 $DEST/$f && chmod 755 $DEST/$f"
done
```

## Dependencias Termux

```bash
pkg install android-tools python at
```

## Crontab

```
0 23 * * * /data/data/com.termux/files/usr/bin/python3 /data/data/com.termux/files/home/holdedMYBeer/maestro.py
* * * * * /data/data/com.termux/files/usr/bin/python3 /data/data/com.termux/files/home/holdedMYBeer/bot.py
@reboot sleep 10 && atd && adb tcpip 5555 && sleep 2 && adb connect 127.0.0.1:5555
```

## Configuracion (horario.conf)

```ini
ENTRADA_BASE="08:00"    # hora base de entrada
ENTRADA_VARIACION=16    # random +0..16 min
PAUSA_BASE="13:00"      # hora base inicio pausa (L-J)
PAUSA_VARIACION=60      # random +0..60 min
PAUSA_DURACION=60       # duracion pausa en minutos
HORAS_LJ=480            # total minutos L-J (480 = 8h)
HORAS_V=330             # total minutos viernes (330 = 5h30m)

UNLOCK_PIN=1440         # PIN de desbloqueo de pantalla
GOOGLE_ACCOUNT="Nombre Apellido (Alias)"
HOLDED_COMPANY="Empresa S.L. / Grupo"
```

## Configuracion (telegram.conf)

Copiar de `telegram.conf.example` y rellenar:

```ini
TG_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TG_CHAT_ID=123456789
BOT_NAME=MiBotFichaje
```

## Ausencias manuales

Si hay un festivo que Holded no registra, añadirlo a `ausencias.txt`:

```
# formato: DD MMM  o  DD MMM - DD MMM (rango)
25 dic
24 jun
3 nov - 20 nov
```

La fuente primaria es siempre la API de Holded. `ausencias.txt` es fallback de ultimo recurso.

## Probar

```bash
# Simulacro completo (8s entre acciones)
adb shell "python3 ~/holdedMYBeer/simulacro.py 8"

# Ver log via Telegram
# Enviar /log a SrRodaBot

# Ver log directo
adb shell "tail -30 /data/data/com.termux/files/home/holdedMYBeer/holdmybeer.log"
```

> La SALIDA devolvera errorCode:4 en simulacros cortos - es la validacion de duracion minima de Holded, no un bug.

## Dispositivo de referencia

Samsung Galaxy S10+ (beyond2lte) - LineageOS Android 16 - 1440x3040
