# Supabase — Trabajo YA

El esquema está preparado para un proyecto Supabase independiente por entorno.
Android usa una clave pública `sb_publishable_…` (o la anterior `anon`) y el JWT
del usuario. FastAPI usa la clave privada `sb_secret_…` (o la anterior
`service_role`) solo dentro del servidor; esa clave nunca pertenece al bundle de
Expo. Los nombres de configuración conservan compatibilidad: la clave pública
va en `SUPABASE_ANON_KEY` y `EXPO_PUBLIC_SUPABASE_ANON_KEY`; la privada va únicamente
en el secreto del servidor `SUPABASE_SERVICE_ROLE_KEY`.

## Proyecto nuevo desde el celular

La ruta más corta es ejecutar [install-new-project.sql](install-new-project.sql)
una sola vez. El archivo reúne las **seis migraciones en orden**, sin
usuarios de demostración ni credenciales. Usá un proyecto Supabase nuevo, dedicado
a Trabajo YA, antes de registrar usuarios en la app.

1. Creá el proyecto en el Dashboard de Supabase y esperá a que esté disponible.
2. Abrí **SQL Editor → New query**. Si el menú no se ve en el celular, activá
   **Sitio de escritorio** en el navegador.
3. Abrí el archivo completo del proyecto descargado y copiá todo su contenido,
   desde el encabezado hasta `COMMIT;`. Pegalo en una consulta nueva, con el rol
   `postgres`, y presioná **Run**. No ejecutes fragmentos ni agregues claves.
4. Verificá que la consulta termine sin errores y que Table Editor muestre, entre
   otras, `profiles`, `job_searches` y `applications`. En Storage deben aparecer
   `resumes` y `profile-photos` como buckets privados.
5. Configurá Auth/SMTP y las claves públicas/privadas mediante los secretos y
   variables de la [guía de Render gratuito](../deploy/render/README.md) o la
   [guía de Google Cloud](../deploy/google-cloud/README.md).

El instalador comprueba el estado antes de crear objetos y usa una transacción
completa: rechaza tablas, funciones, permisos o buckets de Trabajo YA existentes,
y usuarios ya registrados en Auth. Las tablas estándar vacías de Auth/Storage
son compatibles. Tu cuenta del Dashboard de Supabase no es un usuario de Auth
del proyecto y no bloquea esta instalación. Si falla alguna instrucción, no se
confirma una instalación parcial. No borra ni reinicia una base existente.

**Elegí una sola ruta por base:** este archivo para SQL Editor **o** migraciones
administradas por Supabase CLI. El instalador de SQL Editor no registra el
historial del CLI; no ejecutes después `supabase db push` contra esa misma base
sin preparar una línea base del historial. Si usaste el archivo único, las
actualizaciones se aplican con los nuevos archivos de migración, una vez y en
orden; no vuelvas a ejecutar el instalador completo. En una base ya administrada
por CLI, aplicá únicamente las migraciones pendientes con `supabase db push`.

Si ya instalaste las migraciones 001 a 005, aplicá solamente
[006: CV principal persistente](migrations/202610130006_persistent_primary_resume.sql).
La nueva columna guarda la selección por usuario y la función de registro
asocia el CV y su elección en una transacción. El perfil conserva sus otros
datos. La clave foránea compuesta impide elegir CV de otra cuenta y limpia
únicamente la selección al borrar ese documento.

Para regenerar o comprobar el archivo, desde la raíz del proyecto:

```bash
python scripts/build_database_install.py
python scripts/build_database_install.py --check
```

La generación es determinista y el encabezado incluye la huella SHA-256 de cada
migración. Las pruebas del generador comprueban orden, contenido exacto, guardas
y detección de archivos desactualizados; no ejecutan SQL. El esquema `private`
debe quedar fuera de los schemas expuestos por la API.

## Instalación local

