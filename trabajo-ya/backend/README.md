# Backend — Trabajo YA

FastAPI valida la sesión en Supabase Auth y opera con datos del usuario. El worker
es un proceso separado; las búsquedas continúan con el celular apagado si ambos
servicios están desplegados. Esta versión no trae fuentes de empleo ni cuentas de
correo conectadas. No realiza búsquedas ficticias ni registra envíos de muestra.

## Instalación

Python 3.12 o posterior, desde este directorio:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Aplicar primero todas las migraciones de `../supabase/migrations/` en orden;
para una instalación existente, `supabase db push` aplica las pendientes antes
de actualizar API y worker. La versión 0.3 agrega el cupo global y los
recordatorios; los permisos V2 conservan envíos iniciales, pero no habilitan
recordatorios sin renovación explícita. Completar URL, clave
pública y clave de servicio de Supabase en `.env`. La clave de servicio y la clave
de cifrado pertenecen exclusivamente al servidor. Documentación OpenAPI disponible
en `http://localhost:8000/docs`; `/health` distingue configuración de disponibilidad
verificada. Android Emulator accede al servidor local mediante `10.0.2.2:8000`.
En un dispositivo físico usar la IP LAN de la computadora; producción debe usar
HTTPS. Permitir solo los orígenes web necesarios en `CORS_ORIGINS` si se usa Expo web.

```bash
# Segunda terminal; mantenerlo como servicio en producción
python -m app.worker
# Procesar hasta WORKER_BATCH_SIZE tareas y terminar (también sirve para cron)
python -m app.worker --once
python -m unittest discover -s tests -v
```

El worker reclama una tarea a la vez mediante bloqueo SQL `SKIP LOCKED`; cada lease
dura una hora. Los resultados se completan con el token de claim. Si muere el
proceso, la tarea puede recuperarse al vencer el lease. Vacantes y borradores se
deduplican por usuario en la base. Cada registro de postulación reserva **un único
intento de envío** antes de llamar al proveedor. Los recordatorios autorizados
crean nuevos registros vinculados a la postulación original; un resultado incierto
no se reintenta automáticamente. Los errores de consulta de fuentes se pueden intentar
en la siguiente fecha programada. Consultar historial `job_search_runs` para
distinguir `running`, `completed`, `error` y `blocked`.

Cada ejecución tiene un plazo máximo de 15 minutos y termina al menos 90 segundos
antes de vencer su reserva. Verifica en SQL el token y la vigencia de la reserva
antes de cada lote, creación de borrador y envío automático. Procesa hasta 200
vacantes pendientes por ejecución; consulta registros previos en páginas de 1000
para que los siguientes lotes avancen sin duplicar los primeros. Un plazo vencido
conserva resultados parciales y registra `error`. La finalización SQL conserva una
próxima fecha que el usuario haya editado mientras la tarea estaba en ejecución.

## Contrato HTTP

Todas las rutas `/api`, salvo callback OAuth, requieren `Authorization: Bearer
<access_token de Supabase>`. No se aceptan JWT simplemente decodificados: el
servidor consulta `/auth/v1/user`. No existe usuario ficticio en el backend.
El registro y acceso sin contraseña ocurren en Supabase Auth: solicitud de Email
OTP y verificación `type: 'email'`, con sesión real. Configuración SMTP y plantillas
en [AUTH_SETUP.md](../docs/AUTH_SETUP.md); el backend no acepta un correo ingresado
como sustituto del access token.

