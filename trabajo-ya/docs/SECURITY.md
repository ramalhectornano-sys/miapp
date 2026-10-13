# Seguridad y datos personales

La aplicación maneja CV, referencias y permisos de correo. Las decisiones de
envío pertenecen al usuario; el chat puede proponer acciones, pero su salida no
crea permisos ni evidencia de ejecución.

## Límites de acceso

- Android contiene solo URL y clave pública de Supabase. SecureStore protege la
  persistencia de la sesión; el backend valida cada access token con Supabase Auth.
- El registro y el acceso no piden contraseña: Supabase envía un código de un
  solo uso y verifica la propiedad del correo antes de devolver una sesión. La
  configuración local fija 6 dígitos, 10 minutos y solicitudes cada 60 segundos;
  las mismas opciones y plantillas requieren configuración en proyectos remotos.
  Nunca basta con escribir una dirección para acceder a los datos de esa cuenta.
- Todas las tablas de cuenta tienen RLS con `auth.uid()`. Las asociaciones entre
  búsqueda, CV, conexión, oferta y postulación incluyen `user_id` en claves
  foráneas, de modo que no admiten referencias cruzadas entre usuarios.
- Los privilegios del cliente no permiten alterar estados de envío, recibos,
  verificación de destinatarios ni resultados de extracción. Los mensajes del
  cliente solo pueden tener rol `user`; no puede fabricar respuestas del asistente.
- La clave `service_role` elude RLS y vive únicamente en el servidor. Los endpoints
  deben filtrar siempre por el usuario autenticado, además de las restricciones SQL.

## Documentos y extracción

Los buckets de CV y fotos son privados, con políticas de prefijo UUID y límites
de formato/tamaño. Cada CV tiene su propia ruta y versión. Compartir documentos
mediante URL firmada breve; no publicar objetos ni incluir URLs firmadas en logs.
El backend extrae texto de PDF/DOCX sin guardar experiencia inventada. Un PDF
escaneado puede no contener texto; debe informarse y no rellenarse con inferencias.

Configurar un proveedor externo de IA implica evaluar qué información se envía y
su política de tratamiento. Ollama permite mantener inferencia en infraestructura
propia. No introducir el CV completo en una API externa sin informar al usuario.

## Correo y consentimiento

Google OAuth usa estado de un solo uso, hash SHA-256, caducidad y PKCE. Tokens y
verificadores se cifran con Fernet antes de guardarse en tablas `private`. Mantener
la clave de cifrado fuera de la base y del bundle móvil; respaldarla de forma
segura y planificar rotación mediante `key_id`. No imprimir secretos, cuerpos de
correo ni CV en logs.

Conectar un correo no concede autorización para enviar. La aprobación manual
registra fecha y texto de una postulación concreta. El consentimiento automático
registra texto aceptado, política, vencimiento, búsqueda, CV, remitente, fuentes,
límite y opción de recordatorios. Permite ejecutar los envíos diarios sin otra
aprobación hasta un máximo de 90 días. Se puede revocar; la RPC invalida el permiso
y apaga `auto_apply`. Renovarlo reemplaza la autorización anterior. Los permisos
V2 solo autorizan envíos iniciales: los recordatorios cada 3 días necesitan
renovación explícita con política V3 y `repeat_enabled=true`.

El límite global de 10 intentos por usuario y día incluye envíos manuales,
automáticos y recordatorios de todas las búsquedas, así como fallos y resultados
inciertos. Usa la zona estable `profiles.sending_timezone`, inicialmente
`America/Argentina/Buenos_Aires`; cambiar la zona de una búsqueda no multiplica el
cupo. Una reserva SQL serializada por usuario impide superar el límite desde
workers concurrentes. Pausar la búsqueda impide nuevas reservas automáticas.

Antes de llamar al proveedor se reserva el envío atómicamente y se comprueba que
la fuente está autorizada, el destinatario coincide con el verificado, el CV y
correo son propios y los permisos siguen vigentes. La generación del mensaje usa
el borrador reservado, no una lectura anterior que podría haber cambiado.
Las vacantes que necesitan revisión humana quedan pendientes.

Un recordatorio requiere que hayan transcurrido 72 horas desde el último envío
confirmado a ese correo normalizado, considerando todas las búsquedas. La fuente
autorizada debe devolver la oferta vigente, verificada y todavía compatible en
la ejecución actual. No se usa un contacto histórico como evidencia suficiente.
Una respuesta registrada, un intento pendiente o incierto a ese correo, la
revocación o el vencimiento del permiso impiden nuevas reiteraciones automáticas.
Cada recordatorio conserva su propia fila, contenido, CV y recibo; no sobrescribe
el envío original.

El usuario también puede detener recordatorios a un destinatario desde una
postulación propia. El bloqueo se mantiene para ese correo entre todas sus
búsquedas; informar una respuesta es una acción manual y no acredita lectura
automática de la bandeja. Detenerlos impide reservas futuras, pero no deshace un
envío que ya haya sido reservado.

El estado `sent` exige identificador y fecha de confirmación del proveedor, fecha
de envío, destinatario verificado y reserva. La aceptación del proveedor no prueba
entrega ni lectura. Un resultado incierto no se reintenta automáticamente.
`responded` se puede registrar cuando el usuario informa una respuesta a una
postulación ya confirmada. Esta versión no consulta respuestas de bandeja ni
asigna ese estado automáticamente.

## Fuentes y datos no confiables

Solo configurar feeds HTTPS propios o autorizados y respaldar la verificación
de correo con evidencia contractual de la fuente. No añadir scraping que
incumpla condiciones de portales. El adaptador limita tamaño y filas y bloquea
redirecciones y destinos privados. El texto de una vacante o de un modelo es
contenido no confiable y no concede acceso a herramientas, consentimiento o tokens.

## Eliminación y operación

La eliminación de cuenta pasa por FastAPI: purga de objetos privados y eliminación
de Auth Admin con cascadas a datos y secretos. Ante un fallo no se debe confirmar
eliminación total. Los backups necesitan una política de retención y caducidad
separada; definirla antes de publicar junto con privacidad y contacto del responsable.

Desplegar con HTTPS, gestor de secretos, cuentas de servicio separadas, límites
de solicitudes por usuario, logs operativos restringidos, alertas de fallos del
worker y backup. Verificar OAuth de producción y declaración de datos en Google
Play antes de distribuir a usuarios reales.

## Verificación pendiente

Las pruebas backend son offline y no prueban disponibilidad ni permisos de
Supabase/Gmail reales. Consultar [VALIDATION](VALIDATION.md) para los controles
locales ejecutados. Antes de publicar, comprobar las migraciones contra Supabase,
dos sesiones reales, accesos a Storage, workers concurrentes, revocación de
permisos y envío a un destinatario de prueba expresamente autorizado. Las pruebas
locales no acreditan envíos reales ni una compilación Android.
