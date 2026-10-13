# Descargar una APK de prueba desde GitHub

La APK de demostración **ya está compilada y publicada**: [descargar Trabajo-YA-0.3.0-demo.apk](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.3.0-demo/Trabajo-YA-0.3.0-demo.apk). Pesa 51.826.293 bytes (aproximadamente 52 MB). La [versión publicada](https://github.com/ramalhectornano-sys/miapp/releases/tag/trabajo-ya-v0.3.0-demo) incluye los comprobantes de firma, paquete y checksum.

El [workflow de Android](../.github/workflows/android-apk.yml) prepara **Trabajo-YA-0.3.0-demo.apk**, una aplicación instalable y autónoma para Android. No requiere cuenta de Expo/EAS, Expo Go ni una computadora encendida con Metro. GitHub compila el proyecto en sus servidores. Detecta el proyecto en `trabajo-ya/mobile` dentro del repositorio de descargas o en `mobile` si se usa un repositorio independiente; el workflow siempre va en `.github/workflows/android-apk.yml` en la raíz del repositorio GitHub.

La APK conserva el nombre **Trabajo YA**, el logo de la app y el paquete `com.trabajoya.autoempleoia`. Permite recorrer Asistente IA, Mis postulaciones, Búsquedas automáticas y Mi perfil, con temas claro, oscuro y del sistema. Los perfiles, conversaciones, vacantes y postulaciones de ejemplo se identifican como demostración; los cambios locales de la demo no se guardan en un servidor.

**Esta APK es una demostración:** no conecta un modelo de IA real, no autentica cuentas reales, no ejecuta búsquedas en el servidor y no envía correos. La app y su workflow no reciben claves de Groq, tokens de Gmail ni credenciales privadas de Supabase. No cargues esas claves en variables `EXPO_PUBLIC_*`.

## Instalar la APK disponible desde el celular

1. Tocá el [enlace directo de la APK](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.3.0-demo/Trabajo-YA-0.3.0-demo.apk) y esperá la descarga.
2. Abrí `Trabajo-YA-0.3.0-demo.apk` desde Descargas o Archivos. Si Android solicita permiso para instalar desde el navegador o Archivos, habilitalo para esa aplicación y completá la instalación.
3. Abrí **Trabajo YA**. Es una demo autónoma: no requiere Expo Go ni mantener una computadora encendida.

No se ejecutó todavía la aplicación en un dispositivo físico o emulador; la compilación y las verificaciones de firma y paquete fueron exitosas en [GitHub Actions](https://github.com/ramalhectornano-sys/miapp/actions/runs/38427300341).

## Compilar una nueva APK desde el celular

1. Ingresá a GitHub con tu cuenta y abrí el repositorio que contiene este proyecto. La cuenta puede ser gratuita; la disponibilidad de Actions depende de las cuotas y políticas del repositorio.
2. El primer `push` a la rama **trabajo-ya-apk** inicia la compilación. Abrí **Actions → APK de prueba de Trabajo YA** y seleccioná esa ejecución. Mientras se compila, el estado no implica que exista una APK terminada.
3. Si el workflow ya está disponible en la rama predeterminada, también podés usar **Run workflow** y elegir la rama que querés compilar. Si GitHub pide habilitar Actions para un repositorio recién creado o copiado, habilitalo desde esa pestaña.
4. Esperá a que la ejecución termine en verde. Si falla, la etapa en rojo muestra el error y no hay una APK verificada para esa ejecución.
5. Abrí **Releases → Trabajo YA 0.3.0 — APK de demostración** y descargá `Trabajo-YA-0.3.0-demo.apk` desde **Assets**. La versión 0.3.0 ya está publicada; una compilación posterior necesita una nueva versión/tag para no reemplazar sus archivos.
6. Como alternativa, en la ejecución de Actions entrá en **Artifacts** y tocá **Trabajo-YA-0.3.0-demo**. GitHub requiere iniciar sesión para descargar el artefacto. Si la sección no aparece en la vista móvil, activá **Sitio de escritorio**. Extraé el ZIP desde Archivos: adentro están la APK, su checksum SHA-256, las huellas públicas del certificado, la información del paquete y el commit compilado.
7. Tocá el archivo `.apk`. Android puede solicitar permiso para instalar aplicaciones desde tu navegador o aplicación Archivos. Permitilo para esa aplicación y completá la instalación. No requiere contraseña de Expo ni acceso a Google Cloud.

Los artefactos de este workflow se conservan durante **30 días**. La prerelease se conserva hasta que alguien la elimine. El workflow usa el token automático de GitHub con permiso `contents: write` para publicar la APK verificada en **Releases**; no exige configurar un token privado ni otras credenciales. No publica en Google Play ni cambia la rama principal. Si ya existe el tag `trabajo-ya-v0.3.0-demo`, falla explícitamente en la publicación para conservar los archivos anteriores. El artefacto de la nueva compilación queda disponible si la etapa de compilación y verificación terminó; para publicar otra versión hay que cambiar la versión de la app y el tag, o gestionar expresamente la versión anterior.

## Cómo se construye

El runner usa Ubuntu, Node.js 22, Java 17 y Android SDK 36. Instala las dependencias de `mobile`, verifica TypeScript y las pruebas, ejecuta `npx expo prebuild --platform android --no-install` y luego `:app:assembleRelease` con Gradle. Gradle incorpora el JavaScript y los recursos dentro de la APK; no hace falta un servidor de desarrollo para abrirla. Los servicios externos se dejan vacíos y `EXPO_PUBLIC_DEMO_MODE=true` queda fijado durante la compilación. `EXPO_NO_DOTENV=1` impide incorporar valores desde archivos `.env`.

La variante nativa se llama `release`, pero **usa la firma debug de prueba que genera Expo**. Esa clave compartida de desarrollo no sirve como firma privada de publicación. El workflow verifica que exista esa configuración, ejecuta `apksigner verify` y confirma con `aapt dump badging` el nombre, paquete y versión del archivo resultante. No crea ni distribuye una clave privada de producción. Si más adelante instalás una APK del mismo paquete firmada con otro certificado, Android exigirá desinstalar esta demo antes de instalarla; se perderán sus datos locales.

La APK publicada corresponde al commit `2686a70130060c075bc7eea11122885b74ee30c7`. Su SHA-256 es `3839f47c4bba1a0cab47d4c9f112132772e9d687830be8d44a783f1d2bbbead1`.

Para una versión conectada con usuarios, IA y correo, seguí [Activar la IA real](IA_REAL.md), [Android y EAS](ANDROID_BUILD.md) y las instrucciones del servidor. Esa versión requiere servicios desplegados, configuración pública real y un certificado propio. La APK demo publicada no acredita el funcionamiento de esas integraciones.
