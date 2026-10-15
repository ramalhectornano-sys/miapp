# Investigación laboral general en Internet — 0.5.0

El código consulta Tavily y usa Groq para analizar anuncios con evidencia. Las consultas generales combinan puesto, sinónimos acotados, localidad, provincia, país, empresas, consultoras, bolsas laborales y páginas de contratación. LinkedIn y ar.computrabajo.com son fuentes adicionales; no restringen la búsqueda a esos portales ni a Greenhouse.

**Estado real:** la implementación y las pruebas con proveedores simulados están preparadas. Todavía no se ejecutó ni acreditó la búsqueda solicitada de chofer en Rincón de los Sauces a 100 km. No hay enlaces de ofertas reales acreditadas para mostrar. Las claves están solamente en Render y el workflow de prueba no puede leerlas desde allí.

## Actualizar la instalación existente

No recrear Supabase, Gmail, el servicio Render ni claves válidas.

1. Si ya están instaladas las migraciones 001–006, aplicar solamente [202610140007_web_research_and_locations.sql](../supabase/migrations/202610140007_web_research_and_locations.sql) en Supabase → SQL Editor. No repetir 007 si ya está aplicada ni ejecutar otra vez el instalador inicial. Con CLI, supabase db push aplica las pendientes en orden.
2. En **Render → trabajo-ya-api → Environment**, conservar los secretos y revisar:

| Nombre | Valor |
| --- | --- |
| WEB_SEARCH_PROVIDER | tavily |
| WEB_SEARCH_API_KEY | Clave privada de Tavily, solo en el entorno. |
| WEB_SEARCH_MAX_QUERIES | **6** normalmente; entre 1 y 12. |
| AI_PROVIDER | openai_compatible |
| AI_BASE_URL | https://api.groq.com/openai/v1 |
| AI_MODEL | openai/gpt-oss-20b |
| AI_API_KEY | Clave privada de Groq, solo en el entorno. |
| GEOCODER_PROVIDER | georef_ar |
| PUBLIC_PAGE_READS_ENABLED | true |
| PUBLIC_PAGE_MAX_READS | 6; máximo 6. |

El Blueprint anterior configuraba WEB_SEARCH_MAX_QUERIES=2: **Manual Deploy por sí solo no cambia ese valor existente**. Cambiarlo explícitamente en Environment.

3. Desplegar la rama **trabajo-ya-real** mediante **Manual Deploy → Deploy latest commit** y esperar **Live**. Después, https://trabajo-ya-api.onrender.com/health debe informar versión **0.5.0**. El endpoint describe configuración; no demuestra consultas, inferencias ni envíos.
4. Instalar la APK 0.5.0 cuando su compilación y publicación estén confirmadas en [APK conectada](APK_REAL.md). Actualizar Android no despliega el servidor.
5. En la app, comprobar localidad/provincia/país, elegir la coincidencia correcta y el radio, guardar y usar **Búsquedas → Ejecutar ahora**. Revisar **Ver ofertas encontradas**, **Consultas web** y el historial de ejecuciones.

## Qué investiga y comprueba

El presupuesto normal es **6 consultas Tavily basic**, máximo absoluto **12**, y hasta **24 resultados** deduplicados e intercalados. Puede formular una consulta posterior acotada sobre un sitio observado. Las combinaciones omitidas y fallas se informan: no se promete cubrir todo Internet ni cada localidad del radio.

El lector visita hasta **6 páginas públicas**, incluyendo hasta dos enlaces de contratación del mismo editor. Comprueba destinos públicos, DNS, redirecciones y reglas de robots.txt. No atraviesa login, CAPTCHA ni redes privadas. La lectura automática de LinkedIn y Computrabajo está bloqueada; sus enlaces descubiertos mediante Tavily quedan para revisión humana. La lectura permitida no concede permiso para postularse ni para incumplir condiciones de terceros.

Groq analiza texto y datos del editor cuando se pudo leer; en otros casos solo hay fragmentos del buscador. Empresa, puesto, contratación, lugar, requisitos y fechas requieren citas. Se descartan anuncios cerrados/vencidos y datos sin evidencia. Las fechas ausentes no se inventan. Una página no comprobable conserva **pending_review**. No se envían CV, foto, DNI ni tokens OAuth a Tavily.

## Ubicación y radio

