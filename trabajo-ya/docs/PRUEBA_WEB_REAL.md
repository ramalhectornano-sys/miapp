# Prueba real de Internet: chofer, Rincón de los Sauces, 100 km

## Estado actual: claves aceptadas, resultado parcial

El segundo intento de [la ejecución 38744160735](https://github.com/ramalhectornano-sys/miapp/actions/runs/38744160735/attempts/2)
consultó realmente Tavily el 15/10/2026 entre 13:55:30 y 13:55:52 UTC:
**8 consultas HTTP 200, 8 créditos informados, 3 respuestas Groq y 2 GeoRef**.
El centro oficial fue Rincón de los Sauces, Neuquén (ID 58091040).
Hay [JSON completo](evidence/web-real-38744160735-attempt2.json) y
[resumen con enlaces y recibos](evidence/web-real-38744160735-attempt2.md).

El estado es **partial**: no se acreditó una vacante vigente con enlace y
ubicación verificados dentro de 100 km. El lector encontró páginas restringidas,
HTTP 403, robots que deniegan acceso y demoras de rastreo superiores al presupuesto.
El código también gastó lecturas en perfiles personales y enlaces restringidos;
el parche del backend 0.5.1 corrige selección y presupuesto y debe comprobarse
con una nueva ejecución. Esto no autoriza correos y no significa que no existan
empleos en la zona. Las credenciales ya no son el bloqueo de esta prueba.

## Resultado comprobado de la primera ejecución

[GitHub Actions 38744160735](https://github.com/ramalhectornano-sys/miapp/actions/runs/38744160735)
ejecutó el comando real sobre el commit `d008ba39b4a119c833230aaeaffb894591204810`.
Se detuvo en `preflight_failed`: faltaban `WEB_SEARCH_API_KEY` y `AI_API_KEY`
en los secretos de Actions. El informe registra **0 intentos HTTP Tavily**, **0
respuestas Tavily/Groq/GeoRef** y `test_passed=false`. Esto no significa que no
existan empleos: no se pudo ejecutar la búsqueda. **No hay enlaces de ofertas
reales acreditados por esta prueba.**

El informe JSON y Markdown se adjuntó como artefacto
`prueba-web-real-rincon-100km-38744160735` (30 días). El
[comprobante resumido](evidence/web-real-preflight-38744160735.json) conserva la
salida del comando y la referencia verificable. Cargar las claves únicamente en
los secretos y ejecutar nuevamente el workflow indicado debajo; no hace falta
volver a crear Supabase, Gmail ni las claves que ya existen en Render.


La prueba consulta Tavily y analiza con Groq sin acceder a usuarios, currículums,
base de datos ni Gmail. El escenario es **Chofer — Rincón de los Sauces, Neuquén,
Argentina — 100 kilómetros**. Las coordenadas se obtienen de GeoRef y las
distancias son aéreas entre centroides de localidades; no son distancias por ruta.

## Configuración de claves para otra instalación

Render y GitHub no comparten secretos automáticamente. El propietario ya cargó
las dos claves en Actions y el segundo intento verificó su funcionamiento.
Para una instalación nueva, GitHub no puede leerlas desde Render. Sin estas dos claves en Actions, la prueba termina en
`preflight_failed`, con `actual_tavily_calls: 0` y `provider_consulted: false`.
Eso demuestra que falta configuración; no es una búsqueda exitosa sin resultados.

Desde el celular, en GitHub:

1. Abrí [miapp → Settings → Secrets and variables → Actions](https://github.com/ramalhectornano-sys/miapp/settings/secrets/actions).
2. Tocá **New repository secret**. Guardá tu clave de Tavily con el nombre exacto
   `WEB_SEARCH_API_KEY`. Copiala de tu panel de Tavily o del entorno privado de
   Render; no la pegues en el chat, un archivo, una issue ni el código.
3. Creá otro secreto, `AI_API_KEY`, con tu clave de Groq. No hacen falta claves
   de Supabase, Google, Gmail ni la clave de cifrado para esta prueba.
4. Abrí [Actions → Prueba REAL de búsqueda web — Tavily y Groq](https://github.com/ramalhectornano-sys/miapp/actions/workflows/trabajo-ya-web-real-test.yml).
   Tocá **Run workflow**, elegí la rama `main` o `trabajo-ya-real`, mantené `8`
   consultas y ejecutá. En una publicación push se fija al commit de esa ejecución; en una ejecución
   manual usa `trabajo-ya-real`. El resumen de la ejecución muestra el informe
   sin necesidad de extraer el ZIP.
5. Abrí la ejecución. En **Artifacts**, descargá
   `prueba-web-real-rincon-100km-<número>-intento-<intento>`. Contiene un JSON y un
   resumen Markdown con enlaces, horas, consultas, errores y comprobantes.

La primera publicación del workflow también intenta la prueba. Si los secretos
todavía no existen, fallará de forma explícita y se podrá repetir después de
guardarlos. No los envíes a Codex para subsanar el error.

## Qué demuestra el informe

- `actual_tavily_calls`: intentos HTTP. Un intento con error DNS no demuestra que
  Tavily haya recibido nada.
- `provider_consulted` y `tavily_response_count`: hubo una respuesta HTTP del
  endpoint real de Tavily. Una respuesta 401 confirma contacto pero no una
  búsqueda exitosa.
- `audit_events`: cada consulta, tipo, hora de inicio y fin, HTTP, estado,
  enlaces y dominios devueltos. Guarda `request_id` y créditos solo cuando Tavily
  los informa; nunca los inventa.
- `http_events`: fechas y estados HTTP de Tavily, Groq y GeoRef. Las lecturas
  de páginas públicas se comprueban mediante los eventos `public_page` de `audit_events`.
  No contiene headers, claves, cuerpos de solicitudes, prompts ni CV.
- `results`: ofertas sustentadas por evidencia; conserva por separado el estado
  del enlace, ubicación, distancia, vigencia y forma de postulación disponible.
- `discoveries`: enlaces descubiertos que siguen pendientes de revisión; no son
  vacantes verificadas por el mero hecho de aparecer en Tavily.
- `test_passed` solo se activa si hay comprobantes de los tres proveedores,
  termina el flujo sin fallas y existe por lo menos una oferta con enlace original
  y ubicación verificados dentro del radio. Si no hay una oferta demostrable,
  informa `no_verified_opportunities`; no inventa una para que pase la prueba.

Una prueba automática con HTTP simulado en `backend/tests/test_check_web_research.py`
comprueba este contrato, pero **no es prueba de una consulta real a Tavily**.
La evidencia real es el artefacto de una ejecución con respuestas de los servicios.

## Presupuesto y costos

El valor predeterminado permite hasta **8 consultas Tavily basic**, con un máximo
absoluto de 12 por ejecución, y hasta 6 páginas públicas. No reintenta consultas
automáticamente. Tavily basic consume créditos reales de la cuenta; consultá el
cupo y los precios vigentes en [Tavily](https://docs.tavily.com/documentation/api-credits).
Groq consume el cupo del modelo configurado. El workflow no activa facturación ni
crea recursos de pago. GitHub Actions también está sujeto a los límites del plan
y la visibilidad del repositorio. Ejecutar el test repetidamente consume cupos.

Esta prueba puntual no activa el programador periódico. La operación diaria
requiere un worker configurado en el servidor o en el programador documentado
en [WORKER_GITHUB.md](WORKER_GITHUB.md), con secretos propios y controles de cuota.
Un servicio web gratuito de Render que se duerme no sustituye un worker periódico.

## Ejecución local o dentro del backend

Cargá las claves como variables privadas del entorno, sin pasarlas por argumentos
ni escribirlas en archivos públicos. Configuración no secreta necesaria:

```text
WEB_SEARCH_PROVIDER=tavily
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://api.groq.com/openai/v1
AI_MODEL=openai/gpt-oss-20b
```

Desde `backend/`:

```sh
python -m app.check_web_research --output /tmp/trabajo-ya-web-real.json
```

Se escriben `/tmp/trabajo-ya-web-real.json` y `/tmp/trabajo-ya-web-real.md`. No se
imprime la configuración privada. El comando sale con código 1 cuando falta
configuración, falla un proveedor o no puede demostrar la oportunidad solicitada.
Eso no permite concluir que no existan vacantes: hay que leer el estado y los
errores del informe. Ninguna ejecución de este comando envía correos.
