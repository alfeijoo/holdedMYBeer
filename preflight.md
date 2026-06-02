# Preflight — Requisitos del móvil

Todo lo que hay que configurar en el dispositivo Android antes de instalar holdedMYBeer.

---

## 1. Termux

Instalar desde **F-Droid** (no desde Play Store — la versión de Play Store está desactualizada y sin actualizaciones de paquetes).

- [https://f-droid.org/packages/com.termux/](https://f-droid.org/packages/com.termux/)

```bash
# Actualizar paquetes base
pkg update && pkg upgrade

# Instalar dependencias
pkg install openssh android-tools gawk at
```

> `android-tools` incluye el binario `adb` dentro de Termux.
> `gawk` es necesario para el parseo de XML del dump de UI.
> `at` es necesario para programar los jobs de fichaje.

---

## 2. Termux:Boot

Permite que Termux se lance automáticamente en el arranque del dispositivo (para que crond y atd estén siempre activos).

Instalar desde **F-Droid**:
- [https://f-droid.org/packages/com.termux.boot/](https://f-droid.org/packages/com.termux.boot/)

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

> El `@reboot` del crontab hace lo mismo como fallback, pero Termux:Boot es más fiable.

---

## 3. ADB sobre TCP (persistente)

Habilitar ADB por red en el puerto 5555 de forma permanente. Esto permite que los scripts se controlen a sí mismos vía `adb -s 127.0.0.1:5555`.

```bash
# En Termux (requiere que ADB esté habilitado en Ajustes de desarrollador)
adb tcpip 5555

# Hacer el puerto persistente tras reinicios
adb shell setprop persist.adb.tcp.port 5555
```

Verificar que funciona:
```bash
adb connect 127.0.0.1:5555
adb -s 127.0.0.1:5555 shell echo ok
# Debe devolver: ok
```

---

## 4. Depuración USB / ADB habilitado

En **Ajustes → Acerca del teléfono**: pulsar 7 veces sobre "Número de compilación" para activar opciones de desarrollador.

En **Ajustes → Opciones de desarrollador**:
- [x] Depuración USB → activar
- [x] Depuración inalámbrica → activar (en Android 11+)

La clave ADB del dispositivo debe estar autorizada para conexiones locales:

```bash
# Copiar la clave pública generada por Termux a las claves autorizadas del sistema
# (requiere que ADB esté conectado al menos una vez por USB o red local)
adb push ~/.android/adbkey.pub /data/misc/adb/adb_keys
# O añadirla al fichero existente si ya hay claves
```

---

## 5. Sin PIN / bloqueo de pantalla

Los scripts desbloquean la pantalla con un swipe. Si hay PIN, huella o patrón, el swipe no funcionará.

**Ajustes → Seguridad → Bloqueo de pantalla → Ninguno**

> Si no quieres eliminar el bloqueo, habría que usar `adb shell input text <PIN>` hardcodeado, lo cual no es recomendable.

---

## 6. Holded instalado y con sesión activa

- App Holded instalada y con sesión iniciada.
- El usuario tiene acceso al módulo de fichaje (Time Tracking).
- La app debe poder abrirse sin login manual (sesión persistente).

Verificar que el tab "Inicio" muestra el widget de fichaje con el botón Play.

---

## 7. Termux en lista blanca de batería

Android mata procesos en segundo plano agresivamente. Termux debe estar exento.

**Ajustes → Batería → Optimización de batería → Termux → No optimizar**

En Samsung (One UI / LineageOS):
- **Ajustes → Aplicaciones → Termux → Batería → Sin restricciones**

---

## 8. Sin animaciones (opcional pero recomendado)

Las animaciones ralentizan `uiautomator` y pueden causar dumps fallidos. Los scripts las desactivan antes de cada dump y las restauran después, pero desactivarlas globalmente mejora la fiabilidad.

**Ajustes → Opciones de desarrollador**:
- Escala de animación de ventana → **Desactivadas**
- Escala de animación de transición → **Desactivadas**
- Escala de duración del animador → **Desactivadas**

---

## Verificación final

```bash
# En Termux — comprobar que todo está en marcha
pgrep -a crond   # debe mostrar el proceso
pgrep -a atd     # debe mostrar el proceso
crontab -l       # debe mostrar las entradas de maestro.sh y @reboot
adb -s 127.0.0.1:5555 shell echo ok   # debe devolver: ok

# Simulacro completo
~/fichaje/simulacro.sh 8
```

Si el simulacro completa las 4 acciones con `OK`, el sistema está listo.