GeoRef verifica localidades, identificadores y centroides de **Argentina**. Otros países necesitan un proveedor adicional. La app exige elegir la localidad comprobada. Se admiten radios enteros de 0 a 1000 km; 0 significa la localidad elegida. Haversine calcula distancia aérea aproximada entre centroides, no kilómetros por ruta ni desde la dirección exacta del empleo.

El centro y la localidad publicada se verifican independientemente. Las ofertas confirmadas fuera del radio se excluyen. Ubicaciones ambiguas, país ausente en el anuncio o fallas geográficas quedan pendientes; no se heredan datos de la consulta para fingir cercanía. Un radio puede cruzar provincias. Ver [alcance geográfico](ESTADO_UBICACIONES_Y_KM.md).

## Historial y prueba real

La migración 007 añade web_research_events, con lectura privada por usuario y registros de servidor asociados a la ejecución reclamada. Conserva consultas, horas, proveedor, HTTP, fuentes, errores y recibos cuando existen. Una operación iniciada no demuestra una respuesta. No almacena claves, headers privados, prompts completos ni tokens.

La prueba independiente se ejecuta desde [Actions → Prueba REAL de búsqueda web — Tavily y Groq](https://github.com/ramalhectornano-sys/miapp/actions/workflows/trabajo-ya-web-real-test.yml). Antes, copiar las claves privadas a [miapp → Settings → Secrets and variables → Actions](https://github.com/ramalhectornano-sys/miapp/settings/secrets/actions) con los nombres exactos **WEB_SEARCH_API_KEY** y **AI_API_KEY**. No pegarlas en el chat ni código.

El escenario es Chofer/Rincón de los Sauces/Neuquén/Argentina/100 km, con 8 consultas por defecto. Genera JSON y Markdown con comprobantes y enlaces observados, sin acceder a Supabase ni Gmail. Si faltan claves, informa preflight_failed y cero llamadas. Si falla o no demuestra una oportunidad con enlace y ubicación, no declara la prueba terminada. Ver [PRUEBA_WEB_REAL](PRUEBA_WEB_REAL.md).

## Correo y funcionamiento con el celular apagado

Descubrir o leer un anuncio no verifica un destinatario. Los hallazgos web generales siguen para revisión. La integración independiente de Greenhouse exige anuncio vigente, canal explícito para recibir CV y comprobación antes de enviar. Los feeds autorizados conservan su contrato. Siempre se requiere Gmail vinculado, CV y consentimiento específico vigente.

**MAIL_SEND_ENABLED permanece false hasta una prueba controlada.** No activarlo para ocultar un aviso. Se mantienen 10 intentos globales por usuario/día y 72 horas entre recordatorios autorizados. Ningún correo figura enviado sin confirmación del proveedor. Ver [ACTIVAR_CORREOS](ACTIVAR_CORREOS.md).

Ejecutar ahora no activa un programador. Render Free puede dormir y no incluye el worker continuo de esta app. El [worker GitHub Actions](WORKER_GITHUB.md) está preparado y apagado por defecto, requiere secretos/variables propios e intenta ejecutar cada 15 minutos, con posibles demoras. Para disponibilidad supervisada están [Cloud Run Jobs/Scheduler](../deploy/google-cloud/README.md) o [servidor propio](../deploy/README.md), con posibles costos. El teléfono puede estar apagado cuando worker y programador operan; su activación real todavía debe comprobarse.

## Cupos

Tavily basic consume créditos reales y el cupo se comparte entre usuarios. Seis consultas diarias consumen hasta 180 créditos en 30 días por búsqueda, sin contar pruebas. Groq, GeoRef, GitHub Actions, Supabase y hosting tienen límites propios. El código no activa PAYGO ni crea servicios pagos. Revisar precios antes de ampliar frecuencia o usuarios.

Fuentes: [Tavily API](https://docs.tavily.com/documentation/api-reference/endpoint/search), [créditos](https://docs.tavily.com/documentation/api-credits), [condiciones](https://www.tavily.com/terms), [GeoRef](https://www.argentina.gob.ar/georef).

## Primera comprobación ejecutada

[Actions 38744160735](https://github.com/ramalhectornano-sys/miapp/actions/runs/38744160735)
falló en preflight por los dos secretos de proveedor ausentes. Registró cero
llamadas Tavily y cero respuestas de los proveedores. No acredita ofertas reales.
El [informe y los pasos para repetirla](PRUEBA_WEB_REAL.md) distinguen esta prueba
bloqueada de la suite de código aprobada (403 backend y 52 móviles).
