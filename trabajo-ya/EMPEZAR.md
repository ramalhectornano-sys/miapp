# Trabajo YA: actualizar y comprobar la versión 0.5.0

El Supabase y backend existentes se conservan. Android utiliza https://trabajo-ya-api.onrender.com; el usuario ya mostró CV seleccionado y confirmó Gmail vinculado. No hace falta recrear servicios ni claves.

El código **0.5.0 / Android 9** añade búsqueda general, geografía de Argentina, radio e historial de consultas. La compilación y descarga deben comprobarse en [APK_REAL](docs/APK_REAL.md); este documento no acredita por sí solo una nueva publicación. La APK anterior 0.4.1 no contiene estas pantallas geográficas.

**Todavía no se acreditó una búsqueda real Tavily/Groq, una oferta de chofer a 100 km ni una entrega Gmail.** Las pruebas del código usan respuestas simuladas. Las claves están solo en Render; Actions no puede leerlas desde allí.

## 1. Actualizar Supabase sin borrar datos

En [Supabase](https://supabase.com/dashboard) → SQL Editor, si ya están las migraciones 001–006, aplicar solamente [202610140007_web_research_and_locations.sql](supabase/migrations/202610140007_web_research_and_locations.sql). Añade ubicación/radio e historial privado. No repetir 007 si ya está aplicada ni ejecutar otra vez install-new-project.sql. Con CLI, supabase db push aplica pendientes en orden. Ver [Supabase](supabase/README.md).

Si ya podés entrar, no cambies plantillas ni autenticación. Para otra instalación, el callback exacto es **autoempleoia://auth/callback** y el acceso usa PKCE. Ver [AUTH_SETUP](docs/AUTH_SETUP.md).

## 2. Actualizar Render

En **Render → trabajo-ya-api → Environment**, conservar los secretos actuales. Revisar esta configuración pública:

~~~text
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_MAX_QUERIES=6
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://api.groq.com/openai/v1
AI_MODEL=openai/gpt-oss-20b
GEOCODER_PROVIDER=georef_ar
PUBLIC_PAGE_READS_ENABLED=true
PUBLIC_PAGE_MAX_READS=6
~~~

El Blueprint anterior podía dejar WEB_SEARCH_MAX_QUERIES=2. **Cambiarlo a 6 explícitamente: Manual Deploy no actualiza esa variable existente.** WEB_SEARCH_API_KEY y AI_API_KEY siguen como secretos privados de Render; no ponerlos en el código ni chat.

Mantener **MAIL_SEND_ENABLED=false** hasta una prueba controlada. Desplegar la rama **trabajo-ya-real** con **Manual Deploy → Deploy latest commit**, esperar Live y comprobar versión **0.5.0** en /health. Un estado configured_unverified no demuestra consultas ni correo. Ver [BUSQUEDA_WEB](docs/BUSQUEDA_WEB.md).

## 3. Preparar la prueba real desde el celular

1. Abrir [miapp → Settings → Secrets and variables → Actions](https://github.com/ramalhectornano-sys/miapp/settings/secrets/actions).
2. En **New repository secret**, guardar la clave Tavily como **WEB_SEARCH_API_KEY**.
3. Guardar la clave Groq como **AI_API_KEY**. Copiar entre paneles privados; no publicarlas ni enviarlas por chat. No hace falta Supabase ni Gmail para esta prueba.
4. Abrir [Actions → Prueba REAL de búsqueda web — Tavily y Groq](https://github.com/ramalhectornano-sys/miapp/actions/workflows/trabajo-ya-web-real-test.yml) → **Run workflow**. Mantener 8 consultas para **Chofer, Rincón de los Sauces, Neuquén, Argentina, 100 km**.
5. Descargar el artefacto prueba-web-real-rincon-100km-<número>. El JSON y Markdown contienen consultas, horas, HTTP, enlaces y recibos cuando el proveedor los informa.

Si faltan claves: preflight_failed y cero llamadas. Un error no se transforma en «cero vacantes» exitoso. Si no se demuestra una oportunidad con enlace y ubicación dentro del radio, la prueba no se marca terminada. Ver [PRUEBA_WEB_REAL](docs/PRUEBA_WEB_REAL.md).

## 4. Instalar Android y buscar

Descargar la APK nueva solo cuando el enlace y la compilación estén confirmados en [APK_REAL](docs/APK_REAL.md). Instalar como actualización con la misma firma. No desinstalar ni borrar datos como paso rutinario.

En Búsquedas o la propuesta del chat, indicar Argentina, Neuquén, Rincón de los Sauces; tocar **Comprobar ubicación**, elegir la coincidencia y seleccionar **100 km**. Guardar, usar **Ejecutar ahora** y revisar **Ver ofertas encontradas**, **Consultas web** e historial de ejecuciones.

La búsqueda es general: LinkedIn y Computrabajo son adicionales para descubrimiento y revisión; su lectura automática está restringida. También se investigan páginas públicas permitidas de empresas, consultoras y bolsas. No se promete cobertura completa. El radio es aéreo aproximado entre localidades, no kilómetros por ruta. Países distintos de Argentina requieren otro geocodificador.

## 5. Ejecutar con el teléfono apagado

Guardar un horario y desplegar la API no activa un programador. Render Free puede dormir y no aporta el worker continuo de esta app. Seguir [WORKER_GITHUB](docs/WORKER_GITHUB.md): workflow en la rama principal, secretos/variables propios y WORKER_ENABLED apagado por defecto. Intenta ejecutar cada 15 minutos, con posibles demoras; comprobar una ejecución registrada.

Para operación supervisada están [Cloud Run Jobs/Scheduler](deploy/google-cloud/README.md) o [servidor propio](deploy/README.md), con posibles cargos. No hace falta abrir Google Cloud para probar el camino GitHub. Tavily/Groq consumen cupos reales. No se activa un servicio pago desde esta actualización.

## 6. Autorizar correo después de comprobarlo

Gmail conectado y horario guardado no autorizan envíos. Elegir CV, cuenta, fuente verificadora y vencimiento, y aceptar consentimiento. Los hallazgos web generales no verifican destinatarios. Greenhouse solo admite correo cuando una oferta vigente publica ese canal para recibir CV y se vuelve a comprobar antes de enviar. Formularios, páginas restringidas y correos sin verificar quedan para intervención humana.

Se mantienen **10 intentos diarios por usuario**, sumados entre búsquedas, y **72 horas** entre recordatorios autorizados. Habilitar MAIL_SEND_ENABLED y el worker solo después de la comprobación controlada de [ACTIVAR_CORREOS](docs/ACTIVAR_CORREOS.md). Una postulación aparece enviada únicamente con confirmación del proveedor.

La consulta, ejecución periódica y entrega reales siguen pendientes de comprobación. No recrear Supabase, Gmail ni sus claves válidas.
