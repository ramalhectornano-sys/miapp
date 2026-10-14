# Búsquedas desde el servidor con GitHub Actions (pruebas)

Este programador ejecuta `python -m app.worker --once` en un servidor de GitHub,
incluso con el celular apagado. Usa el Supabase existente y los tokens de Gmail
cifrados que ya guardó la API. **El archivo se entrega desactivado**: publicarlo
no inicia búsquedas y no habilita correos.

Los runners estándar de GitHub son gratuitos en repositorios públicos, sujeto a
las condiciones y límites de GitHub. Se propone para pruebas con pocos usuarios,
no como servicio de producción. La IA, Supabase y el proveedor de búsqueda tienen
sus propias cuotas y posibles cargos. No se despliega un segundo backend ni se
requiere una segunda base de datos.

## Qué debe preparar el desarrollador

El workflow es `.github/workflows/trabajo-ya-worker.yml`. En el repositorio actual
debe copiarse también a esa ruta **en la rama predeterminada** de GitHub: los
eventos `schedule` sólo arrancan workflows que existen en esa rama. Cada ejecución
descarga explícitamente el código de `trabajo-ya-real`, donde está Trabajo YA;
no usa el código antiguo de la rama `main`.

El archivo ya contiene la selección del proyecto dentro de `trabajo-ya/` y las
URL públicas del proyecto se leen de `mobile/services.public.json`. No editar
`main` completo ni convertirla en la app real para activar este programador.

## Configurar desde el celular

