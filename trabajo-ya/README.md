# Trabajo YA

El código **0.5.0 / Android 9** incorpora investigación laboral general con Tavily/Groq, geografía de Argentina, radio aéreo e historial de consultas. Las consultas investigan sitios públicos de empresas, consultoras, bolsas y publicaciones; LinkedIn y ar.computrabajo.com son fuentes adicionales, sin limitar el conjunto de sitios.

**La prueba real solicitada de chofer en Rincón de los Sauces, Neuquén, Argentina, a 100 km todavía no fue ejecutada ni aprobada.** No hay ofertas reales acreditadas ni comprobantes de Tavily para mostrar. Las claves están únicamente en Render; las pruebas del código usan proveedores simulados. Se ejecutaron **393 pruebas backend locales sin la prueba de socket del contenedor**, sin que eso demuestre actividad real de los proveedores.

La instalación conserva Supabase, CV, Gmail y el backend https://trabajo-ya-api.onrender.com. Para actualizar: aplicar solamente [migración 007](supabase/migrations/202610140007_web_research_and_locations.sql) si 001–006 ya están instaladas, cambiar **WEB_SEARCH_MAX_QUERIES=6 en Render Environment** si antes quedó en 2 y desplegar la rama **trabajo-ya-real**. Manual Deploy no cambia por sí solo las variables existentes. No repetir el instalador inicial ni recrear cuentas, documentos o claves.

El presupuesto normal es de **6 consultas Tavily basic**, máximo **12**, con hasta **24 resultados** y **6 páginas públicas** por ejecución. Las páginas restringidas o no verificables quedan pendientes. GeoRef cubre Argentina; otros países requieren proveedor adicional. La distancia es aérea entre centroides, no por carretera ni desde la dirección exacta del empleo. Ver [búsqueda web](docs/BUSQUEDA_WEB.md) y [alcance geográfico](docs/ESTADO_UBICACIONES_Y_KM.md).

