# Búsqueda de vacantes en Internet

Trabajo YA puede consultar un buscador web mediante Tavily y pasar los resultados
a la IA configurada en el servidor. Busca por los puestos y ciudades guardados,
extrae anuncios con citas comprobables y conserva su URL y fecha de consulta.
La fuente JSON anterior sigue disponible para integraciones verificadas.

Esta integración necesita una clave privada de Tavily en el servidor. Crear una
cuenta usando GitHub inicia sesión en Tavily; no conecta el repositorio ni Render.
La clave se carga entre paneles privados, nunca en código, APK o este documento.

## Activación en Render

En el servicio existente **trabajo-ya-api → Environment** configurar:

| Nombre | Valor |
| --- | --- |
| `WEB_SEARCH_PROVIDER` | `tavily` |
| `WEB_SEARCH_API_KEY` | Clave privada de tu cuenta Tavily. |
| `WEB_SEARCH_MAX_QUERIES` | `2` para las pruebas; máximo permitido `6`. |

Conservar Supabase, Groq y Google tal como están configurados. Elegir
**Save, rebuild, and deploy** o **Manual Deploy → Deploy latest commit** y esperar
**Live**. El backend de esta actualización identifica su versión como **0.4.0**
en `https://trabajo-ya-api.onrender.com/health`. Un estado
`web_search: configured_unverified` confirma configuración, no una consulta.

En Android, guardar una búsqueda con puesto y ciudad, abrir **Búsquedas → Ejecutar
ahora** y consultar **Ver ofertas encontradas** y **Ver ejecuciones**. El servidor
debe registrar una consulta completada o un error concreto. Si no encuentra
anuncios con evidencia suficiente, puede devolver cero coincidencias; un fallo
del proveedor nunca se convierte en una búsqueda vacía exitosa.

## Qué hace la IA

Se envía a Tavily únicamente el puesto y la ciudad, sin el CV, DNI, foto o tokens
del usuario. La IA recibe fragmentos de resultados, no permisos de envío. Debe
citar empresa, puesto, ciudad y contratación explícita; valores inventados,
anuncios cerrados, fechas vencidas y enlaces sustituidos se descartan. La ciudad
no se deduce de la consulta si no figura en el anuncio. Los enlaces se abren
solo al tocar **Ver oferta**. Esta ruta no visita automáticamente los portales.

Las consultas y los resultados están acotados. Con listas extensas de puestos
y ciudades, una ejecución puede cubrir solo parte de las combinaciones y lo
informa en su resultado. El buscador ofrece cobertura de Internet, sin prometer
consultar todos los portales ni encontrar toda vacante existente.

## Correos y revisión

Un resultado web es un hallazgo para revisar: no verifica que el correo exista,
que pertenezca a la empresa, que la oferta siga abierta o que admita envíos
automáticos. Conserva `recipient_verified=false` y no habilita consentimiento
automático. Se puede abrir el anuncio original y seguir su proceso de postulación.
Las postulaciones por correo del sistema siguen requiriendo una integración que
verifique destinatario y vigencia, Gmail vinculado y autorización específica.
Se conservan el máximo global de 10 intentos diarios y las 72 horas entre
recordatorios autorizados; ningún envío se confirma sin comprobante de Gmail.

## Ejecución con el teléfono apagado

El botón Ejecutar ahora no inicia un programador permanente. Para pruebas está
preparado el [worker con GitHub Actions](WORKER_GITHUB.md), apagado por defecto,
sin garantía de puntualidad. Usa la misma base y secretos del servidor y ejecuta
una búsqueda pendiente por lote. Para producción está la ruta de
[Cloud Run Jobs y Scheduler](../deploy/google-cloud/README.md), con facturación
y posibles cargos. Render Free no incluye el worker continuo de esta app.

Tavily ofrece actualmente 1.000 créditos gratuitos mensuales sin tarjeta.
Una consulta básica consume un crédito; el cupo se comparte entre todos los
usuarios del servidor. No se activa PAYGO desde el código. Al agotarse el cupo,
se registra un error hasta que el proveedor vuelva a permitir consultas.
La clave y las condiciones del servicio se administran en tu cuenta Tavily.

Fuentes: [API oficial](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[créditos y precios](https://docs.tavily.com/documentation/api-credits),
[condiciones](https://www.tavily.com/terms).
