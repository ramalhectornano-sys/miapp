# Contrato de datos — Trabajo YA

Todas las fechas son ISO 8601. Los identificadores son UUID. Los registros de usuario
incluyen `user_id`; las claves foráneas compuestas impiden asociar documentos o
postulaciones de otra cuenta, incluso desde el servidor por error.

## Tablas públicas

| Tabla | Campos principales |
| --- | --- |
| profiles | user_id, full_name, city, headline, photo_path, sending_timezone (fija: America/Argentina/Buenos_Aires), created_at, updated_at |
| work_experiences | id, user_id, company, role, start_date, end_date, description |
| professional_references | id, user_id, full_name, relationship, contact, consent_to_contact |
| credentials | id, user_id, name, issuer, issued_at, expires_at, kind |
| resume_versions | id, user_id, name, original_filename, object_path, mime_type, size_bytes, sha256, extracted_text, extracted_facts, extraction_status, extraction_error |
| job_searches | id, user_id, name, roles (text[]), cities (text[]), frequency, schedule_time, timezone, weekdays (int[]), status, auto_apply, preferred_resume_id, consent_id, next_run_at, last_run_at, claim_token, lease_expires_at |
| job_search_runs | id, user_id, search_id, claim_token, worker_id, status, started_at, finished_at, found_count, message |
| jobs | id, user_id, source, external_id, fingerprint, company, title, city, url, recipient_email, recipient_verified_at, source_authorized, is_active, last_seen_at, description, payload |
| applications | id, user_id, job_id, search_id, resume_id, email_connection_id, company, job_title, recipient_email, recipient_verified_at, subject, body, status, provider_message_id, provider_confirmed_at, sent_at, error, send_attempt_id, send_attempt_started_at, delivery_uncertain, parent_application_id, delivery_sequence, job_match_id, sending_consent_id, sender_email |
| job_search_matches | id, user_id, job_id, search_id, run_id, observed_at, roles_snapshot, cities_snapshot |
| recipient_suppressions | user_id, recipient_email (lower/trim), stopped_at, reason (user_request/responded) |
| chat_messages | id, user_id, role, content, metadata, created_at |
| email_connections | id, user_id, provider, email, status, scopes, connected_at, revoked_at |
| sending_consents | id, user_id, search_id, resume_id (obligatorio para envíos automáticos), email_connection_id, authorized_sources (text[]), daily_limit, expires_at, authorization_text, policy_version, repeat_enabled, repeat_interval_days (3), granted_at, revoked_at |

`frequency`: `daily` / `weekly`. `weekdays`: ISO 1=lunes…7=domingo; en `daily`
puede quedar vacío. `timezone`: identificador IANA como `America/Argentina/Salta`.
`job_searches.status`: `enabled` / `paused`. El servidor calcula `next_run_at`.
`extraction_status`: `pending` / `extracted` / `error`.
`job_search_runs.status`: `running` / `completed` / `error` / `blocked`.
`applications.status`: `pending` / `sent` / `error` / `responded`.
`email_connections.provider`: `google` / `microsoft`; status `connected` / `disconnected` / `expired`.
`credentials.kind`: `license` / `course` / `certification`.

`jobs.fingerprint` es una clave estable de deduplicación por usuario. También se
deduplica `(user_id, source, external_id)` cuando existe external_id. Solo el
servidor puede escribir evidencia de verificación de ofertas, estados de envío y
recibos de proveedor. `sent` y `responded` requieren id, confirmación y fecha de envío.

## RPC del servidor (solo service_role)