| Ruta | Resultado |
| --- | --- |
| `POST /api/chat` | `{message,history?}` → `{reply,proposal?,mode}`; guarda ambos mensajes, sin ejecutar propuestas |
| `GET /api/chat/history` | Últimos 100 mensajes, en orden cronológico |
| `GET /api/integrations` | Fuentes permitidas `{id,name}`, cuentas propias y `mail_policy` con cupo/zona/intervalo; no expone URLs ni secretos |
| `GET/POST /api/searches` | Lista o guarda una propuesta confirmada; POST devuelve `{search,automatic_authorization_required,message}` |
| `PATCH /api/searches/{id}` | Cambia `status`, `time`, `timezone`, `frequency`, `weekdays`, `resume_id`; recalcula próxima fecha |
| `POST /api/searches/{id}/run` | Consulta real de fuentes autorizadas; 503 si no hay ninguna fuente |
| `GET /api/searches/{id}/runs` | Últimas 50 ejecuciones verificables |
| `POST /api/resumes/{id}/extract` | Texto extraído de PDF/DOCX; `profile_saved:false`, revisión requerida |
| `DELETE /api/resumes/{id}` | Elimina CV privado; bloquea versiones asociadas a búsquedas, permisos o historial |
| `GET /api/applications` | Historial propio; el recibo del proveedor acredita un envío |
| `PATCH /api/applications/{id}` | Edita `subject`, `body`, `resume_id`, `email_connection_id` de borradores sin intentos |
| `POST /api/applications/{id}/send` | `{consent:true,acknowledgment:"Enviar esta postulación"}`; autorización para ese envío |
| `POST /api/applications/{id}/stop-followups` | `{reason:"user_request"}` o `{reason:"responded"}`; detiene recordatorios a ese correo en todas las búsquedas propias |
| `POST /api/mail/google/start` | URL de autorización OAuth de Google |
| `GET /api/mail/google/callback` | Consume estado de un solo uso y guarda conexión cifrada |
| `POST /api/mail/consents` | Autoriza búsqueda/CV/cuenta/fuentes por máximo 90 días; `repeat_every_days` igual a 0 o 3, cupo global 10/día |
| `GET /api/mail/consents` | Consulta permisos propios y su estado vigente, vencido o revocado |
| `DELETE /api/mail/consents/{id}` | Revoca autorización y deshabilita automatización |
| `DELETE /api/account` | Purga buckets privados antes de eliminar cuenta y cascadas |

Las propuestas tienen `title`, `role`, `city`, `frequency:daily|weekly`, `time:HH:MM`,
`timezone:IANA`, `weekdays:[1..7]`, `mode:manual|automatic`, `resume_id?`. Se guardan
con `auto_apply=false` incluso si la IA propone modo automático. El envío necesita
un consentimiento independiente. Payload de autorización:

```json
{
  "search_id": "UUID de la búsqueda",
  "resume_id": "UUID del CV",
  "email_connection_id": "UUID de la cuenta conectada",
  "allowed_sources": ["partner"],
  "expires_at": "2026-11-01T00:00:00Z",
  "repeat_every_days": 3,
  "acknowledgment": "Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día"
}
```

Sin recordatorios, usar `repeat_every_days:0` y
`"acknowledgment":"Autorizo los envíos automáticos de esta búsqueda"`.
Omitir `repeat_every_days` equivale a `0`. El backend no infiere el permiso de
reiteración desde el chat ni desde una cuenta OAuth conectada. El consentimiento
con recordatorios usa política V3, `repeat_enabled=true` e intervalo de 3 días.

La extracción reproduce el texto del archivo; no inventa información ni modifica
el perfil. El usuario revisa y edita campos del perfil con su sesión y RLS. Los PDF
escaneados necesitan un futuro módulo OCR; no se inventan datos cuando no hay texto.
No enviar el CV completo a un proveedor externo sin configurar una política de
privacidad y consentimiento para ese tratamiento.

Una autorización vigente habilita los envíos de cada ejecución diaria sin aprobar
cada postulación. Se mantiene acotada al CV, la cuenta y las fuentes elegidas;
renovarla sustituye de forma atómica la anterior. El worker contempla también
borradores pendientes compatibles con ese permiso que aún no tengan un intento
reservado y cuya oferta volvió a aparecer vigente en la consulta actual.
Pausar o revocar detiene futuras reservas. El límite es **10 intentos por usuario
y día**, sumando todas sus búsquedas y cuentas conectadas, los envíos manuales y
los recordatorios. Cuenta incluso fallos o resultados inciertos; no existe un
cupo nuevo por búsqueda. Usa el día calendario de `profiles.sending_timezone`,
una zona estable de cuenta inicialmente `America/Argentina/Buenos_Aires` que el
cliente no puede editar. La zona de cada búsqueda solo controla el horario del
scheduler.

