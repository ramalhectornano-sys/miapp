# APK conectada a servicios reales

**APK 0.5.0 / versionCode 9 publicada para pruebas.**
[Descargar Trabajo-YA-0.5.0-real.apk](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.5.0-real/Trabajo-YA-0.5.0-real.apk).
La [compilación 38744160527](https://github.com/ramalhectornano-sys/miapp/actions/runs/38744160527)
terminó correctamente: Expo/Gradle incluyeron JavaScript y recursos; `apksigner`
y `aapt` verificaron firma, nombre, paquete y versión.

La APK usa `demo=false`, paquete **com.trabajoya.autoempleoia** y callback
**autoempleoia://auth/callback**. El comprobante de certificado coincide con la
entrega anterior: instalar **como actualización, sin desinstalar**.
Es una firma de prueba, no una publicación en Google Play.

Tamaño: **51870841 bytes**. SHA-256:

```text
f0229c1edb388b5d07f0ae09ddb63c9c16f63218ea6c705274d3e1602c422d2c
```

Commit compilado: `d008ba39b4a119c833230aaeaffb894591204810`. Los comprobantes y checksum están en
[la versión publicada](https://github.com/ramalhectornano-sys/miapp/releases/tag/trabajo-ya-v0.5.0-real).
La APK no incluye claves privadas de Tavily, Groq, Gmail ni Supabase.

Esta actualización agrega provincia, país, radio, selección de localidad,
resultados con evidencia e historial web. El código pasó **403 pruebas backend,
52 móviles, TypeScript, siete migraciones y 29 cloud** en
[CI 38744160825](https://github.com/ramalhectornano-sys/miapp/actions/runs/38744160825).
Eso no acredita búsquedas ni correos reales.

**Antes de usar las pantallas nuevas**, aplicar solo [migración 007](../supabase/migrations/202610140007_web_research_and_locations.sql)
si 001–006 ya están instaladas. En Render Environment cambiar explícitamente
`WEB_SEARCH_MAX_QUERIES=6` si seguía en 2; después desplegar la rama
`trabajo-ya-real` mediante Manual Deploy y esperar Live. `/health` debe mostrar
backend **0.5.0**. No repetir el instalador inicial, recrear Gmail ni regenerar
TOKEN_ENCRYPTION_KEY. El programador necesita su configuración separada.

La [prueba real solicitada](PRUEBA_WEB_REAL.md) fue intentada pero quedó bloqueada
por `WEB_SEARCH_API_KEY` y `AI_API_KEY` ausentes en Actions: **cero llamadas** a
Tavily y sin ofertas reales acreditadas. Las claves existentes de Render no se
comparten con GitHub. La función no se considera terminada hasta obtener esa
prueba. No se desplegó Render ni se activaron envíos desde estas herramientas.
Ver [EMPEZAR](../EMPEZAR.md), [búsqueda general](BUSQUEDA_WEB.md),
[worker](WORKER_GITHUB.md) y [correo](ACTIVAR_CORREOS.md).

Los pasos siguientes sirven para preparar otra instalación o repetir una
compilación. El servicio Supabase y el Gmail existentes se conservan.

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

La versión y `versionCode` se obtienen de `mobile/app.json`; la revisión publicada es **0.5.0 / 9**. El archivo APK, nombre de artefacto y tag se generan a partir de esa versión; no hay un nombre fijo en el workflow. Una versión publicada no se reemplaza automáticamente: para una siguiente entrega hay que incrementar `version` y `android.versionCode`.

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
