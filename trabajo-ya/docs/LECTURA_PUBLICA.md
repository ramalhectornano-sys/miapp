# Lectura de páginas públicas

El descubrimiento continúa siendo una búsqueda general con Tavily. La lectura
de páginas agrega evidencia del enlace original; no restringe el buscador a
una lista de portales ni convierte una empresa o un destinatario en verificado
para enviar correo.

`backend/app/services/public_pages.py` ofrece este contrato:

```python
enriched_results, failures = await investigate_pages(
    settings, provider_client, results, search, audit=record_event,
)
```

Conserva el extracto y la procedencia de Tavily. Cuando puede leer una página,
agrega `raw_content` y `page_verification`: hora UTC de comprobación, estado,
URL final, estado HTTP y SHA-256 del contenido realmente recibido. Extrae texto
público, requisitos, fechas que el editor declare, enlaces de postulación y
datos estructurados `JobPosting`, cuando existan. No inventa fechas, vacantes,
ubicaciones ni correos. Un enlace accesible no demuestra que una vacante siga
abierta ni que el empleador sea legítimo.

Los estados son:

- `verified_link`: se pudo leer el enlace y conservar evidencia del contenido.
- `pending_review`: lectura bloqueada, límite alcanzado, formato no soportado,
  acceso humano requerido o comprobación incompleta.
- `unavailable`: el editor respondió 404 o 410.
- `closed`: el contenido indica cierre o vencimiento explícito.

Una página de empresa sin una oferta no se transforma en una vacante.
`job_posting` se incluye solo si hay un único anuncio estructurado; una lista
de anuncios queda en `job_postings` y debe analizarse sin mezclar sus datos.

## Límites y acceso

- Hasta seis páginas por investigación, incluidos como máximo dos enlaces
  laborales adicionales del mismo hostname y de un solo salto. Si se agotó el
  presupuesto, el resto queda pendiente. No hay rastreo recursivo.
- Se permiten dos redirecciones por página, con robots y DNS comprobados para
  el destino. `allowed_links` conserva candidatos observados literalmente en
  la página; antes de seguirlos todavía se comprueban robots y DNS.
- Se exige HTTPS público, puerto 443, sin credenciales, fragmentos ni parámetros
  privados conocidos. Cada conexión resuelve DNS y fija una IP pública; se
  rechazan respuestas privadas o mixtas, multicast y direcciones de transición.
  TLS sigue validando el hostname original. Los pools se separan por hostname.
- Antes de leer se consulta `robots.txt`. Si no se puede comprobar o prohíbe
  la ruta, queda pendiente. Se respeta un `crawl-delay` de hasta cinco segundos;
  uno mayor queda pendiente para no exceder el presupuesto de ejecución.
  Robots es una restricción técnica, no una licencia ni una autorización para
  reutilizar datos, automatizar postulaciones o ignorar las condiciones del sitio.
- No se leen directamente LinkedIn ni Computrabajo. Pueden descubrirse mediante
  Tavily y abrirse por decisión del usuario para revisión manual.
- Solo hay solicitudes GET. No se ejecutan scripts, no se completan formularios,
  no se inicia sesión y no se eluden CAPTCHA, 403, 429 o pagos.
- Cada solicitud tiene un límite total de quince segundos, además de los
  límites de conexión/lectura. HTML máximo: 1 MiB; robots: 512 KiB; texto para
  análisis: 20.000 caracteres. Se omiten scripts, formularios y texto oculto.
- El lector usa un cliente separado sin tokens de Tavily/Groq, Authorization,
  API keys ni cookies. Si hay un proxy de salida que impide fijar DNS con esta
  protección, no se lo evita: la publicación queda pendiente de revisión.

La configuración del servidor admite `PUBLIC_PAGE_READS_ENABLED=true`
(predeterminado) para habilitar la lectura y `PUBLIC_PAGE_READS_ENABLED=false`
para conservar los descubrimientos pendientes sin solicitar esas páginas.
`PUBLIC_PAGE_MAX_READS=6` es el presupuesto predeterminado; admite de uno a seis
y nunca eleva el límite de seis. Se traducen a los atributos internos
`settings.public_page_reads_enabled` y `settings.public_page_max_reads`.

## Historial y correo

El callback `audit(event)` puede ser asíncrono. Cada solicitud real registra
`kind=public_page`, `provider=publisher`, UUID `event_id`, operación
`robots_fetch` o `page_fetch`, URL, hora y estado `started` seguido de
`succeeded` o `failed` con el mismo UUID. Las decisiones que impiden una
solicitud se registran como `blocked`. No se registra el cuerpo de la página,
tokens ni mensajes de excepción privados.

Un correo publicado junto a la instrucción de enviar CV se conserva como
`published_email_pending_review`, siempre con `recipient_verified=False`.
Leer esa dirección no habilita envíos automáticos. Siguen siendo necesarios
la verificación independiente del destinatario, el consentimiento vigente,
las fuentes aptas y el servicio de correo habilitado. Este módulo no envía
correos ni acredita que una llamada a Tavily o Groq haya ocurrido.

## Validación

```bash
cd backend
python -m unittest tests.test_public_pages -v
```

Las pruebas usan `httpx.MockTransport`; verifican límites, un salto, robots,
redirecciones, DNS privado, IP fijada con Host/SNI, separación de pools TLS,
ausencia de cookies/credenciales/formularios, respuestas bloqueadas, vencimiento
y auditoría. No realizan una búsqueda real ni prueban un envío real. La prueba
de Tavily debe mostrar la solicitud efectiva y su identificador de proveedor
desde el entorno que tenga configurada la clave.