1. Instalar [Supabase CLI](https://supabase.com/docs/guides/cli) y Docker.
2. Desde la raíz del proyecto, ejecutar `supabase start` y `supabase db reset`
   únicamente sobre el entorno local de desarrollo; reset elimina sus datos.
3. Copiar la URL/clave pública a Expo y la URL/clave de servidor a FastAPI.
4. El correo de confirmación local aparece en el capturador de correo que informa
   `supabase status`. En producción mantener verificación y configurar SMTP.

Como ruta alternativa para un proyecto remoto propio nuevo, revisar primero las migraciones, vincularlo con
`supabase link --project-ref <referencia>` y aplicar `supabase db push`. Nunca usar
un proyecto ajeno o una base de producción para estas pruebas. El esquema
`private` debe quedar fuera de los schemas expuestos por la API.

No hay seed automático ni postulaciones ficticias enviadas en la base de datos.
Las vistas de demostración de la aplicación deben indicarlo expresamente.

## Modelo y permisos

Ver [CONTRACT.md](CONTRACT.md) para nombres, campos y firmas RPC exactas. Todas las
tablas de usuario tienen RLS. Las claves foráneas incluyen `user_id` para evitar
que el backend asocie por accidente un CV de otra cuenta. Solo el servidor escribe
ofertas verificadas, búsquedas programadas, consentimientos, historiales de tarea
y postulaciones. Android puede leer sus registros y editar el perfil propio.

Los buckets `resumes` y `profile-photos` son privados. Cada objeto usa un prefijo
con UUID del usuario. Storage entrega descargas mediante JWT o URL firmada de
corta duración; nunca guardar URLs públicas de los CV. Las versiones de CV no se
sobreescriben. El cliente tampoco puede borrar/recrear en la misma ruta un CV
asociado al historial. El servidor conserva el borrado completo de cuenta. La eliminación de un documento usado por una postulación requiere
coordinar también su historial desde el servidor.

Los tokens OAuth y verificadores PKCE se cifran en FastAPI antes de pasar a RPC,
con una clave de cifrado externa a Supabase. El campo `key_id` permite identificar
versiones para futuras rotaciones. No guardar tokens en `metadata`, `payload`,
mensajes de chat ni logs. Las conexiones públicas solo exponen cuenta, permisos
y estado. El nonce OAuth se guarda como hash SHA-256, caduca en máximo 15 minutos
y se consume con una eliminación atómica.

## Envíos y planificación

Las funciones de claims solo admiten `service_role`. Una tarea crea un registro
`running` únicamente al obtener una lease exclusiva. `complete_search_run` debe
recibir el token de esa lease y un próximo horario futuro. Una lease vencida no
puede completar el registro; cuando otro worker la recupera, el intento anterior
queda en error con un mensaje que expresa que no hubo confirmación. `blocked`
sirve para fuentes ausentes o no configuradas, sin fingir una búsqueda realizada.

Antes de llamar al correo, el backend reserva una postulación con
`claim_application_send`. Valida fuente autorizada, destinatario verificado,
propiedad del CV, cuenta conectada, consentimiento vigente, fuente/CV/remitente
autorizados y límite diario. El límite GLOBAL es de 10 reservas por usuario por día en Buenos Aires, sumando
todas las búsquedas, recordatorios y aprobaciones manuales. Por seguridad los
intentos fallidos y resultados inciertos también consumen cuota; no se recicla.
La zona del horario de cada búsqueda no altera la zona fija del presupuesto. La aprobación manual queda
registrada con fecha y el texto presentado al usuario; tampoco excede la cuota.

La migración 005 permite recordatorios con autorización explícita v3 renovada;
los permisos v2 conservan solo envíos iniciales. Se espera un mínimo de 72 horas
desde la última confirmación al mismo destinatario (normalizado), incluyendo
otras búsquedas. Cada recordatorio ocupa una nueva fila histórica, sin resetear
intentos ni cambiar el mensaje/CV/recibo anteriores. Solo procede si una consulta
nueva de fuente autorizada redescubre la misma vacante vigente y compatible en
la lease actual. Un resultado incierto, una reserva pendiente, una respuesta o
una detención del usuario impiden recordatorios. Los intentos sin confirmación
requieren revisión: no se vuelven a enviar automáticamente. Cuando las 72 horas
vencen después del horario diario se agenda una nueva consulta al vencer; el
worker debe consultar otra vez la fuente, sin reutilizar el resultado guardado.
Los nuevos puestos de cada ejecución se procesan antes que sus recordatorios.

La reserva se realiza una sola vez. Si un proveedor produce un timeout después
de recibir la petición, marcar `delivery_uncertain=true` y no reintentar hasta
conciliar con evidencia del proveedor. Un estado `sent` o `responded` requiere
identificador y confirmación del proveedor, fecha de envío, destinatario verificado
y reserva. Un recibo solo prueba aceptación del proveedor, no entrega al buzón.
Revocar consentimiento invalida la autorización y apaga `auto_apply` atómicamente.

La eliminación total de una cuenta se realiza en FastAPI: revocar conexiones,
purgar todos los objetos de ambos buckets con paginación y eliminar el usuario
mediante Auth Admin. Las claves foráneas propagan el borrado a datos de cuenta y
secretos. No afirmar eliminación completa si una de estas operaciones falla.

## Pruebas

El harness usa PostgreSQL embebido en WASM, no mocks de SQL. Ejecuta las baterías
de contrato 004 antes de aplicar 005 y luego la batería vigente 005:

Las pruebas SQL están incluidas, pero no se ejecutaron en el entorno de entrega
porque no se pudo instalar PGlite. No se aplicaron migraciones a servicios reales.

```bash
cd supabase
npm install
npm test
```

Valida las migraciones, aislamiento A/B, privilegios de columnas, CV privado,
prohibición de receipts falsos, deduplicación, lease exclusiva, finalización
idempotente, reserva de un único envío, límite global entre búsquedas/aprobaciones
manuales/errores, cooldown canónico, recordatorios con consentimiento v3, historial
inmutable, nuevas observaciones de fuente, detención por respuesta, zona fija
incluso al recrear perfil, protección de CV en Storage, wakes futuros de 72 horas,
OAuth de un uso y revocación.
El bootstrap recrea el contrato mínimo de Auth/Storage para las pruebas; no
comprueba la API de Storage, OAuth externo ni procesos concurrentes en sockets.
La misma batería SQL puede ejecutarse contra Supabase local con `psql` como
administrador y se revierte al terminar:

```bash
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres \
  -v ON_ERROR_STOP=1 -f supabase/tests/daily_budget_and_followups.sql
```

Antes de publicar, verificar también llamadas HTTP con dos JWT independientes,
Storage firmado, workers concurrentes y el proveedor real en cuentas de prueba.

La exclusión mutua real también tiene un harness opcional con **24 procesos psql
concurrentes**, dos búsquedas con zonas diferentes y reservas automáticas/manuales.
Requiere las seis migraciones ya aplicadas a Supabase local, psql y conexión como
administrador. Solo admite localhost, crea su propia cuenta ficticia aleatoria,
comprueba exactamente diez reservas y cero recibos, y borra su fixture al terminar.
No se ejecutó en este entorno porque no hay PostgreSQL instalado:

```bash
cd supabase
DATABASE_TEST_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres npm run test:concurrency
```

Nunca conectarlo a producción. Esta prueba no abre Gmail, no consulta portales ni
envía correos; comprueba las reservas atómicas de base de datos en sesiones reales.