- `claim_due_searches(p_worker_id text, p_limit_count int=10, p_lease_seconds int=300)` → array JSON de búsquedas con `run_id`; lease exclusiva y `SKIP LOCKED`.
- `claim_search_now(p_search_id uuid, p_user_id uuid, p_worker_id text, p_lease_seconds int=300)` → búsqueda JSON con `run_id` o null; ejecución manual incluso en pausa, sin superponer una lease vigente.
- `assert_search_claim(p_search_id uuid, p_claim_token uuid)` → boolean; verifica lease vigente antes de efectos del worker, sin renovarla.
- `complete_search_run(p_search_id uuid, p_claim_token uuid, p_run_id uuid, p_status text, p_next_run_at timestamptz, p_found_count int=0, p_message text=null)` → boolean; rechaza claims vencidas/reemplazadas. Repetición no vuelve a completar. Con autorización v3 y oferta observada en ese run, puede adelantar la próxima consulta al vencimiento futuro de 72 horas desde la última confirmación por destinatario, evitando esperar al cuarto día por segundos de latencia. Ese horario exige otra consulta real de fuente y otro match; excluye supresiones, respuestas, intentos sin confirmación, cuota agotada para ese día y permisos expirados. Nunca agenda un wake ya vencido ni declara un envío. Si hubo edición de la búsqueda tras iniciarse el run, conserva el `next_run_at` actual cuando ya es futuro. Cambiar una autorización sin recalcular el horario no conserva fechas vencidas: utiliza el próximo horario futuro calculado por el worker.
- `grant_sending_consent(p_user_id uuid, p_search_id uuid, p_resume_id uuid, p_email_connection_id uuid, p_authorized_sources text[], p_expires_at timestamptz, p_authorization_text text, p_repeat_enabled bool=false)` → `{consent,search}`. Alta atómica que valida propiedad de búsqueda/CV/cuenta, Gmail y scope de envío, 1–20 fuentes sin vacíos y caducidad futura de hasta 90 días. Sin repetición, exige el texto exacto `Autorizo los envíos automáticos de esta búsqueda` y guarda `policy_version='v2'`. Con repetición exige `Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día`, guarda `v3`, `repeat_enabled=true` y `repeat_interval_days=3`. Revoca permisos anteriores y alinea búsqueda/CV/remitente; jamás amplía automáticamente un consentimiento v2 a recordatorios. El backend valida que las fuentes sean integraciones disponibles y autorizadas.
- `create_initial_application(p_application jsonb)` → aplicación JSON. Inserta solo campos de borrador y devuelve la fila inicial existente si `(user_id,job_id)` ya tiene una; no modifica un historial ni acepta estados/recibos desde el JSON. Es idempotente bajo lock por usuario. Reemplaza el `ON CONFLICT(user_id,job_id)` que ya no corresponde a un índice total.
- `prepare_automatic_application(p_application_id uuid, p_user_id uuid)` → aplicación JSON o null. Solo un borrador pendiente sin reserva; vuelve a verificar consentimiento, CV, Gmail, fuente y destinatario vigente. Selecciona evidencia fresca del run y alinea `job_match_id`, CV y cuenta, conservando asunto y mensaje. Los hijos requieren autorización v3. Preparar no reserva ni envía.
- `prepare_followup_application(p_root_application_id uuid, p_user_id uuid, p_search_id uuid, p_run_id uuid, p_claim_token uuid)` → hijo nuevo/existente sin reserva o null. Requiere postulación inicial confirmada, consentimiento v3 vigente y nueva observación de la misma vacante en la fuente autorizada, con la lease actual y los criterios de búsqueda actuales. Solo después de 72 horas desde la última confirmación del proveedor para el destinatario canónico; impide respuestas, bloqueos del usuario, ofertas cerradas, fuente/recipient cambiado y cualquier intento previo sin confirmación. Reutiliza únicamente un borrador todavía sin intento; cada entrega real ocupa su propia fila, `parent_application_id` apunta a la inicial y `delivery_sequence` aumenta.
- `claim_application_send(p_application_id uuid, p_user_id uuid, p_explicit_manual_consent bool=false, p_manual_approval_text text=null)` → aplicación JSON o null. Reserva **un** intento; no equivale a correo enviado. Serializa por usuario usando advisory lock transaccional, vuelve a validar todos los permisos, fuente/CV/Gmail y match de la lease vigente antes de un automático. El máximo es **10 reservas diarias por usuario**, sumando todas las búsquedas, aprobaciones manuales, recordatorios, errores y resultados inciertos, en `profiles.sending_timezone`, fija en Buenos Aires. Cambiar el horario/zona de una búsqueda o recrear el perfil no recicla cuota. Un consentimiento con límite menor conserva su restricción. Para el mismo correo normalizado, una confirmación dentro de las últimas 72 horas bloquea otra reserva; una reserva pendiente o incierta bloquea sin caducidad automática. Los recordatorios bloquean también cualquier intento sin confirmación, una respuesta o una supresión. La aprobación individual exige exactamente `Enviar esta postulación`; no evade el techo ni el cooldown. Guarda CV, remitente `sender_email`, consentimiento `sending_consent_id` e intento. El worker jamás sustituye permiso automático por aprobación manual.
- `stop_recipient_followups(p_user_id uuid, p_application_id uuid, p_reason text='user_request')` → supresión JSON o null. Solo backend tras validar JWT. Detiene recordatorios para la dirección canónica en todas las búsquedas del usuario y mantiene la primera fecha. Con `responded` exige envío confirmado y registra su estado respondido, sin cambiar mensaje/recibo; `user_request` no rebaja una respuesta anterior. No deshace entregas ya reservadas ni accede a cuentas ajenas.
- `store_email_secret(p_connection_id uuid, p_user_id uuid, p_encrypted_payload text, p_key_id text='v1')` → void.
- `get_email_secret(p_connection_id uuid, p_user_id uuid)` → `{encrypted_payload,key_id}` o null.
- `store_oauth_state(p_state_hash text, p_user_id uuid, p_provider text, p_encrypted_verifier text, p_redirect_uri text, p_scopes text[], p_expires_at timestamptz)` → void.
- `consume_oauth_state(p_state_hash text, p_provider text)` → estado JSON o null; eliminación atómica, un solo uso, caducidad validada. Estado hash SHA-256, nunca el nonce público.

