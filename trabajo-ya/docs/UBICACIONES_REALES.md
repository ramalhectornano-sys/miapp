# Ubicaciones y radio verificado

Trabajo YA usa la API pública oficial **Servicio Georef – argentina.gob.ar/georef** para confirmar localidades de Argentina. Consulta `https://apis.datos.gob.ar/georef/api/v2.0/localidades` y guarda ID, localidad, provincia, país, centroide, URL de la consulta y hora de obtención. No acepta coordenadas inventadas por la IA ni suministradas por el teléfono para confirmar la búsqueda.

`GEOCODER_PROVIDER=georef_ar` habilita este proveedor. No necesita cuenta ni clave. La implementación actual cubre **Argentina**; para otros países hace falta integrar un proveedor geográfico autorizado. Un país desconocido, un error del proveedor o una localidad homónima quedan sin confirmar: no se calcula una distancia ficticia. Al guardar una búsqueda con homónimos, la aplicación debe pedir que el usuario elija uno de los IDs oficiales candidatos.

El radio se calcula con Haversine sobre los **centroides de las localidades**. Se muestra como distancia aérea aproximada, sin estimar kilómetros por carretera ni afirmar la dirección exacta del puesto. Un radio de 0 significa la localidad confirmada, identificada por su ID. La comparación con el límite usa la distancia sin redondear; el valor mostrado se redondea a tres decimales.

Para formular consultas cercanas, el servidor obtiene el catálogo de localidades argentinas y selecciona las que quedan dentro del radio, incluyendo otras provincias. El catálogo se pagina con hasta 5000 registros por página y hasta tres páginas. Se conservan las 50 localidades más cercanas para planificar consultas. Si el catálogo, la paginación o este límite impiden cubrir todo el radio, el resultado incluye una advertencia: no se afirma que todas las empresas o ciudades fueron investigadas. Las ofertas con una localidad distinta pueden comprobarse igualmente y quedan fuera del radio si corresponde.

La ubicación de cada oferta se toma **de su publicación**, con país y provincia cuando consten. Nunca se heredan el país, la provincia ni la ciudad de la consulta para inventar dónde está el empleo. El proveedor confirma la existencia del lugar, mientras la comprobación del enlace y de las citas de la oferta determina si ese lugar corresponde al trabajo. Si falta el país, hay homónimos o no se confirma el centro, `within_radius` y/o la distancia quedan pendientes. Las postulaciones automáticas deben requerir `within_radius=true` y la verificación independiente del destinatario y de la oferta.

La caché dura 24 horas y conserva la hora original de obtención, no la cambia a una consulta nueva. Hay hasta ocho consultas geográficas por ejecución y controles por proceso para respetar las cuotas públicas: 10 consultas por segundo, 40 por minuto, 2000 por hora y 10000 por día. Si se despliegan varios servidores, hace falta una cuota compartida para controlar el consumo total entre ellos. Los errores de red y las cuotas agotadas se registran como problemas de verificación, nunca como prueba de cero vacantes.

Georef es gratuito y exige atribución. Sus datos se publican con licencia CC BY 4.0. La función añade dicha atribución a las ubicaciones devueltas y la interfaz debe mostrar o enlazar la fuente.

Fuentes oficiales revisadas:

- [Ejemplos y endpoint vigente](https://www.argentina.gob.ar/georef/ejemplos-de-uso).
- [Parámetros de consulta y paginación](https://www.argentina.gob.ar/georef/parametros-generales).
- [Cuotas, licencia y atribución](https://www.argentina.gob.ar/georef/condiciones-de-uso-y-licencia).
- [Cobertura y acceso gratuito](https://www.argentina.gob.ar/georef/preguntas-frecuentes).

Las pruebas unitarias usan fixtures sintéticas y prueban homónimos, límites de distancia, cruces de provincia, cuotas y errores. **No sustituyen la consulta real a Georef ni prueban una búsqueda real de Tavily**; esa evidencia debe registrarse por separado desde una ejecución auténtica del servidor.
