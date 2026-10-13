# Trabajo YA: Supabase y servidor gratuitos para pruebas

Esta ruta prepara inicio de sesión por código, perfil, foto, CV y chat con un
modelo real. Usá **Supabase Free** para usuarios, datos y documentos privados,
y **Render Free** para la API Python que llama a Groq. Las cuentas y los secretos
pertenecen a vos. No hay que poner una clave privada en GitHub ni en la APK.

Podés hacerlo desde el navegador del celular. Si algún menú queda oculto,
activá **Sitio de escritorio**. Creá primero Supabase; después Render.

## 1. Crear Supabase

1. Abrí [Supabase](https://supabase.com/dashboard) y registrate. Podés usar GitHub.
2. Creá una organización con plan **Free**. Tocá **New project**, elegí esa
   organización y poné `Trabajo YA` como nombre.
3. Generá una contraseña para la base de datos y guardala en tu gestor de
   contraseñas. Esta contraseña administra PostgreSQL; los usuarios de la app
   seguirán entrando por código de correo, sin contraseña.
4. Elegí una región cercana y tocá **Create new project**. Esperá que termine.
5. Antes de registrar usuarios en la app, abrí **SQL Editor → New query**.
   Copiá **todo** [supabase/install-new-project.sql](../../supabase/install-new-project.sql),
   desde el encabezado hasta `COMMIT;`, pegalo y tocá **Run** con el rol
   `postgres`. El instalador reúne las **seis migraciones** en orden, incluida
   la persistencia del CV principal.
6. Comprobá que termine sin errores. En **Table Editor** deben estar `profiles`,
   `resume_versions`, `job_searches` y `applications`. En **Storage** deben
   aparecer `resumes` y `profile-photos`, ambos **privados**.

El instalador es para una base nueva, una sola vez. No borra datos ni debe
repetirse sobre un proyecto ya instalado. Si se usaron migraciones individuales,
no ejecutes también el instalador. La guía del esquema está en
[supabase/README.md](../../supabase/README.md).

## 2. Habilitar el ingreso sin contraseña

1. En **Authentication → Sign In / Providers → Email**, habilitá el proveedor
   Email y el registro de nuevos usuarios. Mantené la confirmación de correo.
2. Si aparece **Email OTP expiration**, elegí **600 segundos** y código de
   **6 dígitos**, para coincidir con la app y las plantillas.
3. En **Authentication → Email Templates**, pegá
   [magic_link.html](../../supabase/templates/magic_link.html) en **Magic Link**
   y [confirmation.html](../../supabase/templates/confirmation.html) en
   **Confirm signup**. Ambos muestran `{{ .Token }}`, el código que el usuario
   escribe en la app.
4. En **URL Configuration → Redirect URLs**, agregá
   `autoempleoia://auth/callback`. La app conserva este identificador técnico.
5. Para tu primera prueba ingresá en la app con **el mismo correo de tu cuenta
   Supabase**, que es miembro del equipo del proyecto.

El correo incluido de Supabase sirve para probar con las direcciones de miembros
del equipo; actualmente limita el envío a **2 mensajes por hora**. Para registrar
otras personas necesitás configurar SMTP propio en Supabase. No desactives la
confirmación para evitar ese límite. Esto es independiente de Gmail para enviar
postulaciones. Ver [configuración de autenticación](../../docs/AUTH_SETUP.md) y
[restricciones oficiales de SMTP](https://supabase.com/docs/guides/auth/auth-smtp).

## 3. Encontrar los datos de Supabase

Abrí **Connect** o **Settings → API / API Keys**, según el menú del Dashboard,
y guardá estos datos:

| Dato | Dónde se configura |
| --- | --- |
| **Project URL**, `https://…supabase.co` | Render: `SUPABASE_URL`. APK: URL de Supabase. |
| **Publishable key**, `sb_publishable_…`, o antigua `anon` | Render: `SUPABASE_ANON_KEY`. APK: clave pública de Supabase. |
| **Secret key**, `sb_secret_…`, o antigua `service_role` | **Solo Render**: `SUPABASE_SERVICE_ROLE_KEY`. |

La clave secreta permite operaciones del servidor. No la pongas en una captura,
un mensaje, GitHub ni en un campo `EXPO_PUBLIC_…`. El nombre de variable
`SUPABASE_ANON_KEY` acepta también la nueva clave pública `sb_publishable_…`.

## 4. Crear el servidor Render Free

El código se toma de
[ramalhectornano-sys/miapp, rama trabajo-ya-real](https://github.com/ramalhectornano-sys/miapp/tree/trabajo-ya-real).
El archivo `render.yaml` ya está en la raíz de esa rama y contiene tu URL y
clave pública de Supabase. El camino más corto es **Blueprint**: solo tenés
que completar las dos claves privadas en Render.

1. Abrí [Render](https://dashboard.render.com/) y creá tu cuenta con GitHub.
   Usá el workspace **Hobby** para estas pruebas.
2. Tocá **New → Blueprint**. Conectá GitHub si Render lo pide y elegí
   **ramalhectornano-sys/miapp → Connect**. Si el repositorio no aparece,
   autorizá el acceso de Render a `miapp` desde la conexión de GitHub.
3. Poné `Trabajo YA` como nombre del Blueprint, elegí la rama
   **trabajo-ya-real** y dejá **Blueprint Path: `render.yaml`**.
4. Render te pedirá únicamente estos valores. Pegalos **solo en su panel**:

| Campo de Render | Qué pegar |
| --- | --- |
| `SUPABASE_SERVICE_ROLE_KEY` | Tu clave **Secret key** (`sb_secret_…`) o antigua `service_role`, desde Supabase → Settings → API Keys. |
| `AI_API_KEY` | Tu clave de Groq, desde [API Keys](https://console.groq.com/keys). Usá una nueva si compartiste la anterior. |

5. Revisá que el resumen muestre **un Web Service `trabajo-ya-api` con plan
   Free**. No agrega una base de datos de Render ni un worker. Tocá
   **Deploy Blueprint**. Si el panel ofrece otro plan o pide un pago, no
   aceptes un cambio de plan para seguir esta ruta gratuita; usá la alternativa
   Web Service de abajo y elegí Free.
6. Esperá el estado **Live** del servicio `trabajo-ya-api`. Abrilo y copiá la
   **URL HTTPS** que Render le asignó. Esa URL es el dato que falta para
   conectar la APK con tu servidor. No compartas las dos claves privadas.

No necesitás credenciales de Google OAuth para probar perfil y chat. El
Blueprint ya configura Groq, el puerto, `/health` y los envíos desactivados.
El plan **Hobby** del workspace y el plan **Free** del servicio son ajustes
distintos: revisá ambos. El soporte de `plan: free` está documentado en la
[referencia oficial de Blueprint](https://render.com/docs/blueprint-spec), y
el flujo aparece en la [guía oficial de creación](https://render.com/docs/infrastructure-as-code).

Si Render muestra un error al leer el Blueprint, revisá primero la rama y la
ruta `render.yaml`. Si pide verificar la cuenta, completá la verificación que
muestre el proveedor; no podemos confirmar de antemano las verificaciones de
cada cuenta. No crees un segundo servicio si el primero ya se desplegó.

### Alternativa: formulario Web Service

Usá esta alternativa si no podés crear el Blueprint; permite seleccionar Free
manualmente. No uses ambas rutas para crear dos servicios.

1. En Render tocá **New → Web Service** y conectá `miapp`. Si usás otra cuenta,
   podés usar la URL del repositorio público.
2. Configurá:

| Campo | Valor |
| --- | --- |
| Name | `trabajo-ya-api`, o un nombre disponible |
| Branch | `trabajo-ya-real` |
| Root Directory | `trabajo-ya/backend` |
| Language / Runtime | **Docker** |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context Directory | `.` |
| Instance Type | **Free** |
| Health Check Path | `/health` |
| Auto-Deploy | **Off**, para actualizar cuando decidas |

3. En **Advanced → Docker Command**, pegá este comando completo:

```sh
sh -c 'exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log'
```

Render asigna el puerto por la variable `PORT`. El comando respeta ese valor,
escucha en todas las interfaces y evita guardar las URL de las solicitudes en
el registro de acceso. No cambies el Dockerfile para cargar secretos.

4. En **Environment Variables**, agregá:

| Nombre | Valor |
| --- | --- |
| `SUPABASE_URL` | Tu Project URL de Supabase |
| `SUPABASE_ANON_KEY` | Tu Publishable key o `anon` |
| `SUPABASE_SERVICE_ROLE_KEY` | Tu Secret key o `service_role`, privada |
| `AI_API_KEY` | Una clave Groq vigente, privada |
| `AI_PROVIDER` | `openai_compatible` |
| `AI_BASE_URL` | `https://api.groq.com/openai/v1` |
| `AI_MODEL` | `openai/gpt-oss-20b` |
| `DEFAULT_TIMEZONE` | `America/Argentina/Buenos_Aires` |
| `CORS_ORIGINS` | `[]` |
| `AUTHORIZED_JOB_FEEDS` | `[]` |
| `MAIL_SEND_ENABLED` | `false` |

La clave de Groq se obtiene en [API Keys](https://console.groq.com/keys).
Usá una nueva si la anterior se compartió en un chat. Cargala directamente en
Render, nunca en el código ni en la app. Para esta etapa no necesitás añadir
credenciales de Google OAuth: el chat y el perfil funcionan sin vincular Gmail.

La app Android nativa no necesita CORS. El valor `[]` es correcto. Si después
publicás una versión web, agregá únicamente los orígenes HTTPS de esa web en un
array JSON; no hace falta permitir cualquier origen.

5. Revisá que **Instance Type siga siendo Free** y tocá **Create Web Service**.
   Esperá el estado **Live**. Render mostrará la URL HTTPS asignada: guardala.
   No hay una URL de servidor real hasta que ese despliegue termine.

El archivo [render.yaml](../../render.yaml) describe la configuración equivalente
del Blueprint. Si usás un fork o
una estructura distinta de carpetas, ajustá `repo`, `branch` y `rootDir` antes
de desplegar. Las rutas del Dockerfile y del contexto se resuelven desde
`rootDir`, según la [guía oficial de monorepos](https://render.com/docs/monorepo-support).

## 5. Comprobar y conectar la APK

Abrí la URL que Render mostró seguida de `/health`. El resultado debe incluir
`"status": "ok"`. El estado `configured_unverified` de la IA solo indica que
se cargó la configuración; **no demuestra que Groq respondió**.

Para preparar la APK conectada hacen falta únicamente tu **URL pública de
Render**, tu **URL de Supabase** y tu **clave pública Publishable/anon**. No hace
falta compartir la clave secreta de Supabase ni la clave Groq.

La compilación Android debe usar:

```env
EXPO_PUBLIC_DEMO_MODE=false
EXPO_PUBLIC_BACKEND_URL=https://TU-SERVICIO.onrender.com
EXPO_PUBLIC_SUPABASE_URL=https://TU-PROYECTO.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=TU-CLAVE-PUBLICA
```

Estos son ejemplos de campos, no un servidor o una cuenta ya existentes.
La APK de demostración anterior no se convierte en real al crear las cuentas;
hay que compilar o configurar la versión conectada con tus datos públicos.

En la versión conectada, probá ingresar por código, guardar el perfil, cargar
una foto y un CV, cerrar la app y volver a abrirla para comprobar persistencia.
Después enviá una instrucción al chat y comprobá que responda sin indicación
de demostración. Un error de Groq, Supabase o red debe mostrarse como error,
sin simular una respuesta ni una operación guardada.

## Límites y búsquedas automáticas

Render Free apaga la API después de **15 minutos sin tráfico** y puede tardar
alrededor de **un minuto** en despertar. Si la primera solicitud falla por
tiempo de espera, esperá el arranque y volvé a intentarlo. Tu perfil, foto y CV
se almacenan en Supabase; el disco temporal de Render no guarda esos archivos.
El plan incluye **750 horas de instancia por mes y workspace**, compartidas
entre sus servicios Free. Los límites pueden suspender servicios o builds.
Ver [limitaciones oficiales de Render Free](https://render.com/docs/free).

Supabase Free incluye **500 MB de base de datos** y **1 GB de documentos**;
puede pausar proyectos tras una semana sin actividad. Usalo para pruebas y
guardá copias de tus documentos. Ver [cuotas de Supabase](https://supabase.com/pricing).

Esta ruta **no ejecuta tareas automáticas con el celular apagado**: Render no
ofrece workers ni cron en su plan Free, y este Blueprint no los crea. Tampoco
envía correos ni busca vacantes; se mantienen deshabilitados hasta configurar
fuentes permitidas, Gmail y autorizaciones.

Para automatización desde el servidor conservamos la ruta
[Google Cloud Run + Run Jobs + Scheduler](../google-cloud/README.md), que requiere
activar facturación y controlar cuotas; no garantiza costo total cero. No
elijas un plan pago ni agregues extras asumiendo que siempre serán gratuitos.
Al agregar un medio de pago en Render pueden cobrarse excesos según sus reglas.