1. Abrí [el repositorio](https://github.com/ramalhectornano-sys/miapp) en Chrome.
   Activá **Sitio para computadoras** si no ves todas las opciones.
2. Entrá en **Settings → Secrets and variables → Actions → Secrets**. Elegí
   **New repository secret** y cargá las claves privadas que correspondan:

   | Nombre | Qué copiar directamente al panel de GitHub |
   | --- | --- |
   | `SUPABASE_SERVICE_ROLE_KEY` | La misma Secret key/service_role privada que usa Render. La clave publicable no sirve aquí. |
   | `AI_API_KEY` | La clave privada del proveedor real de IA que usa la API. |
   | `WEB_SEARCH_API_KEY` | La clave privada de Tavily si se habilita búsqueda web. |
   | `GOOGLE_CLIENT_SECRET` | El secreto del mismo cliente OAuth web configurado en Render; requerido al habilitar envíos. |
   | `TOKEN_ENCRYPTION_KEY` | **Exactamente la misma clave de cifrado de Render**, sin regenerarla; requerida al habilitar envíos. |

   Copiá estas claves sólo entre paneles privados. No las pegues en el código,
   comentarios, chat, variables públicas ni capturas. GitHub las entrega al
   proceso del servidor; no se incorporan a la APK.

3. Abrí la pestaña **Variables → New repository variable** y cargá:

   | Nombre | Valor |
   | --- | --- |
   | `WORKER_ENABLED` | Primero `false`. Usá `true` sólo al estar lista la configuración para probar. |
   | `MAIL_SEND_ENABLED` | Primero `false`. Habilitar el worker no habilita correos. |
   | `WEB_SEARCH_PROVIDER` | `tavily` para búsqueda web; vacío si se usarán sólo feeds autorizados. |
   | `WEB_SEARCH_MAX_QUERIES` | `2` para las pruebas. El servidor admite de 1 a 6 consultas por búsqueda. |
   | `AUTHORIZED_JOB_FEEDS` | `[]` si se usa sólo búsqueda web, o la misma lista JSON de feeds autorizados de Render. |
   | `GOOGLE_CLIENT_ID` | El ID público del mismo cliente web de Render; requerido para envíos. |
   | `AI_BASE_URL` | La misma URL del proveedor de IA de Render. Por defecto: `https://api.groq.com/openai/v1`. |
   | `AI_MODEL` | El mismo modelo de Render. Por defecto: `openai/gpt-oss-20b`. |
   | `DEFAULT_TIMEZONE` | `America/Argentina/Buenos_Aires`, o la zona que corresponda a la configuración del servidor. |

   Una URL de feed nunca debe incluir una contraseña o clave privada. Las fuentes
   se configuran con autorización real: no basta marcar cualquier portal como
   autorizado. La búsqueda web encuentra páginas públicas mediante la API del
   proveedor; no inicia sesión en portales ni supera sus controles.

4. Conservá las fuentes y el modelo iguales en API y worker. Si la app necesita
   ver Tavily como fuente disponible, configurá también `WEB_SEARCH_PROVIDER` y
   `WEB_SEARCH_API_KEY` en **Render → Environment**, y desplegá el backend actualizado.
5. Cambiá `WORKER_ENABLED` a `true`, conservando `MAIL_SEND_ENABLED=false`.
6. Abrí **Actions → Búsquedas programadas de Trabajo YA (pruebas) → Run workflow**
   y elegí la rama predeterminada. Si no aparece, el archivo todavía no está
   publicado en esa rama, o Actions está deshabilitado en el repositorio.

## Comprobar primero la búsqueda

En la app, guardá y confirmá una búsqueda con puesto, ciudad y horario, y dejala
habilitada. El chat proponiendo un horario no acredita una ejecución. El worker
procesa una búsqueda pendiente por vez: una ejecución manual sin tareas vencidas
puede terminar bien sin buscar nada. Para una prueba inmediata, usá **Ejecutar
ahora** en la app para verificar la fuente; para comprobar el programador, revisá
una búsqueda cuyo horario ya haya llegado.

Comprobá en **Búsquedas** el historial, la hora y el resultado real. Cero vacantes
es un resultado válido si la fuente fue consultada correctamente. Si el job falla
porque faltan secretos o fuentes, no se inició la búsqueda. No se crea un envío
para compensar un fallo. Si hay un error de base de datos o de API, revisá el
mensaje del job sin compartir claves ni información privada.

## Habilitar correos sólo después de esa comprobación

La cuenta Gmail ya vinculada sigue siendo válida siempre que API y worker usen
el mismo cliente OAuth, Supabase y `TOKEN_ENCRYPTION_KEY`. En el proyecto Google
debe seguir habilitada Gmail API y el permiso `gmail.send` de esa conexión. En
Testing externo, Google puede vencer refresh tokens a los siete días; reconectá
si ocurre durante las pruebas.

1. Completá los secretos de Gmail y el ID público del cliente web en GitHub.
2. Mantené desactivadas las autorizaciones automáticas para una prueba controlada con una integración y destinatario propios y autorizados. Habilitá temporalmente `MAIL_SEND_ENABLED=true` solo en Render y desplegá para permitir ese envío manual expresamente aprobado. Comprobá su confirmación real en **Mis postulaciones**. No envíes ensayos a empresas.
3. Configurá `MAIL_SEND_ENABLED=true` en Render y en Variables de GitHub cuando
   estén listas las dependencias. Desplegá Render después de cambiar su variable.
4. En la app autorizá cada búsqueda: CV, cuenta, fuentes, vencimiento y, si se
   desea, recordatorios. Tener Gmail conectado no sustituye ese consentimiento.
5. Verificá en **Mis postulaciones** una confirmación de Gmail. Un job verde,
   un borrador preparado o una respuesta de la IA no equivalen a un envío.

Los fragmentos obtenidos con Tavily se preparan para revisión manual. La integración independiente **Ofertas verificadas de Greenhouse** puede comprobar los enlaces oficiales mediante su API pública, solo si la oferta publica expresamente un correo para recibir CV. Los otros enlaces siguen para revisión; no se certifican porque aparezcan en el buscador. Ver [activación de correos](ACTIVAR_CORREOS.md). La automatización de correo requiere una fuente autorizada
que certifique el destinatario según el contrato del backend. No se envía a un
correo inventado. Los envíos aptos conservan el máximo de **10 intentos al día por
usuario**, y los recordatorios autorizados esperan **72 horas completas**.
Las reservas de envío persisten en Supabase: otro job no repite un intento con
resultado incierto ni borra esas reservas para volver a enviar.

## Horarios y límites de esta alternativa

- GitHub consulta cada 15 minutos, en los minutos 7, 22, 37 y 52 de cada hora
  UTC. El horario de cada búsqueda y el presupuesto diario los determina el
  servidor con la zona guardada; no hay que convertir el horario del chat a UTC.
- El cron puede demorarse o perder ejecuciones cuando GitHub tiene carga. Una
  cola o varios usuarios agregan demora. No garantiza enviar exactamente a las
  09:00 ni dentro de los siguientes 15 minutos.
- Cada job admite 25 minutos y procesa una búsqueda por vez. Las ejecuciones
  del mismo workflow no se superponen; las reservas de Supabase también protegen
  frente a otros workers. No agregar un segundo programador para la misma base
  sin revisar su coordinación.
- En repositorios públicos, GitHub desactiva programadores tras 60 días sin
  actividad. Revisá Actions y reactivá el workflow cuando corresponda.
- Para detener nuevas ejecuciones, cambiá `WORKER_ENABLED=false` o deshabilitá
  el workflow. Eso no cancela un job que ya empezó: detenelo en Actions si hace
  falta, desactivá los envíos en la app y mantené las reservas existentes.
- La suspensión de Render no apaga este job: consulta Supabase y los proveedores
  directamente. Una pausa de Supabase, credenciales vencidas o cuotas agotadas
  sí impiden ejecutarlo. No se afirma que hubo búsqueda o entrega en ese caso.

Para producción con horario más previsible, usá un worker/cron de servidor o
[Cloud Run Jobs + Scheduler](../deploy/google-cloud/README.md), con sus costes
y requisitos correspondientes.

Referencias oficiales: [cron y rama predeterminada](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
[precios de GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions),
[secretos de Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions)
y [concurrencia](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