Dentro de una ejecución se priorizan los envíos iniciales y después los
recordatorios. Estos requieren 72 horas completas desde el último envío
confirmado al correo de la empresa, normalizado con minúsculas y sin espacios
externos, entre todas las búsquedas del usuario. Debe existir consentimiento
vigente con recordatorios y una vacante recuperada durante la ejecución actual,
compatible, activa y con destinatario verificado. Una respuesta registrada o un
intento pendiente o incierto a ese correo impide la reiteración automática. Si
hay menos vacantes aptas, se envían menos; si no hay ninguna, no se envía.

Cada recordatorio tiene su propia fila y un único intento, con
`parent_application_id` apuntando al envío inicial y `delivery_sequence > 0`.
El registro inicial tiene padre nulo y secuencia `0`. Cada fila conserva mensaje,
CV, remitente y recibo confirmados; crear un recordatorio no modifica el historial
del envío anterior.

Para detener los recordatorios a una empresa, usar
`POST /api/applications/{id}/stop-followups` con
`{"reason":"user_request"}`; `"responded"` registra que el usuario informó una
respuesta, sin afirmar que se leyó automáticamente la bandeja. Devuelve
`{stopped:true,recipient_email,stopped_at,reason,message}`. El bloqueo se aplica a
ese correo entre todas las búsquedas propias. No cancela un envío ya reservado.
`GET /api/applications` incluye `followups_stopped`, `followups_stopped_at` y
`followups_stop_reason` para mostrar ese estado. El motivo `responded` exige una
postulación confirmada y actualiza su estado a `responded` por declaración manual
del usuario; no consulta la bandeja.

## IA abierta/configurable

`AI_PROVIDER=demo` usa un intérprete simple en español, devuelve propuestas con
etiqueta `demo`, sin llamadas de modelo. Para Ollama instalar el modelo y configurar
`AI_PROVIDER=ollama`, `AI_BASE_URL=http://localhost:11434`, `AI_MODEL=qwen2.5:7b`.
Para una API compatible usar `AI_PROVIDER=openai_compatible`, URL terminada en
`/v1`, modelo y clave propios. La respuesta del modelo se valida con esquema
cerrado. Su texto libre nunca decide consentimiento, estados o supuestas acciones:
el servidor construye la respuesta visible. Historial conversacional no es una
fuente de permisos.

La activación preparada usa Groq con `openai/gpt-oss-20b`, salida JSON y clave
privada solo en el servidor. Ver [IA_REAL](../docs/IA_REAL.md). Con las variables
reales cargadas, `python -m app.check_ai` comprueba una respuesta del proveedor
mediante una instrucción sintética sin Supabase, CV ni Gmail. Un error termina
con código 1 y `verified:false`; nunca se reemplaza por una respuesta demo.

## Fuentes permitidas

Configurar `AUTHORIZED_JOB_FEEDS` con fuentes propias o acuerdos explícitos:

```json
[{"id":"partner","url":"https://partner.example/jobs.json","authorized":true,"recipient_verification":"source_attestation"}]
```

El endpoint debe devolver un array, o `{"jobs":[...]}`. Cada vacante:

```json
{"id":"123","company":"Empresa","title":"Chofer","city":"Rincón de los Sauces","url":"https://partner.example/123","description":"Requisitos publicados","recipient_email":"empleo@empresa.example","recipient_verified":true,"is_active":true,"valid_until":"2026-11-01T23:59:59Z"}
```

