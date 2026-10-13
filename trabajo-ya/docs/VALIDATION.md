# Validación de Trabajo YA 0.3.0

La imagen `images/maqueta-trabajo-ya.png` es una maqueta generada; `preview.html`
es una representación navegable del diseño. No son capturas de una ejecución
Android. El logo original proporcionado se conserva sin cambios en
`mobile/assets/brand/trabajo-ya-logo.jpg`; el PNG del icono es una adaptación.

## Comprobaciones ejecutadas

- **135 pruebas Python del backend aprobadas**, además de compileall.
- **29 pruebas del despliegue Google Cloud aprobadas**, con gcloud simulado:
  secretos ocultos, versiones compartidas, fuentes verificadas, activación
  expresa, pausa al actualizar y exclusión de archivos privados de la subida.
- Instalador SQL único generado y comprobado con `--check`: cinco migraciones
  intactas, hashes, orden y guard transaccional para proyecto nuevo. Sus nueve
  pruebas offline revisan el archivo/generador; no ejecutan PostgreSQL.
- **18 pruebas de lógica del móvil aprobadas**: 4 de demostración, 5 de acceso
  por código, 5 de preferencias de tema y 4 de estado de permisos automáticos.
- Sintaxis TypeScript/JSX de 24 archivos, imports locales, archivos JSON,
  configuración TOML, plantillas OTP, referencias de iconos y JavaScript de la
  vista HTML revisados.
- Sintaxis JavaScript de los dos ejecutores de pruebas SQL revisada.
- Configuración EAS, guard de compilación real y script Android revisados;
  una compilación sin variables reales se rechaza en la comprobación previa.
- applicationId y callback Google contrastados con el código. El helper de
  huellas se probó con un certificado público temporal de keytool, eliminado
  después; no se generó ni configuró el certificado de la APK de prueba.
- Docker Compose validado estáticamente con PyYAML y el parser de Compose,
  usando exclusivamente el archivo de ejemplo; no se ejecutaron contenedores.
- Archivo ZIP final comprobado íntegro y con logo, icono, migraciones y plantillas.

Las pruebas del servidor cubren tareas diarias con usuarios, cuentas de correo y
CV distintos. Verifican el máximo global de 10 reservas entre búsquedas y envíos
manuales, la espera de 72 horas, la autorización adicional para recordatorios,
la actualización de la oferta antes de reiterar y la detención por destinatario.
También comprueban la prioridad de vacantes nuevas dentro de cada ejecución,
la conservación del historial y CV anteriores, las reservas inciertas, la pérdida
de una tarea reservada, los permisos vencidos o revocados y el borrado seguro del
CV ante referencias concurrentes o una limpieza incompleta.
El proveedor de correo, las consultas y las RPC de esas pruebas son dobles de
prueba: validan el comportamiento Python, pero no ejecutan las transacciones SQL.
No se contactó Gmail ni se enviaron mensajes reales.

Las 14 pruebas adicionales de configuración comprueban que ejemplos, claves
privadas en variables públicas, dominios/callback incoherentes y configuración
incompleta se rechacen sin imprimir valores. El preflight no hace solicitudes
de red y siempre informa `services_verified: false`.

Las pruebas nuevas del worker comprueban el código de salida de `--once` cuando
una tarea falla o no se confirma, conservando las reservas de envío. Las de
Supabase comprueban claves modernas `sb_secret_`/`sb_publishable_` en `apikey`
y JWT de usuario separado para RLS, además de claves JWT antiguas, Storage y
eliminación de cuenta. Utilizan MockTransport: no prueban un proyecto remoto.

Las 20 pruebas nuevas de IA y su CLI comprueban JSON, datos sintéticos, modo real,
límite de generación, parámetros Groq GPT-OSS, claves ausentes o rechazadas,
cuotas, respuestas incompletas y ausencia de datos privados en errores. Usan
MockTransport, no Groq real. Las pruebas del despliegue verifican que el job de
IA use la revisión activa, su imagen y versión del secreto, sin heredar variables
de Gmail/Supabase ni dar por verificada una respuesta fallida.

El comando `setup` se comprobó con gcloud simulado: una comprobación de acceso
fallida impide crear recursos, el proceso conserva secretos previos y no activa
correo ni Scheduler. Las variables Android generadas contienen solo datos públicos
y no sobrescriben archivos locales del usuario. En este entorno el comando real
se detiene porque gcloud no está instalado; no se crearon recursos cloud.

## Estado de la puesta en marcha

El propietario ya creó el cliente OAuth de tipo Aplicación web en Google Cloud
y desea una opción económica de pruebas manejable desde el celular. No se
confirmó todavía un proyecto Supabase ni una cuenta de facturación habilitada
para el despliegue. El entorno no tiene secretos,
identidades, proyecto remoto ni fuente autorizada de vacantes configurados.
`deploy/google-cloud` prepara API Cloud Run, worker Job y Scheduler cada 15 minutos,
con secretos en Secret Manager. Ofrece HTTPS `run.app` sin comprar dominio para
pruebas; usa cuotas gratuitas, con facturación y posibles cargos. `deploy/compose.yaml`
conserva la alternativa de VPS con Ollama. Ninguna alternativa está desplegada.
No se creó ningún usuario real, conexión Gmail ni tarea remota. Faltan los accesos
del proyecto, la configuración de Supabase, vacantes autorizadas y correo de acceso.
Las instrucciones móviles están en `deploy/google-cloud/README.md`; Android en
`docs/ANDROID_BUILD.md`. Para IA real se preparó `activate-ai` con Groq
`openai/gpt-oss-20b` y `test-ai`. El entorno todavía no tiene clave del proveedor,
por lo que no se confirmó una inferencia externa. `docs/IA_REAL.md` contiene los
pasos para crear/cargar esa clave y comprobar una respuesta real.

## Comprobaciones pendientes

La instalación de paquetes npm no pudo completarse en este entorno por el
acceso de red; la comprobación del registro devuelve EPERM y la caché está vacía.
El acceso al socket de Docker también devuelve EPERM. No se ejecutaron
el compilador TypeScript con las dependencias
Expo, la exportación Android, una compilación APK/AAB, un emulador ni las pruebas
SQL de PGlite. Las cinco migraciones se revisaron, pero no se aplicaron a
Supabase. La prueba opcional de concurrencia con 24 sesiones PostgreSQL tampoco
se ejecutó: no hay PostgreSQL disponible. Tampoco se probaron OTP por SMTP,
OAuth Gmail, Ollama o feeds reales.

Para completar esos controles, instalar las dependencias del README y ejecutar
`bash scripts/check.sh`. El proyecto también incluye
`.github/workflows/checks.yml` para controles reproducibles cuando se suba a
un repositorio y tenga acceso a los paquetes. Ese workflow no se ejecutó aquí.
La exportación de JavaScript Android del workflow no genera un APK.

Luego verificar en Android: registro y acceso OTP, reenvío y vencimiento de
códigos, tema conservado tras reiniciar, carga PDF/DOCX y foto, correo conectado,
autorización/revocación de envíos, tarea diaria con el celular apagado, cupo entre
búsquedas, recordatorios después de 72 horas, detención por empresa e historial.
El icono del lanzador requiere una nueva compilación nativa; Expo Go conserva
su propio icono como aplicación anfitriona.

Un comprobante de Gmail confirma aceptación de la operación; no confirma entrega
al destinatario ni una respuesta. La detección automática de respuestas, OCR
y ranking semántico avanzado siguen pendientes.
