# APK conectada a servicios reales

**APK 0.5.1 / versionCode 10 publicada para pruebas.**
[Descargar Trabajo-YA-0.5.1-real.apk](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.5.1-real/Trabajo-YA-0.5.1-real.apk). Instalar como actualización, sin desinstalar.

Esta revisión explica el motivo junto al botón de postulación: falta de correo
de la empresa, CV, consentimiento, demostración u operación en curso. Repite el
destinatario junto a la acción y muestra los rechazos del servidor dentro del
detalle. Tras un error consulta el estado guardado sin repetir el envío. Los
errores quedan asociados a la postulación que los produjo.

El cambio es de Android: no requiere una nueva migración ni recrear Supabase,
Gmail o claves. No habilita un envío sin destinatario ni sustituye la validación
del servidor. Un correo presente no significa que esté verificado. Las fuentes
web pueden producir borradores sin correo; encontrar una oferta no acredita un
canal legítimo para enviar el CV.

La [compilación 38905283660](https://github.com/ramalhectornano-sys/miapp/actions/runs/38905283660) verificó con apksigner y aapt la firma,
nombre, paquete y versión. La app usa demo=false, paquete
**com.trabajoya.autoempleoia** y callback **autoempleoia://auth/callback**.
El comprobante de certificado coincide con 0.5.0; conserva la instalación y
los datos. Es una firma de prueba, no una publicación en Google Play.

Tamaño: **51873325 bytes**. SHA-256:

```text
12d18534a4c545c516ae247ad52ce2e9c3ef0aff2bd6cb8b83500b7dabae8ce4
```

Commit compilado: `21633d3ca10e473349b4334519bba7ab239b04d5`. Los comprobantes, certificado y checksum están
en [la versión publicada](https://github.com/ramalhectornano-sys/miapp/releases/tag/trabajo-ya-v0.5.1-real). No incluye secretos de IA,
Supabase ni Gmail. [CI 38905283984](https://github.com/ramalhectornano-sys/miapp/actions/runs/38905283984) aprobó **424 pruebas backend,
52 móviles, TypeScript, siete migraciones, pruebas SQL, 29 cloud y arranque
del contenedor**. La revisión del flujo fue por código; queda la comprobación
manual del botón en el dispositivo y no se envió correo durante estas pruebas.

El backend sigue en **0.5.3**. La [última prueba web real](PRUEBA_WEB_REAL.md)
consultó Tavily y Groq con resultado parcial: cero vacantes verificadas dentro
del radio. Esta actualización no repitió consultas de pago ni acredita una
entrega de Gmail o la automatización completa. El worker y los envíos necesitan
su configuración y una ejecución comprobada. Ver [EMPEZAR](../EMPEZAR.md),
[búsqueda general](BUSQUEDA_WEB.md), [worker](WORKER_GITHUB.md) y
[correo](ACTIVAR_CORREOS.md).

Para instalaciones que aún no actualizaron la geografía/historial, aplicar
solamente [migración 007](../supabase/migrations/202610140007_web_research_and_locations.sql)
si 001–006 están instaladas y 007 falta. No repetir el instalador inicial ni
regenerar TOKEN_ENCRYPTION_KEY. El parche del botón no necesita SQL adicional.

## Qué necesita Android

La APK recibe únicamente tres datos públicos:

| Campo | Dónde obtenerlo |
| --- | --- |
| `backend_url` | URL HTTPS de Render o Cloud Run después de desplegar el backend. Usá la URL base, sin `/health`, `/api`, parámetros ni credenciales. |
| `supabase_url` | **Project URL** del proyecto en [Supabase](https://supabase.com/dashboard). |
| `supabase_public_key` | Clave **publishable** (`sb_publishable_...`) o la clave antigua **anon** del proyecto en Supabase. |

La clave pública de Supabase forma parte de cualquier app que use Supabase; el acceso a los datos depende de la sesión del usuario y las políticas RLS. No uses `service_role`, `sb_secret_...`, la clave de Groq, el secreto OAuth ni tokens de Gmail. El preparador rechaza campos adicionales y claves privadas; sus errores no imprimen los valores recibidos.

## Preparar y compilar desde el celular

1. Terminá la instalación de Supabase con las siete migraciones y los buckets privados, habilitá el acceso por correo OTP y desplegá el backend. Configurá el proveedor de IA en el servidor. En Cloud Run o un servidor propio podés comprobarlo con `test-ai` o `python -m app.check_ai` según [IA real](IA_REAL.md). Render Free no ofrece terminal: allí la comprobación se completa mediante el chat autenticado de la app, después de compilar. No alcanza con crear una clave ni con `/health`.
2. Abrí el repositorio del proyecto en GitHub. Creá o seleccioná la rama **`trabajo-ya-real`**. Si el repositorio contiene el ZIP descomprimido, los archivos del proyecto están dentro de `trabajo-ya/`; si contiene directamente el código, están en la raíz. El workflow debe estar en **`.github/workflows/android-real.yml` en la raíz del repositorio**.
3. Abrí `mobile/services.public.json.example` (o `trabajo-ya/mobile/services.public.json.example`) y copiá su contenido. Creá junto a él un archivo llamado **`services.public.json`** mediante **Add file → Create new file**. Si estas opciones no aparecen en el navegador del celular, activá **Sitio de escritorio**.
4. Completá las tres cadenas vacías con tus valores públicos y guardá el archivo. Debe conservar esta estructura, sin agregar más campos:

   ```json
   {
     "backend_url": "",
     "supabase_url": "",
     "supabase_public_key": ""
   }
   ```

   Las cadenas vacías son un formulario, no una configuración operativa. Pegá URLs de servicios desplegados y la clave pública de tu proyecto. No sirven `localhost`, direcciones privadas, dominios de ejemplo ni URLs HTTP.

5. El guardado mediante un `push` a **`trabajo-ya-real`** inicia **Actions → APK real de Trabajo YA**. También podés elegir **Run workflow** cuando el workflow esté disponible en la rama predeterminada; seleccioná la rama con tu configuración. No requiere cuenta de Expo, EAS ni agregar secretos privados para la APK.
6. La primera etapa valida el archivo público y consulta **`<backend_url>/health`**. Requiere `status=ok`, Supabase `configured` e IA `configured_unverified`; rechaza IA `demo`. Si falla, la ejecución termina **antes de instalar dependencias y herramientas Android**. Arreglá el servicio o el archivo indicado y repetí la ejecución. Este control verifica configuración y accesibilidad, **no una respuesta real de IA ni persistencia**.
7. Esperá a que la ejecución complete la compilación, verifique la firma y publique la prerelease. Recién entonces habrá una APK nueva. Abrí **Releases** y descargá el archivo `Trabajo-YA-<versión>-real.apk`. Como alternativa, descargá el artefacto `Trabajo-YA-<versión>-real` desde esa ejecución de Actions y extraé el ZIP.
8. Abrí la APK desde Archivos y completá la instalación en Android. No requiere Expo Go ni un servidor Metro.

La versión y `versionCode` se obtienen de `mobile/app.json`; la revisión publicada es **0.5.1 / 10**. El archivo APK, nombre de artefacto y tag se generan a partir de esa versión; no hay un nombre fijo en el workflow. Una versión publicada no se reemplaza automáticamente: para una siguiente entrega hay que incrementar `version` y `android.versionCode`.

## Qué comprueba la compilación

El runner usa Node.js 22, Java 17 y Android SDK 36. Valida `app.config.js` antes de `expo prebuild`, verifica TypeScript y pruebas de la app, incorpora el JavaScript y los recursos con Gradle y valida la APK con `apksigner verify` y `aapt dump badging`. Confirma nombre **Trabajo YA**, paquete **`com.trabajoya.autoempleoia`**, versión y `versionCode`.

Publica como **prerelease** un tag `trabajo-ya-v<versión>-real` con `--target` fijado al commit compilado. Adjunta APK, checksum SHA-256, huellas públicas del certificado, información del paquete, commit y el lockfile de dependencias. El artefacto de Actions dura 30 días; la versión publicada permanece mientras no se elimine.

Esta ruta usa **firma debug de prueba generada por Expo**, igual que la ruta de pruebas anterior. Permite probar servicios reales sin una cuenta de Expo ni una clave privada para compilar. Para publicar en Google Play se requiere una firma propia y su gestión segura. Si el certificado de la nueva APK difiere del de la instalada, Android exigirá desinstalar la anterior.

## Pruebas obligatorias con una cuenta real

Antes de considerar terminada la integración, comprobá en Android:

1. Recibir un correo, abrir su enlace en el mismo celular (o ingresar el OTP si lo incluye) y volver a abrir la app conservando la sesión.
2. Guardar un perfil y una foto, cerrar la app y confirmar que ambos siguen disponibles al entrar de nuevo. Verificá también con otra sesión que los datos correspondan al usuario correcto.
3. Subir un PDF o DOCX, elegir el CV principal y comprobar que permanece seleccionado después de volver a entrar. El archivo debe quedar en almacenamiento privado.
4. Escribir una instrucción en el chat, obtener una respuesta del modelo real y confirmar que se conserva el historial. En Cloud Run se puede ejecutar además `test-ai`; en Render Free se verifica con esa llamada autenticada real. El valor `configured_unverified` de `/health` no reemplaza una respuesta del modelo.
5. Crear una búsqueda y verificar su persistencia y una ejecución del worker con una fuente real autorizada. El horario se ejecuta en el servidor.
6. Conectar Gmail, conceder explícitamente el permiso y comprobar un envío a un destinatario verificado autorizado. Solo debe figurar como enviado con confirmación del proveedor. Activar el scheduler y los envíos es una configuración separada del backend; compilar esta APK no los activa.

La APK **0.3.2** añade el regreso por enlace PKCE. Guardar Site URL y
Redirect URLs con `autoempleoia://auth/callback`, pedir un correo nuevo desde la
APK y abrirlo en ese mismo celular. La plantilla predeterminada del proyecto
Free sirve para este ingreso; el OTP numérico es opcional si el correo incluye
`{{ .Token }}`. Para personalizar el mensaje se necesita SMTP propio. El botón
Sign in del preview del Dashboard no es un enlace real. Ver la
[configuración y diagnóstico completos](AUTH_SETUP.md).

Antes de dar por verificado el acceso, probar una apertura con la app cerrada,
otra con la app abierta y un enlace vencido o reutilizado. Confirmar persistencia
de la sesión y comprobar chat/perfil/foto/CV con esa cuenta. Estas pruebas desde
el teléfono todavía no se ejecutaron. Las búsquedas y los correos automáticos
continúan pendientes de integración y programación.

## Compilación propia con las mismas variables públicas

Desde la raíz del proyecto, cuando el archivo JSON esté completo:

```bash
python3 scripts/prepare_android_real.py --mobile-dir mobile --check-health --env-file mobile/.env.local
```

Ese comando escribe únicamente variables públicas y fija el modo real. Para GitHub Actions se usa `--github-env "$GITHUB_ENV"` en lugar de `--env-file`. Las variables privadas permanecen exclusivamente en el servidor y nunca deben cargarse como `EXPO_PUBLIC_*`. Para los pasos de compilación local y EAS, consultá [Android](ANDROID_BUILD.md).
