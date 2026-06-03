# Preflight - Requisitos del movil

Todo lo que hay que configurar en el dispositivo Android antes de instalar holdedMYBeer.

---

## 1. Termux

Instalar desde **F-Droid** (no desde Play Store, la version de Play Store esta desactualizada y no recibe actualizaciones de paquetes).

- https://f-droid.org/packages/com.termux/

```bash
# Actualizar paquetes base
pkg update && pkg upgrade

# Instalar dependencias
pkg install openssh android-tools gawk at
```

`android-tools` incluye el binario `adb` dentro de Termux.
`gawk` es necesario para el parseo de XML del dump de UI.
`at` es necesario para programar los jobs de fichaje.

---

## 2. Termux:Boot

Permite que Termux se lance automaticamente en el arranque del dispositivo para que crond y atd esten siempre activos.

Instalar desde **F-Droid**:
- https://f-droid.org/packages/com.termux.boot/

Abrir la app al menos una vez para activarla. Luego crear el script de arranque:

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-services.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Arranca crond, atd y conecta ADB al iniciar el dispositivo
sleep 10
crond
atd
adb tcpip 5555
sleep 2
adb connect 127.0.0.1:5555
EOF
chmod +x ~/.termux/boot/start-services.sh
```

El `@reboot` del crontab hace lo mismo como fallback, pero Termux:Boot es mas fiable.

---

## 3. ADB sobre TCP (persistente)

Habilitar ADB por red en el puerto 5555 de forma permanente. Los scripts se controlan a si mismos via `adb -s 127.0.0.1:5555`.

```bash
# En Termux (requiere ADB habilitado en Opciones de desarrollador)
adb tcpip 5555

# Hacer el puerto persistente tras reinicios
adb shell setprop persist.adb.tcp.port 5555
```

Verificar que funciona:
```bash
adb connect 127.0.0.1:5555
adb -s 127.0.0.1:5555 shell echo ok
# debe devolver: ok
```

---

## 4. Depuracion USB / ADB habilitado

En **Ajustes > Acerca del telefono**: pulsar 7 veces sobre "Numero de compilacion" para activar opciones de desarrollador.

En **Ajustes > Opciones de desarrollador**:
- Depuracion USB: activar
- Depuracion inalambrica: activar (Android 11+)

La clave ADB del dispositivo tiene que estar autorizada para conexiones locales:

```bash
# Copiar la clave publica de Termux a las claves autorizadas del sistema
adb push ~/.android/adbkey.pub /data/misc/adb/adb_keys
```

---

## 5. Sin PIN / bloqueo de pantalla

Los scripts desbloquean la pantalla con un swipe. Con PIN, huella o patron el swipe no funcionara.

**Ajustes > Seguridad > Bloqueo de pantalla > Ninguno**

---

## 6. Holded instalado y con sesion activa

- App Holded instalada y con sesion iniciada.
- El usuario tiene acceso al modulo de fichaje (Time Tracking).
- La app se abre sin pedir login (sesion persistente).

Verificar que el tab "Inicio" muestra el widget de fichaje con el boton Play.

---

## 7. Termux en lista blanca de bateria

Android mata procesos en segundo plano. Termux tiene que estar exento.

**Ajustes > Bateria > Optimizacion de bateria > Termux > No optimizar**

En Samsung (One UI / LineageOS):
**Ajustes > Aplicaciones > Termux > Bateria > Sin restricciones**

---

## 8. Sin animaciones (recomendado)

Las animaciones ralentizan `uiautomator`. Los scripts las desactivan antes de cada dump y las restauran despues, pero desactivarlas globalmente mejora la fiabilidad.

**Ajustes > Opciones de desarrollador**:
- Escala de animacion de ventana: desactivada
- Escala de animacion de transicion: desactivada
- Escala de duracion del animador: desactivada

---

## Verificacion final

```bash
# En Termux
pgrep -a crond   # debe mostrar el proceso
pgrep -a atd     # debe mostrar el proceso
crontab -l       # debe mostrar las entradas de maestro.sh y @reboot
adb -s 127.0.0.1:5555 shell echo ok   # debe devolver: ok

# Simulacro completo
~/fichaje/simulacro.sh 8
```

Si el simulacro completa las 4 acciones con OK, el sistema esta listo.
