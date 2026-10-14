# APK conectada a servicios reales

La APK de demostración publicada no autentica usuarios ni guarda sus datos en un servidor. La nueva ruta de compilación usa **`EXPO_PUBLIC_DEMO_MODE=false` y `TRABAJO_YA_BUILD_MODE=real`**, requiere servicios desplegados y falla si falta la configuración. No cambia automáticamente a una demo para completar una compilación.

**Estado actual: APK real 0.4.1 publicada para pruebas.** [Descargar Trabajo-YA-0.4.1-real.apk](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.4.1-real/Trabajo-YA-0.4.1-real.apk) o abrir la [versión publicada](https://github.com/ramalhectornano-sys/miapp/releases/tag/trabajo-ya-v0.4.1-real). La [ejecución de GitHub Actions 38609341591](https://github.com/ramalhectornano-sys/miapp/actions/runs/38609341591) terminó correctamente y verificó la firma con `apksigner` y los datos del paquete con `aapt`: **Trabajo YA**, **`com.trabajoya.autoempleoia`**, versión **0.4.1**, `versionCode` **8**. La APK ocupa **51.848.277 bytes** y su SHA-256 es:

```text
21f6aca141ad7bc686d2ca1e8c69f128c7ec8949289c60a09a1bd3f3a89c5ab8
```

El backend está publicado en **https://trabajo-ya-api.onrender.com** y el proyecto Supabase ya existe. El endpoint de salud de Supabase Auth respondió HTTP 200; también se comprobó que la tabla de perfiles existe y que el acceso anónimo está protegido. La APK incorpora la configuración pública de esos servicios y el modo real. Todavía no se probó en un teléfono físico ni se confirmó el funcionamiento completo de las integraciones.

Las capturas del usuario muestran acceso a la app, CV elegido y Gmail conectado. No hay que recrear servicios, claves o conexiones que ya funcionan. Todavía falta comprobar una consulta real del buscador, la operación del programador y una entrega controlada confirmada por Gmail. La API de Render Free necesita un worker/programador separado; ni esta compilación ni el despliegue activan automáticamente los envíos. Ver [activación de correos](ACTIVAR_CORREOS.md).

La entrega 0.3.3 incorpora los cambios de persistencia del chat de la [PR2](https://github.com/ramalhectornano-sys/miapp/pull/2), integrada en `trabajo-ya-real`. Conserva paquete, esquema de autenticación y certificado de prueba. Instalá la APK como actualización sin desinstalar. Para aplicar la corrección del chat, desplegá el último commit del backend en **Render → trabajo-ya-api → Manual Deploy → Deploy latest commit** y esperá **Live**. La compilación de Android no despliega Render ni habilita Gmail o tareas automáticas.

La actualización 0.4.0 agrega Tavily, extracción de vacantes con evidencia y **Ver ofertas encontradas**. El código 0.4.1 agrega un verificador independiente de anuncios de Greenhouse con canal explícito de CV por correo, reconsulta antes de enviar y muestra qué requisito falta junto al botón de autorización. Su compilación nueva está publicada y verificada; ver [activación de correo](ACTIVAR_CORREOS.md). Seguir [BUSQUEDA_WEB](BUSQUEDA_WEB.md) para activarla en Render y [WORKER_GITHUB](WORKER_GITHUB.md) para las tareas de pruebas. País, provincia y radio en kilómetros todavía están pendientes: ver [estado geográfico](ESTADO_UBICACIONES_Y_KM.md).

Los pasos siguientes se conservan para preparar otra instalación o repetir la compilación. Para la configuración actual no hace falta volver a crear los servicios ni reemplazar los datos públicos ya cargados.

## Qué necesita Android

La APK recibe únicamente tres datos públicos:

| Campo | Dónde obtenerlo |
| --- | --- |
| `backend_url` | URL HTTPS de Render o Cloud Run después de desplegar el backend. Usá la URL base, sin `/health`, `/api`, parámetros ni credenciales. |
| `supabase_url` | **Project URL** del proyecto en [Supabase](https://supabase.com/dashboard). |
| `supabase_public_key` | Clave **publishable** (`sb_publishable_...`) o la clave antigua **anon** del proyecto en Supabase. |

La clave pública de Supabase forma parte de cualquier app que use Supabase; el acceso a los datos depende de la sesión del usuario y las políticas RLS. No uses `service_role`, `sb_secret_...`, la clave de Groq, el secreto OAuth ni tokens de Gmail. El preparador rechaza campos adicionales y claves privadas; sus errores no imprimen los valores recibidos.

## Preparar y compilar desde el celular

1. Terminá la instalación de Supabase con las seis migraciones y los buckets privados, habilitá el acceso por correo OTP y desplegá el backend. Configurá el proveedor de IA en el servidor. En Cloud Run o un servidor propio podés comprobarlo con `test-ai` o `python -m app.check_ai` según [IA real](IA_REAL.md). Render Free no ofrece terminal: allí la comprobación se completa mediante el chat autenticado de la app, después de compilar. No alcanza con crear una clave ni con `/health`.
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

La versión y `versionCode` se obtienen de `mobile/app.json`; la revisión publicada es **0.4.1 / 8**. El archivo APK, nombre de artefacto y tag se generan a partir de esa versión; no hay un nombre fijo en el workflow. Una versión publicada no se reemplaza automáticamente: para una siguiente entrega hay que incrementar `version` y `android.versionCode`.

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
