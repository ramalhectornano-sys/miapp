# Pruebas en la nube desde el celular

La opción recomendada es **Google Cloud Run + Cloud Run Jobs + Cloud Scheduler**,
con **Supabase Free** para usuarios, base de datos y CV privados. Aprovecha el
proyecto Google Cloud donde ya se creó el cliente OAuth web de Trabajo YA.
Los archivos están preparados; no se desplegó un servicio ni se ejecutó una
búsqueda real durante su preparación.

## Por qué esta opción

| Opción | Tareas con el celular apagado | Condición para las pruebas |
| --- | --- | --- |
| Cloud Run + Jobs + Scheduler | Sí: el programador inicia un proceso independiente de la API | Cuotas gratuitas, con facturación habilitada y posibles cargos por exceso/otros servicios |
| Render Free | Su API gratuita no aporta un worker continuo ni cron gratuito | La API se suspende sin tráfico; los cron son de pago |
| Oracle Always Free | Una VM permite cron, API y Ollama | Sujeta a capacidad disponible, posible recuperación por inactividad y administración de Linux/TLS |
| Railway | Admite procesos y cron | Créditos de prueba y crédito mensual limitado; no asegura sostener todo el sistema gratis |

Fuentes oficiales consultadas para esta recomendación:
[Cloud Run](https://cloud.google.com/run/pricing),
[Render Free](https://render.com/docs/free),
[Render Cron](https://render.com/docs/cronjobs),
[Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
y [Railway Trial](https://docs.railway.com/pricing/free-trial).

La API puede bajar a cero instancias cuando no se usa; **el worker no se ejecuta
dentro de esa API**. Cloud Scheduler arranca el job, este consulta las búsquedas
vencidas en Supabase, procesa un lote y termina. No depende de una sesión de
Cloud Shell, de abrir la aplicación ni de dejar el celular encendido.

## Qué significa gratis

Google requiere una cuenta de facturación con un medio de pago. Esta configuración
busca aprovechar el nivel gratuito, sin prometer una factura final de cero.
Se usa `us-central1`, una instancia máxima de API, mínimo cero y un job con
1 CPU/512 MiB. El programador ejecuta cada **15 minutos**. En pruebas con pocas
búsquedas, puede haber unos 15 minutos de demora; una cola, una ejecución larga
o fallos pueden agregar más demora. No se promete ejecución al segundo exacto.

Cloud Run Jobs tiene una cuota mensual de 240.000 vCPU-segundos y cobra al menos
un minuto por ejecución. En 31 días, 2.976 ejecuciones de menos de un minuto
con 1 CPU equivalen a 178.560 vCPU-segundos. Ese cálculo cubre solo esos jobs,
no todos los componentes ni ejecuciones largas. Bajar el intervalo a 5 minutos
excede esa cuota incluso con jobs muy breves.
[Precios de Cloud Run](https://cloud.google.com/run/pricing).

Cloud Scheduler incluye tres definiciones de tareas por cuenta de facturación;
esta solución usa una, que despacha las búsquedas de todos los usuarios.
[Precios de Scheduler](https://cloud.google.com/scheduler/pricing).

Builds, imágenes guardadas, acceso a secretos, red e IA tienen sus propias cuotas
y posibles cargos. Revisar [Cloud Build](https://cloud.google.com/build/pricing),
[Artifact Registry](https://cloud.google.com/artifact-registry/pricing) y
[Secret Manager](https://cloud.google.com/secret-manager/pricing).
Eliminar imágenes antiguas que ya no se usen. Crear una alerta de presupuesto
pequeño: una alerta normal avisa, no corta el gasto. Si se habilita un Spend Cap
compatible con Cloud Run, revisar su alcance; no limita automáticamente todos
los servicios del proyecto.
[Presupuestos y Spend Caps](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps).

## Cuentas que hacen falta

- **Google Cloud:** usar el proyecto del cliente OAuth web ya creado. Habilitar
  facturación y conservar acceso de propietario/administrador para configurar
  los recursos. No hace falta otra cuenta para Run, Scheduler o Secret Manager.
- **Supabase:** crear un proyecto Free propio si todavía no existe. Guarda los
  perfiles, los CV y las sesiones; su clave de servicio se configura solo en el servidor.
- **Proveedor de IA:** para conversar con un modelo real, usar uno compatible
  con OpenAI y modelos abiertos. Cloud Run de 512 MiB no aloja Ollama/Qwen 7B.
  La IA externa es configurable y su plan tiene límites/costes independientes.
  Se puede desplegar primero en `AI_PROVIDER=demo`, claramente identificado,
  y cambiarlo al conectar el proveedor; eso no activa una IA real.
  Se incluye activación y prueba para Groq `openai/gpt-oss-20b`, con clave privada
  guardada en Secret Manager. Seguir [IA_REAL](../../docs/IA_REAL.md).
- **SMTP para el acceso:** para probar con el correo propietario autorizado
  puede servir el SMTP de desarrollo de Supabase con sus límites. Para usuarios
  externos, configurar SMTP propio, por ejemplo un proveedor con plan de prueba.
  Puede exigir un dominio verificado. Este correo envía los códigos de acceso;
  las postulaciones salen por el Gmail OAuth de cada usuario.
- **Expo:** se necesita después para compilar e instalar la APK conectada.
  No hace falta Expo ni GitHub para desplegar este backend usando el ZIP.

Supabase Free puede pausar proyectos con poca actividad y limita base/archivos.
Restaurar el proyecto desde el dashboard si ocurre; no se promete continuidad
de producción con este plan.
[Pausa de proyectos](https://supabase.com/docs/guides/platform/free-project-pausing)
y [SMTP de Supabase](https://supabase.com/docs/guides/auth/auth-smtp).

## Pasos desde Android

### 1. Preparar Google Cloud

Abrir [Google Cloud Console](https://console.cloud.google.com/) desde Chrome
o la aplicación Google Cloud. Seleccionar el mismo proyecto del cliente OAuth.
Anotar el **ID del proyecto**, que no es el nombre visible ni el número de proyecto.
Habilitar la cuenta de facturación y crear el presupuesto de pruebas.
Si una pantalla no se adapta, usar **Sitio para computadoras** en Chrome.

### 2. Crear y configurar Supabase

Abrir [Supabase Dashboard](https://supabase.com/dashboard), crear un proyecto
Free y guardar su contraseña de base de datos en un gestor propio. En **SQL Editor**,
ejecutar los cinco archivos de `supabase/migrations` en orden, del `001` al `005`.
Para un proyecto nuevo vacío también se incluye `supabase/install-new-project.sql`,
que reúne esos cinco archivos en una transacción con un guard de instalación.
Elegir una sola ruta: archivo único o migraciones individuales, sin ejecutarlas dos veces.
El contenido SQL es público; se puede abrir desde el ZIP o consultar en Cloud Shell.
No ejecutar un reset sobre un proyecto con datos que se quieran conservar.

Configurar Email OTP y sus plantillas con `{{ .Token }}` según
[AUTH_SETUP](../../docs/AUTH_SETUP.md). Copiar para la configuración del servidor
la URL del proyecto y la clave pública. La clave de servicio se guarda en
Secret Manager, en un paso aparte; nunca en Android ni dentro de este repositorio.

### 3. Subir el proyecto a Cloud Shell

Descargar `trabajo-ya.zip` en el celular. Abrir **Cloud Shell** con el icono `>_`
de Google Cloud. En el menú del terminal, elegir **Subir archivo** y seleccionar
el ZIP desde Descargas. Cloud Shell también se puede abrir en la aplicación Google
Cloud para Android.
[Instrucciones oficiales para móvil](https://support.google.com/cloud/answer/6143581?hl=en).

En el terminal ejecutar:

```bash
unzip trabajo-ya.zip
cd trabajo-ya
```

La consola puede pedir autorización para usar tu cuenta. Los comandos corren
en Cloud Shell, no en el sistema Android. Después del despliegue se puede cerrar
el terminal sin apagar los servicios de Run ni el programador.

### 4. Configurar y desplegar

Las herramientas y los comandos exactos se detallan a continuación en la sección
de archivos. Usar únicamente datos públicos en `cloud-config.json`: ID de proyecto,
región, URL/clave pública Supabase, ID público del cliente Google y proveedor/modelo
de IA. Los valores de ejemplo deben sustituirse antes de ejecutar el despliegue.

Los secretos se cargan por entrada oculta o desde **Secret Manager** en la consola.
La clave Fernet se genera y guarda sin mostrarla; es la misma en API y worker.
Conservarla estable: regenerarla deja ilegibles las conexiones de Gmail anteriores.
La herramienta no guarda contraseñas ni tokens en el código o archivos de configuración
públicos y no crea claves JSON de cuentas de servicio.

El despliegue deja los envíos deshabilitados y el programador sin activar.
Antes de activarlos, completar las verificaciones de la siguiente sección.

### 5. Registrar el callback real de Google

El despliegue entrega una dirección HTTPS terminada en `run.app`. En Google Cloud,
abrir **Google Auth Platform / Clientes**, elegir el cliente **Aplicación web**
existente y agregar en **URIs de redireccionamiento autorizados**:

```text
https://<URL-REAL-DEL-SERVICIO>/api/mail/google/callback
```

Usar la URL exacta que imprime el despliegue, sin agregar una segunda barra,
sin usar el nombre del paquete Android y sin reemplazarla por una URL inventada.
La herramienta configura esa misma dirección como `GOOGLE_REDIRECT_URI` del servidor.
Habilitar Gmail API y agregar tu correo como usuario de prueba si el consentimiento
está en Testing. No se necesita SHA-1 para este flujo web.

Con permisos Gmail y consentimiento externo en Testing, los refresh tokens pueden
vencer a los siete días; reconectar durante las pruebas. Para uso sostenido,
completar los requisitos de publicación y verificación que indique Google.
[OAuth de Google](https://developers.google.com/identity/protocols/oauth2).

### 6. Conectar la app y comprobar una búsqueda

Configurar en Expo la URL HTTPS de Run, la URL/clave pública de Supabase y modo
real siguiendo [ANDROID_BUILD](../../docs/ANDROID_BUILD.md). Desde la APK:

1. Solicitar y verificar el código de acceso, completar perfil y subir un CV real.
2. Conectar el Gmail propio y comprobar que figura la dirección correcta.
3. Configurar **una fuente real autorizada de vacantes** que cumpla el contrato
   del [backend](../../backend/README.md). No existe un portal conectado por defecto.
4. Crear una búsqueda y probarla primero sin enviar correos. Revisar su ejecución
   y resultados; `/health` no prueba conexión ni acredita una búsqueda ejecutada.
5. Para correo, usar una vacante propia de prueba y destinatario autorizado;
   habilitar envíos en el servidor y aprobar expresamente esa postulación en la app.
   Comprobar el ID real de Gmail en el historial antes de considerarla enviada.

### 7. Activar las búsquedas automáticas

Una vez verificada la fuente y la conexión Gmail, autorizar en la app la búsqueda,
su CV, cuenta, fuentes y vencimiento. Elegir recordatorios si se desean. Activar
el programador mediante el comando de esta guía. Apagar el celular y comprobar
después en el historial una ejecución programada y, cuando exista, su comprobante
de envío. No se inventan resultados si no se encontró ninguna vacante.

El máximo de 10 intentos diarios suma todas las búsquedas, envíos manuales y
recordatorios. Repetir exige al menos 72 horas desde el último envío confirmado,
vacante vigente recuperada nuevamente, consentimiento activo y ausencia de
supresión/respuesta o resultado incierto. El reloj de pruebas consulta cada
15 minutos; el intervalo mínimo de 72 horas nunca se acorta.

## Diagnóstico

Revisar **Cloud Run → servicio** para la URL y los logs, **Cloud Run → Jobs**
para las ejecuciones del worker, **Cloud Scheduler** para su estado y Supabase
para `job_search_runs`/`applications`. Una ejecución de infraestructura exitosa
sin búsquedas vencidas no significa que se buscó empleo o se envió un correo.

El worker `--once` devuelve error si una búsqueda falla, queda bloqueada o no
confirma su registro. No borra reservas ni vuelve a intentar un envío incierto.
Si un proceso se interrumpe abruptamente, su reserva de búsqueda puede tardar
hasta una hora en quedar disponible de nuevo. La base mantiene las protecciones
de concurrencia aunque se solapen tareas.

Los logs de acceso de Uvicorn se deshabilitan y se prepara una exclusión de
request logs de Cloud Run para el callback OAuth de esta API, evitando guardar
el código/state en esos logs. Otros destinos de logs añadidos por el propietario
deben respetar el mismo criterio. No compartir contraseñas, tokens ni documentos
personales al consultar logs.

## Archivos y comprobaciones

Desde la raíz `trabajo-ya`, usar estos comandos en Cloud Shell:

```bash
python3 deploy/google-cloud/cloud.py setup
```

`setup` reúne configuración, comprobación de acceso/facturación, preparación,
carga oculta de secretos y despliegue. Conserva configuraciones y secretos que
ya existan. Genera variables públicas para Android en `generated/mobile.env`,
sin sobrescribir una configuración móvil propia, y mantiene envíos y Scheduler
sin activar. Si falla un paso, se detiene y no afirma que todo el despliegue terminó.

Para ejecutar cada etapa por separado, usar:

```bash
python3 deploy/google-cloud/cloud.py configure
python3 deploy/google-cloud/cloud.py validate
python3 deploy/google-cloud/cloud.py prepare
python3 deploy/google-cloud/cloud.py secrets
python3 deploy/google-cloud/cloud.py deploy
```

`configure` solicita los datos públicos y crea `cloud-config.json`, excluido de
Git. También se puede copiar `cloud-config.json.example` y editarlo con el editor
de Cloud Shell. `validate` es offline. `prepare` habilita las APIs, las identidades,
el repositorio de imagen y Secret Manager; necesita facturación. `secrets` pide
las claves privadas mediante entrada oculta y genera la clave de cifrado solo si
no existe. Para fuentes aún no disponibles, ingresar `[]`; eso no activa búsquedas.
`deploy` construye la imagen y configura API/job con la misma versión de cada
secreto compartido, sin activar Scheduler ni correos.
Si el programador ya estaba activo, `deploy` lo pausa antes de actualizar y
no lo reanuda automáticamente. Después de comprobar la nueva configuración,
usar `scheduler-resume` y volver a habilitar correo solo si corresponde.

La configuración pública de Android puede regenerarse después del despliegue:

```bash
python3 deploy/google-cloud/cloud.py export-mobile
```

Los datos están en `deploy/google-cloud/generated/mobile.env`. Revisar si ya
existe una configuración propia antes de copiar a `mobile/.env.local`; las mismas
variables se configuran también en EAS, pues su compilación remota usa ese entorno.

Para conectar IA real tras el despliegue inicial, editar solo los datos públicos
de `cloud-config.json`: `ai_provider="openai_compatible"`, `ai_base_url` HTTPS,
`ai_model` disponible y `ai_api_key_required=true` si necesita clave. Ejecutar
`prepare` para crear el secreto adicional, `set-secret --secret AI_API_KEY` para
cargarlo con entrada oculta y `deploy` para aplicar el cambio. El modo demo no
realiza inferencias; sin un proveedor activo no se muestra como IA conectada.

Para agregar o cambiar una fuente autorizada después:

```bash
python3 deploy/google-cloud/cloud.py set-secret --secret AUTHORIZED_JOB_FEEDS
python3 deploy/google-cloud/cloud.py deploy
```

Ingresar el JSON real del proveedor cuando lo solicite. El segundo comando fija
la nueva versión en ambos servicios y vuelve a dejar los envíos deshabilitados.
No colocar claves de APIs de fuentes en archivos públicos o en el historial del
terminal. Un `authorized:true` escrito en JSON declara una configuración;
el permiso real y la verificación del destinatario deben existir en la integración.

Para probar el worker sin envíos y después habilitar operaciones autorizadas:

```bash
python3 deploy/google-cloud/cloud.py test-worker
python3 deploy/google-cloud/cloud.py enable-mail --confirmed-real-source-and-consent
python3 deploy/google-cloud/cloud.py scheduler-enable --confirmed-real-source-and-consent
python3 deploy/google-cloud/cloud.py scheduler-status
```

Ejecutar `enable-mail` solo después de los controles del paso 6. Si es necesario
probar un correo antes de autorizar automatización, aprobar la postulación
individual en la app; el interruptor del servidor no reemplaza ese permiso.
`scheduler-enable` no crea una tarea por usuario: inicia el único despachador de
las búsquedas guardadas. Antes de la activación, una fuente `[]` se rechaza.
No ejecutar `test-worker` con envíos habilitados si se desea una prueba sin correo.

Para pausar el programador, detener envíos futuros o reanudar:

```bash
python3 deploy/google-cloud/cloud.py scheduler-pause
python3 deploy/google-cloud/cloud.py disable-mail
python3 deploy/google-cloud/cloud.py scheduler-resume --confirmed-real-source-and-consent
```

Pausar Scheduler no cancela un job ya iniciado. `disable-mail` cambia el interruptor
de API y job para futuras operaciones/instancias; un proceso en curso mantiene
su entorno inicial. Para detener una búsqueda o sus recordatorios, usar los
controles de revocación/pausa de la app, que la base comprueba antes de reservar.

Los archivos del directorio son:

- `cloud.py`: configuración, secretos, despliegue y controles desde Cloud Shell.
- `cloud-config.json.example`: datos públicos de ejemplo; no contiene credenciales privadas.
- `cloudbuild.yaml`: construcción del backend con identidad separada.
- `../../backend/.gcloudignore` y `.dockerignore`: solo suben código Python,
  requirements y Dockerfile; excluyen archivos de configuración y documentos.
- `test_cloud.py`: pruebas locales con comandos cloud simulados, sin crear recursos.

Además, la herramienta construye una carpeta temporal con la lista explícita de
fuentes antes de subirla: Dockerfile, requirements y módulos Python de `app`.
Los CV, archivos JSON de tokens, `.env` y otros documentos no se copian a esa
carpeta, independientemente del comportamiento de los archivos de exclusión.

Se revisan offline antes de entregar el ZIP. La ejecución de los comandos cloud
en tu proyecto requiere los permisos y cuentas indicados; no fue realizada en
este entorno. No se confirmó una URL activa, tarea programada ni envío real.