Para la prueba real, guardar **WEB_SEARCH_API_KEY** y **AI_API_KEY** en [miapp → Settings → Secrets and variables → Actions](https://github.com/ramalhectornano-sys/miapp/settings/secrets/actions), nunca en código ni chat. Ejecutar [Prueba REAL de búsqueda web — Tavily y Groq](https://github.com/ramalhectornano-sys/miapp/actions/workflows/trabajo-ya-web-real-test.yml) y descargar su informe. Sin esos secretos, el test falla explícitamente con cero llamadas. Ver [comprobantes y pasos desde el celular](docs/PRUEBA_WEB_REAL.md).

La publicación y compilación de la APK nueva deben comprobarse en [APK conectada](docs/APK_REAL.md); el código preparado no acredita por sí solo un nuevo binario. La APK anterior 0.4.1 no contiene las pantallas geográficas de 0.5.0. El callback Android conserva **autoempleoia://auth/callback** y el paquete **com.trabajoya.autoempleoia**.

Guardar un horario no activa tareas. Render Free puede dormir y no incluye el worker continuo. El [worker GitHub Actions](docs/WORKER_GITHUB.md) está preparado, apagado por defecto y requiere secretos propios; intenta ejecutar cada 15 minutos con demoras posibles. [Cloud Run Jobs/Scheduler](deploy/google-cloud/README.md) y [servidor propio](deploy/README.md) son alternativas con posibles costos. Hay que comprobar una ejecución real antes de afirmar que las búsquedas periódicas operan.

La búsqueda general no verifica destinatarios. Correo automático exige fuente verificadora, Gmail, CV, consentimiento vigente y servicio habilitado. Se conservan 10 intentos totales por usuario/día y 72 horas entre recordatorios. **MAIL_SEND_ENABLED permanece false hasta una prueba controlada.** Ninguna postulación aparece enviada sin recibo del proveedor; tampoco se ha acreditado una entrega real del usuario. Ver [activar correos](docs/ACTIVAR_CORREOS.md).

La aplicación usa Expo/React Native/TypeScript, FastAPI y Supabase con documentos privados y RLS. Sus cuatro pestañas son Asistente IA, Mis postulaciones, Búsquedas automáticas y Mi perfil, con tema claro, oscuro o del dispositivo. La propuesta del chat debe confirmarse; no demuestra una ejecución ni concede permisos de correo.

Para actualizar desde el celular, seguir [EMPEZAR](EMPEZAR.md). La [APK 0.3.0](docs/APK_GITHUB.md) es una demostración histórica, no la aplicación conectada actual.

## Logo e icono

El logo enviado por el usuario se conserva en
`mobile/assets/brand/trabajo-ya-logo.jpg` y se muestra en la aplicación.
`trabajo-ya-icon.png` es una adaptación PNG para el icono de Android.
El nuevo icono del lanzador se incorpora al compilar una nueva versión nativa.

## Ver el diseño

[Maqueta de las cuatro pantallas](docs/images/maqueta-trabajo-ya.png) y
[vista HTML navegable](docs/preview.html). Son referencias visuales de demostración;
no son capturas de una ejecución Android.

## Estructura

```text
mobile/             Aplicación Expo SDK 54, React 19.1, React Native 0.81.5
backend/            API FastAPI, worker, adaptadores IA/CV/fuentes/correo, pruebas
supabase/           Migraciones, RLS, buckets privados, RPC atómicas y pruebas SQL
docs/               Arquitectura, seguridad y vista HTML de referencia
deploy/             Servidor cloud: Docker Compose, Ollama, API, worker y HTTPS
scripts/            Comprobaciones y preparación de compilación Android
```

## Ejecutar Android en demostración

Requiere Node.js 20.19 o posterior; se recomienda Node 22 LTS. En un teléfono
Android instalar una versión de **Expo Go compatible con SDK 54**; si la versión
actual de la tienda usa otro SDK, obtener la correspondiente en
[expo.dev/go](https://expo.dev/go). Para emulador, instalar Android Studio y crear
un dispositivo virtual.

```bash
cd mobile
cp .env.example .env
npm install
npm run android
```

Con el teléfono en la misma red, también se puede usar `npm start` y abrir el QR
desde Expo Go. La configuración inicial `EXPO_PUBLIC_DEMO_MODE=true` permite
explorar las pantallas sin credenciales ni backend. Los cambios de `.env` requieren
reiniciar Metro; usar `npx expo start --clear` si mantiene una configuración anterior.

## Activar Supabase y el backend

Estos pasos se conservan para una instalación nueva o para desarrollo local.
No hace falta volver a crear el Supabase ni el servicio Render actuales. Antes
de usar la app, confirmar las siete migraciones, incluida 007, y conservar el acceso que ya funciona en el proyecto
existente; no repetir el instalador de proyecto nuevo sobre una base instalada.

1. Crear un proyecto Supabase propio, o instalar Supabase CLI/Docker y ejecutar
   desde la raíz `supabase start` y `supabase db reset`.
2. Para un proyecto remoto, revisar y aplicar las migraciones de
   `supabase/migrations` en orden, o vincularlo con `supabase link --project-ref
   <referencia>` y aplicar `supabase db push`. En una instalación existente,
   aplicar también las nuevas migraciones antes de actualizar API y worker;
   `supabase db push` aplica las pendientes en orden. No exponer el schema `private`
   en la API. Los permisos anteriores conservan los envíos iniciales; para habilitar
   recordatorios hay que renovar expresamente el permiso de cada búsqueda.
3. Para otra instalación, configurar el acceso siguiendo [acceso sin contraseña](docs/AUTH_SETUP.md).
   El enlace predeterminado no requiere editar plantillas. Si se elige OTP numérico con SMTP propio, las plantillas deben mostrar `{{ .Token }}`, para registro y para ingreso.
   La configuración local incluye códigos de 6 dígitos válidos durante 10 minutos;
   las opciones y plantillas del proyecto remoto se configuran en su Dashboard.
   `supabase/config.toml` conserva `autoempleoia://auth/callback` para la app.
4. Preparar FastAPI con Python 3.12 o posterior:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env
```

Completar `SUPABASE_URL`, `SUPABASE_ANON_KEY` y `SUPABASE_SERVICE_ROLE_KEY` en el
`.env` del backend. Arrancar la API y, en otra terminal, el worker con el mismo
entorno virtual y configuración:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
python -m app.worker
# Alternativa para cron: procesa un lote y termina
python -m app.worker --once
```

La API documenta sus rutas en `http://localhost:8000/docs`. Las tareas continúan
con el teléfono apagado mientras el servidor y el worker estén activos. Para
producción, ejecutar ambos como servicios supervisados y usar HTTPS.

Para las pruebas con Google Cloud, la API se despliega como servicio de Run y
el worker como Job con `--once`, lote 1 y sin reintentos del proveedor. Scheduler
consulta cada 15 minutos. La guía móvil explica sus cuotas, facturación y demoras;
el programador no depende de mantener la API activa ni de una sesión del celular.

En `mobile/.env`, configurar:

```dotenv
EXPO_PUBLIC_DEMO_MODE=false
EXPO_PUBLIC_SUPABASE_URL=https://tu-proyecto.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=tu-clave-publica
EXPO_PUBLIC_BACKEND_URL=http://10.0.2.2:8000
```

`10.0.2.2` permite al emulador Android llegar a la computadora. En un teléfono
físico usar la IP LAN de la computadora y permitir la conexión en el firewall.
Para Supabase local también sustituir `localhost` por una dirección alcanzable
desde Android. Nunca colocar `service_role`, claves de cifrado ni tokens OAuth
en variables `EXPO_PUBLIC_*`: Expo las incorpora a la aplicación.

## IA, fuentes y correo reales

La configuración de desarrollo empieza con `AI_PROVIDER=demo`: interpreta
ejemplos de forma básica y devuelve propuestas identificadas, sin afirmar
ejecuciones. La instalación Render está preparada para Groq; queda verificar
una respuesta real desde el chat autenticado de la APK conectada. Para otra
instalación con un modelo abierto local:

```bash
ollama pull qwen2.5:7b
```

Configurar `AI_PROVIDER=ollama`, `AI_BASE_URL=http://localhost:11434` y
`AI_MODEL=qwen2.5:7b`. También existe `openai_compatible` para un proveedor
configurable. Una propuesta del chat debe confirmarse; no concede permisos de envío.

`AUTHORIZED_JOB_FEEDS` admite feeds HTTPS propios o autorizados. Sin fuentes
configuradas, el sistema informa el bloqueo; no registra una búsqueda como exitosa.
La investigación general usa consultas variadas, evidencia de la publicación y verificación geográfica de Argentina. El lector público es acotado y respeta restricciones de acceso; no automatiza páginas de LinkedIn ni Computrabajo. Los proveedores que requieren interacción humana conservan la postulación pendiente para revisión.

Google OAuth/Gmail está implementado como adaptador configurable. Registrar un
cliente OAuth web, habilitar Gmail API, configurar el callback exacto y usuarios
de prueba, generar una clave Fernet y completar las variables de `backend/.env`.
Los tokens se cifran y nunca pasan por Android. `MAIL_SEND_ENABLED=false` permanece
por defecto. Activarlo solo después de una prueba controlada con cuenta y
destinatario autorizados. Una cuenta conectada y una propuesta de IA no autorizan
envíos: se requiere aprobación individual o consentimiento automático explícito,
revocable y acotado a búsqueda, CV, remitente, fuentes y vencimiento.

Para configurar **envíos todos los días**:

1. Ingresar con el código recibido por correo, completar el perfil y cargar un CV.
2. Vincular el correo en **Mi perfil**. El remitente será la cuenta autorizada por
   OAuth; no se usa una dirección compartida de Trabajo YA.
3. Crear una búsqueda con frecuencia diaria, hora y zona horaria. En
   **Búsquedas automáticas**, abrir **Autorizar envíos automáticos**, elegir CV,
   cuenta conectada, fuentes y vencimiento, y aceptar expresamente el permiso.
   Para reiterar la postulación, activar y aceptar también **Recordatorios cada
   3 días**. Vincular el correo o un permiso anterior no activa esa opción.
4. Mantener API, worker y proveedores activos. A partir de cada ejecución real,
   el servidor prepara y envía las vacantes compatibles a destinatarios verificados
   dentro del permiso. El máximo es 10 intentos por usuario y día calendario,
   sumando envíos iniciales, manuales y recordatorios de todas las búsquedas.
   Si encuentra menos vacantes aptas, envía menos; si no encuentra ninguna,
   no envía. El teléfono puede estar apagado.

La autorización dura hasta 90 días y puede revocarse. Pausar la búsqueda detiene
futuros envíos; reanudarla conserva la autorización si sigue vigente. Si vence,
se revoca o se cambia el CV, la cuenta o las fuentes autorizadas, revisar y renovar
el permiso. El día de envío usa `profiles.sending_timezone`, una zona estable de
la cuenta fijada en `America/Argentina/Buenos_Aires`; cambiar la zona de una
búsqueda no reinicia el cupo. Los límites cuentan intentos reservados, incluso
fallidos o inciertos, por lo que los correos efectivamente confirmados pueden ser menos.

En cada ejecución se priorizan las postulaciones nuevas antes de los recordatorios.
Un recordatorio exige que hayan transcurrido al menos 72 horas desde el último
envío confirmado a ese correo, incluso si aparece en otra búsqueda. La oferta debe
seguir vigente, coincidir con la búsqueda y ser recuperada de una fuente autorizada
en esa ejecución; no basta con el historial. Una postulación respondida, un permiso
vencido o revocado, una búsqueda pausada y un resultado de envío incierto impiden
su reiteración automática. En **Mis postulaciones** se pueden detener los
recordatorios a una empresa; la elección se aplica al mismo correo entre todas
las búsquedas. No deshace un envío que ya se haya reservado. Las ofertas que
requieren intervención humana quedan
pendientes de revisión. Cada recordatorio genera su propio registro y confirmación
del proveedor; el envío original se conserva. Si una integración está bloqueada,
no se inventan envíos diarios.

Consultar [backend/README.md](backend/README.md) para payloads, contratos de feeds,
OAuth y rutas de consentimiento; [supabase/CONTRACT.md](supabase/CONTRACT.md) contiene
el contrato SQL exacto. Todavía no se verificaron una inferencia real, una búsqueda
laboral ni un envío externo en la instalación actual.

## Development build y compilación Android

Expo Go sirve para la primera exploración. Para probar identidad nativa, permisos
y deep links con el identificador propio, crear un development build:

```bash
cd mobile
npx expo install expo-dev-client
npx eas-cli login
npx eas-cli build --profile development --platform android
npx expo start --dev-client
```

Instalar el APK de desarrollo generado por EAS en el dispositivo o emulador.
Alternativa local con Android SDK/JDK configurados: `npx expo run:android`. El
proyecto incluye perfiles EAS `development`, `preview` (APK de demostración),
`preview-real` (APK con servicios reales) y `production` (AAB, modo real).
Configurar las variables públicas de EAS y seguir
[ANDROID_BUILD](docs/ANDROID_BUILD.md) antes de producir cada artefacto:

```bash
npx eas-cli build --profile preview --platform android
npx eas-cli build --profile preview-real --platform android
npx eas-cli build --profile production --platform android
```

Configurar las variables públicas de producción en EAS antes del build. Las
credenciales privadas siguen en el servidor. Estos comandos EAS son instrucciones;
no se ejecutó una compilación EAS ni se generó un AAB. La APK de demostración
disponible se compiló con Gradle desde GitHub Actions.

## Comprobaciones

El registro de [VALIDATION](docs/VALIDATION.md) indica los controles ejecutados y
su resultado, además de las comprobaciones que requieren un entorno Android o
credenciales reales.

```bash
cd backend
python -m unittest discover -s tests -v
```

```bash
cd mobile
npm run typecheck
npm test
npm run doctor
npm run export:android
```

```bash
cd supabase
npm install
npm test
```

Las pruebas backend son offline y las de móvil comprueban la lógica y el estado
de demostración. El harness SQL usa PostgreSQL embebido con PGlite y también
incluye SQL ejecutable contra Supabase local. Las pruebas locales no acreditan
envíos reales ni una compilación Android; consultar el registro para su alcance
y los controles pendientes antes de publicar.

## Alcance actual

- Perfil, versiones PDF/DOCX privadas, extracción de texto revisable, chat y
  propuestas confirmables, búsquedas con horarios IANA, historial y borradores.
- Scheduler de servidor con claims, leases y deduplicación; envíos con reserva
  única, cupo global por usuario y estado `sent` solo con recibo confirmado del
  proveedor. Los recordatorios cada 72 horas requieren permiso adicional y una
  vacante vigente recuperada durante la ejecución.
- No hay OCR de PDF escaneado, proveedor de empleo contratado ni Microsoft OAuth
  completo. La detección de respuestas de correo, notificaciones push y ranking semántico
  de vacantes aún no están implementados.
- La publicación necesita despliegue/monitorización, validación con dos cuentas
  reales, pruebas de Storage y OAuth, privacidad/retención, rate limiting y revisión
  de permisos de Google y Google Play.

Ver [arquitectura](docs/ARCHITECTURE.md) y [seguridad](docs/SECURITY.md) para continuar
el desarrollo. El proyecto es una base funcional de desarrollo, con integraciones
que requieren configuración y validación antes de operar con datos reales.