Solo se considera verificado el correo si la integración declara
`recipient_verification=source_attestation` **y** la vacante acredita la verificación.
Este contrato debe estar respaldado por el proveedor real; no usar una fuente
genérica como evidencia. No hay scraping de portales. La consulta bloquea HTTP,
redes privadas y redirecciones; límite 20 fuentes/2000 filas por fuente/5 MiB.
Filtra ciudad exacta y coincidencia textual de puesto: este es el análisis básico
de compatibilidad del MVP, sin puntajes de IA inventados. Vacantes sin correo
verificado quedan como borradores para intervención humana.

El proveedor debe mantener la lista vigente. `is_active:false`, un estado de
cierre reconocido o `valid_until` vencido descartan la oferta. Una entrada sin
`is_active` se trata como activa por compatibilidad; para una integración nueva,
declararlo expresamente y actualizar los cierres. `valid_until` es opcional y usa
fecha y hora ISO con zona horaria. El worker necesita volver a obtener la vacante de la fuente autorizada
en la ejecución actual antes de enviar o preparar un recordatorio: el historial
de ofertas no acredita vigencia. La base exige la observación reciente y la lease
del run reclamado. Una fuente inaccesible no habilita recordatorios basados en
ofertas antiguas.

## Google OAuth y envío real

Registrar cliente OAuth tipo web en Google Cloud. Agregar el callback exacto,
habilitar Gmail API y configurar pantalla de consentimiento, usuarios de prueba y
verificación de permisos antes de publicar. Usamos `gmail.send`, `userinfo.email`
y `openid`, no acceso a bandeja de entrada. Esto implica que **la detección de
respuestas todavía no está implementada**; no se asigna `responded` ficticiamente.
Microsoft queda como siguiente adaptador, no se presenta como conectado.

Generar `TOKEN_ENCRYPTION_KEY` con Fernet y mantenerla estable en el gestor de
secretos. Los tokens y verificadores PKCE se cifran y se guardan en tablas privadas
mediante RPC exclusivas de servicio. Los estados OAuth se guardan como hash y se
consumen atómicamente. Un correo conectado no concede permiso de envío.

`MAIL_SEND_ENABLED=false` por defecto. Solo activar tras una prueba controlada con
una cuenta y destinatario autorizados. El servidor revisa propietario del CV,
destinatario coincidente con vacante verificada, fuente autorizada, cuenta
conectada y consentimiento antes del envío. La reserva SQL vuelve a validar esas
condiciones y serializa el límite diario. Nunca se marca `sent` sin ID confirmado
por Gmail. Si el envío se confirmó pero no pudo guardarse, queda reservado y se
registra el ID de comprobante en el log del servidor para revisión; no se reenvía.
No registrar cuerpos, CV o tokens en logs. Proteger los logs y el acceso operativo.

## Antes de publicar

Desplegar API y worker como servicios separados con HTTPS, secretos externos,
monitoreo, backup, retención y política de privacidad. Añadir límites de solicitudes
por usuario en el gateway, verificación OAuth de producción, auditoría de permisos
y pruebas contra Supabase/Gmail reales con cuentas de prueba. Las pruebas incluidas
son offline: no certifican disponibilidad de esos proveedores. Dockerfile permite
ejecutar API; para el worker usar el mismo contenedor con `python -m app.worker`.
No compartir service-role con la aplicación móvil.

## Búsqueda web con IA

Además de los feeds JSON permitidos, `WEB_SEARCH_PROVIDER=tavily` y `WEB_SEARCH_API_KEY` habilitan consultas de Internet por puesto y ciudad. `WEB_SEARCH_MAX_QUERIES=2` limita el costo por ejecución. La IA extrae solo anuncios con citas de empresa, puesto y ciudad, y conserva enlaces para revisión. El endpoint `GET /api/searches/{id}/results` devuelve los hallazgos de la búsqueda del usuario autenticado; `GET /api/searches/{id}/runs` muestra ejecuciones y errores. Los hallazgos web no habilitan consentimiento de envío automático ni verifican direcciones de correo. Ver [configuración y límites](../docs/BUSQUEDA_WEB.md).