Tokens y verificadores se guardan cifrados por el backend con una clave externa
a la base de datos. Sus tablas están en `private`, fuera de los schemas expuestos
por PostgREST. Las RPC no cifran ni descifran: nunca pasar texto claro.

## Acceso de Android

CRUD propio: profile, experiencia, referencias, credenciales; lectura propia en
el resto. Inserción de CV solo campos `id,user_id,name,original_filename,object_path,
mime_type,size_bytes,sha256`; el backend escribe extracción. Chat cliente solo
puede insertar mensajes `role='user'`. Búsquedas, consentimientos y postulaciones
se crean mediante endpoints del backend tras validar el JWT y la solicitud.
`revoke_sending_consent(p_consent_id uuid)` es RPC del usuario; invalida la
autorización y desactiva el envío automático de sus búsquedas asociadas. Se
serializa con altas y reservas por usuario y no permite revocar cuentas ajenas.
Revocar un consentimiento anterior no desactiva un consentimiento más reciente.

Buckets privados `resumes` (PDF/DOCX, hasta 10 MiB) y `profile-photos` (JPEG/PNG/WebP,
hasta 5 MiB); ruta `<auth.uid()>/<uuid>.<ext>`. El cliente no puede sobreescribir CV
ya existentes; el backend descarga con service role y el usuario usa URL firmada.
La eliminación completa la coordina el backend: purga objetos de ambos buckets y
elimina `auth.users`, que propaga cascadas a todos los datos de cuenta. Un error de
Storage debe impedir afirmar que la eliminación fue completa.

`last_run_at` representa la última búsqueda completada. Los intentos bloqueados
o con error se consultan en `job_search_runs`; no se muestran como búsquedas
completadas en Android.

## Evidencia y deduplicación de recordatorios (migración 005)

La vacante sigue deduplicada por fingerprint. La postulación inicial conserva un
índice único parcial `(user_id,job_id) WHERE parent_application_id IS NULL`; los
hijos usan índice único `(user_id,parent_application_id,delivery_sequence)`.
Cada fila es una entrega independiente en el historial. Una vez reservada no se
pueden cambiar asunto, mensaje, CV, remitente, destinatario, familia, aprobación,
match ni intento. La confirmación y su fecha quedan inmutables; solo se puede
registrar una respuesta o conciliar un resultado incierto con recibo del proveedor.

`job_search_matches` es escritura exclusiva del servidor después de consultar la
fuente: no es una autorización de Android. El trigger verifica run/lease activos,
snapshots exactos de roles/ciudades y `observed_at` dentro del run y de la última
hora. El backend normaliza la fuente, excluye anuncios cerrados y verifica los
requisitos antes de registrar un match; la base no inventa compatibilidad. Envíos
automáticos iniciales y repetidos necesitan esa evidencia. Una oferta ausente del
nuevo feed no recibe match y no habilita reenvíos. `last_seen_at` por sí sola no
habilita un envío ni prueba que la búsqueda se completó.

El cliente no puede borrar objetos de CV asociados a aplicaciones ni reemplazar
sus bytes mediante borrar/subir en la misma ruta. El trigger de Storage lo bloquea
para `authenticated`; `service_role` conserva el borrado integral de cuenta.
CV sin postulaciones siguen siendo eliminables. `recipient_suppressions` y
`job_search_matches` tienen RLS de lectura propia y ninguna escritura del cliente.
