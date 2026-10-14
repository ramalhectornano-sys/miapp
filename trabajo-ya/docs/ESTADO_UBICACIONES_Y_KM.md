# Estado de búsqueda, ubicaciones y kilómetros

La arquitectura permite añadir los requisitos geográficos, pero la entrega
0.4.0 todavía no los implementa. La ciudad se guarda como texto y se compara
con la ciudad del anuncio. Escribir «100 km» en el chat no calcula ese radio.

| Requisito | Estado actual |
| --- | --- |
| Tavily y análisis de anuncios con IA | Implementados; la consulta real debe comprobarse con la cuenta configurada en Render. |
| Empresa, puesto, ciudad, enlace y fecha de consulta | Implementados en Ver ofertas encontradas. |
| Evidencia, duplicados e historial | Implementados y probados con transportes de prueba. |
| País, provincia, identificadores y coordenadas verificadas | Pendientes de implementación. |
| Ambigüedad de localidades y confirmación | Pendiente de implementación. |
| Radios, provincia completa y kilómetros personalizados | Pendientes de implementación. |
| Haversine y descarte de ofertas fuera del radio | Pendientes de implementación. |
| Distancia, requisitos estructurados y publicación visibles | Pendientes; el backend conserva algunas citas y fechas cuando están disponibles. |
| Gmail | El usuario confirmó la vinculación; no se confirmó una prueba de envío. |
| Tareas con el celular apagado | Worker preparado en GitHub, desactivado por defecto y pendiente de ejecución comprobada. |
| Enviar automáticamente a hallazgos web | Deshabilitado: Tavily no verifica vigencia ni destinatarios. |

Para completar la parte geográfica hacen falta un proveedor de geocodificación
configurable, identificadores y coordenadas persistentes, resolución de nombres
ambiguos, migraciones y controles de Android para país/provincia/radio.
Haversine proporciona distancia en línea recta entre coordenadas; la distancia
por carretera requiere otra integración y debe mostrarse con su tipo correcto.
Una ubicación que no se puede verificar debe quedar para revisión manual.

Las pruebas de código y compilación no acreditan consultas reales, escrituras
de resultados, ejecución del programador ni entrega de correo. Para probarlos
en el entorno del usuario hay que desplegar, ejecutar una búsqueda autenticada,
revisar su registro y enlaces, activar el worker y comprobar una ejecución,
y autorizar expresamente un destinatario de prueba antes de habilitar envíos.

Render Free no ejecuta el worker continuo. GitHub Actions sirve para pruebas
gratuitas con demoras posibles; un servicio de producción requiere revisar
disponibilidad y costos. Tavily tiene un cupo gratuito mensual compartido.
Geocodificación, IA, hosting, base de datos y servicios adicionales tienen sus
propias condiciones y cuotas. No se activa un plan pago desde estas instrucciones.
