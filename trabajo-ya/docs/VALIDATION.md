# Validación de Trabajo YA

## Búsqueda web y Android 0.4.0

Se añadieron consultas Tavily por puesto y ciudad, extracción con citas de IA,
registro de enlaces por usuario, revisión manual y worker de pruebas separado.
Los hallazgos web no verifican destinatarios y no habilitan correo automático.
No se implementaron país/provincia/identificadores geográficos ni kilómetros.
El [estado de los requisitos geográficos](ESTADO_UBICACIONES_Y_KM.md) distingue
lo implementado, lo pendiente y las comprobaciones reales que aún faltan.

La [verificación 38579659524](https://github.com/ramalhectornano-sys/miapp/actions/runs/38579659524)
aprobó **221 pruebas backend**, **44 móviles**, TypeScript, **29 cloud**,
seis migraciones y pruebas SQL, y arranque del contenedor. La integración
Tavily → IA → base → ofertas se prueba con MockTransport; esos comprobantes no
son consultas a Internet ni escrituras reales en la base del usuario.
El usuario confirmó Gmail conectado y mostró los nombres de variables Tavily
en Render; los valores permanecen ocultos y no se verificó una consulta real.

La [compilación 38579659455](https://github.com/ramalhectornano-sys/miapp/actions/runs/38579659455)
publicó [Trabajo-YA-0.4.0-real.apk](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.4.0-real/Trabajo-YA-0.4.0-real.apk) con `versionCode=7`,
`demo=false`, paquete y enlace nativo conservados. `apksigner` y `aapt`
verificaron la APK. El comprobante del certificado coincide con0.3.3.
APK: **51844897 bytes**. SHA-256: `ce7ef7c50ee7981b6f373db54ccbf330aa78306c052901b5d045335b81018299`.
Commit compilado: `aefe282ac4b564d507ea78025dbf502aec7f0a3c`.

El worker se publicó en la rama predeterminada main, commit
`53cf7db50ffd0532fad3d5ad4b9540997f7e1545`, además de trabajo-ya-real. Está apagado por
defecto y requiere secretos, variables y activación expresa; no se ejecutó
una tarea real ni se envió un correo durante estas verificaciones.

## Entrega Android 0.3.3 e integración de PR2

La [PR2](https://github.com/ramalhectornano-sys/miapp/pull/2) se integró conservando
la corrección del chat y el diagnóstico de permisos del servidor. Su prueba
verifica respuesta del proveedor, guardado de los dos mensajes en un solo lote,
lectura del historial, sesión inválida, error del proveedor y error de escritura.
Los transportes son simulados únicamente en las pruebas.

La [verificación 38568445782](https://github.com/ramalhectornano-sys/miapp/actions/runs/38568445782)
aprobó **161 pruebas backend**, **44 móviles**, TypeScript, **29 de despliegue**,
las seis migraciones y el arranque del contenedor. Supabase Auth respondió
HTTP200 y la lectura anónima de perfiles sigue bloqueada; no se leyeron datos.

La [compilación 38568445689](https://github.com/ramalhectornano-sys/miapp/actions/runs/38568445689)
publicó [Trabajo-YA-0.3.3-real.apk](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.3.3-real/Trabajo-YA-0.3.3-real.apk)
con `versionCode=6`, `demo=false`, paquete `com.trabajoya.autoempleoia` y esquema
`autoempleoia`. `apksigner` y `aapt` verificaron la APK antes de publicar.
El digest del comprobante de certificado coincide con el de 0.3.2; se conserva
la firma de prueba. APK: **51835001 bytes**; SHA-256
`db706fdf71cc1c00aa38e69e5f5c8ab2eeba37f29d358f54ef0b47668603b602`.
Commit compilado: `4a9623b732918a1bf43592c10d971d7ce7addd22`.

La APK se instala como actualización. La corrección de persistencia también
necesita el despliegue de ese backend en Render. No se confirmó un chat, OAuth
Gmail, búsqueda o envío real con una cuenta del usuario mediante estas pruebas;
las dependencias externas pendientes siguen en [SOLUCION_ERRORES](SOLUCION_ERRORES.md).

## Corrección de guardado del chat (backend 0.3.1)

Se identificó un defecto reproducible en `/api/chat`: el insert masivo de
`chat_messages` enviaba una fila sin `metadata` y otra con ese campo. PostgREST
rechaza claves distintas con PGRST102. Ahora ambas filas incluyen `metadata`.
La prueba de regresión usa un transporte que aplica esa regla y verifica la
respuesta y los dos mensajes persistidos. Se diferencian errores de sesión,
acceso del servidor y esquema pendiente sin devolver diagnósticos privados.
Los logs incluyen solo método, recurso conocido, estado HTTP y códigos permitidos.

Las **19 pruebas enfocadas** de chat, errores y claves Supabase pasan localmente.
Se utilizan proveedores simulados únicamente en pruebas; no acreditan una
respuesta remota de IA o escritura en la base del usuario. El servicio gratuito
tiene Auto-Deploy apagado: el propietario debe ejecutar **Manual Deploy → Deploy
latest commit** en Render. `/health` debe mostrar backend 0.3.1 después del despliegue.
Esta corrección inicial no requería una APK nueva ni una migración SQL; en ese
momento la APK publicada era 0.3.2. La [guía de los avisos](SOLUCION_ERRORES.md) documenta lo
pendiente de Gmail, fuentes autorizadas y worker; no se activaron envíos.

## Corrección de enlaces de autenticación 0.3.2

Se incorporó `emailRedirectTo: autoempleoia://auth/callback`, `flowType: pkce`,
el receptor de URL inicial y eventos de React Native Linking, y el canje del
código mediante el SDK Supabase. Se validan esquema, host, ruta, parámetros
repetidos/mezclados y errores; no se aceptan tokens implícitos antiguos. Los
intercambios concurrentes se deduplican. La restauración inicial de sesión no
sobrescribe un evento de Auth posterior. El puente nativo usa entropía Expo y
SHA-256 para S256, con soporte UTF-8 cuando falta TextEncoder.

La [verificación 38453859674](https://github.com/ramalhectornano-sys/miapp/actions/runs/38453859674)
terminó correctamente: **44 pruebas móviles** (12 nuevas de enlaces/PKCE),
TypeScript, 149 pruebas backend, 29 pruebas cloud y seis migraciones SQL.
La prueba del SDK real sustituye únicamente el transporte y comprueba redirect
exacto, challenge S256 y exclusión del verifier del cuerpo HTTP. No envía correo
ni valida tokens contra el proyecto remoto. La compilación nativa en
[38453859661](https://github.com/ramalhectornano-sys/miapp/actions/runs/38453859661)
terminó correctamente y publicó la APK **0.3.2 / versionCode5** con firma debug.
`apksigner` y `aapt` verificaron firma, paquete y versión. APK: 51.835.005 bytes;
SHA-256 `91ffd2af51d3060fc5cc913a2e79c2c14cce0d2844cfec2c9745f6942222fc00`.
Commit compilado: `60319e1f09c86f5eefbe4186cec9dbebaaf04916`.
[Descargar APK0.3.2](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.3.2-real/Trabajo-YA-0.3.2-real.apk).
El comprobante del certificado tiene el mismo digest que la entrega0.3.1;
la actualización conserva el certificado de prueba. Se comprobó que el manifest
Android generado contiene el esquema en un intent VIEW/BROWSABLE/DEFAULT.

Site URL y Redirect URLs deben ser `autoempleoia://auth/callback`. El propietario
respondió “listo”, pero estas herramientas no acceden al Dashboard ni confirman
sus valores guardados. La guía está en [AUTH_SETUP.md](AUTH_SETUP.md).
No se configuraron Android App Links HTTPS o assetlinks.json. El enlace se debe
solicitar nuevamente desde la APK0.3.2 y abrir en la misma instalación. No se
probó físicamente un ingreso completo, un enlace vencido ni la sesión tras
reiniciar; siguen pendientes de comprobación en el teléfono.

## Comprobaciones del código conectado 0.3.1

La [ejecución 38439756866 de GitHub Actions](https://github.com/ramalhectornano-sys/miapp/actions/runs/38439756866)
terminó correctamente sobre el commit `6b6538ed7a4159bdab163023afafe3895dc94817`:

- **148 pruebas Python** del backend, incluida la preparación del APK real y
  del instalador de base de datos, y compilación de los módulos Python.
- **Seis migraciones ejecutadas en PostgreSQL embebido (PGlite)** y cuatro
  baterías SQL: aislamiento de usuarios, consentimiento de envío, presupuesto
  diario y recordatorios, y persistencia del CV principal.
- **TypeScript sin errores y 32 pruebas móviles**: 18 de lógica de acceso,
  demostración, temas y permisos, más 14 del servicio de perfil, foto y CV.
- **29 pruebas de despliegue** con gcloud sustituido y comprobación `--check`
  del instalador SQL único actualizado.

Las pruebas SQL ejecutan las transacciones con los esquemas de autenticación y
Storage del archivo de preparación de pruebas. No sustituyen una verificación
contra Supabase alojado ni ejecutan la prueba opcional de concurrencia de 24
sesiones PostgreSQL. Las pruebas de móvil usan dobles del transporte Supabase;
las de backend y despliegue tampoco prueban Gmail, Groq o recursos cloud reales.

Se corrigió la persistencia del CV principal con la migración 006 y una RPC
atómica. Guardar texto conserva la foto y el CV principal existentes. La subida
de fotos obtiene una URL privada utilizable antes de reemplazar la asociación;
una respuesta perdida no borra un archivo cuya operación podría haber quedado
confirmada en el servidor. Las pruebas cubren estas situaciones y la recuperación
de la confirmación de una subida de CV.

Dos fixtures SQL separan ahora la ejecución de una función con efectos de la
lectura del resultado: PostgreSQL puede evaluar una subconsulta de un `IF` antes
de ejecutar esa función. No se modificaron las migraciones históricas para
adaptarlas a esos fixtures.

## Verificación del proyecto Supabase del propietario

El propietario creó Supabase y compartió su URL y clave **pública**. Están
cargadas en `mobile/services.public.json` y `render.yaml`; ninguna clave privada
se añadió al código. En la misma ejecución de CI se consultaron únicamente:

- `/auth/v1/health`: **HTTP 200**, el servicio de autenticación respondió.
- `/rest/v1/profiles?select=user_id&limit=0`: tabla todavía no instalada.

No se leyeron registros personales, no se solicitaron códigos de acceso y no
se aplicó SQL al proyecto remoto desde estas herramientas. En la ejecución
posterior 38446413798, `profiles` ya existía y el rol anónimo no tenía permiso de
lectura. Esa comprobación no verifica todas las migraciones ni el registro de
usuarios; no se volvió a ejecutar el instalador sobre la base existente.

## Corrección del arranque en Render

El propietario creó el servicio Render Free y realizó un despliegue del commit
`044954f`. La construcción Docker terminó, pero el arranque falló con código 127:
el comando compuesto de shell del Blueprint se interpretó incorrectamente.
Se reemplazó por `/app/start.sh`, un ejecutable incluido en la imagen Docker que
respeta `PORT` y evita registrar las URL de acceso. La configuración y la guía
para recuperar el servicio existente se actualizaron. El propietario mostró
posteriormente el servicio **Live** con el commit corregido `6f6cc72`. Una prueba
posterior de `/health` remoto pasó en el preparador Android; todavía no se confirmó
una inferencia real en Render.

La [ejecución 38446413798](https://github.com/ramalhectornano-sys/miapp/actions/runs/38446413798)
aprobó sobre el commit `6f6cc72f548aa56dae8030f7bc66ce51a273a16f`:
**149 pruebas backend**, incluyendo el arranque del script real con HTTP local;
**construcción Docker y HTTP 200 del contenedor** con un `PORT` asignado y el
comando `/app/start.sh`; seis migraciones y cuatro baterías SQL; TypeScript y
32 pruebas móviles; instalador actualizado y 29 pruebas de despliegue.
Las pruebas de arranque usan configuración de prueba y no confirman Groq,
Gmail, inicio de sesión ni persistencia en el servidor Render del propietario.

## Servidor activo y APK conectada publicada

Se preparó **Render Free** para probar el chat con Groq y los datos privados en
Supabase. El Blueprint incluye los datos públicos del proyecto y solicita las
claves privadas solamente en Render. La guía está en
[deploy/render/README.md](../deploy/render/README.md).

La URL `https://trabajo-ya-api.onrender.com` está incorporada en
`mobile/services.public.json`. La [compilación 38447381098](https://github.com/ramalhectornano-sys/miapp/actions/runs/38447381098)
validó la configuración pública y completó la consulta `/health` al servidor real:
exige HTTP 200, Supabase `configured` y proveedor de IA `configured_unverified`.
Pasaron TypeScript, 32 pruebas móviles, Expo prebuild y Gradle
`assembleRelease`. `apksigner` verificó la firma y `aapt` confirmó nombre Trabajo
YA, paquete `com.trabajoya.autoempleoia`, versión **0.3.1 / 4**. La
[APK conectada descargable](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.3.1-real/Trabajo-YA-0.3.1-real.apk)
está publicada como versión de prueba con firma debug. Tamaño: **51.829.057 bytes**;
SHA-256: `85ae0acee37710efd52ded50420f2f109888d3db6825fff0f557c94643150a51`.
Commit compilado: `4a5b40a00f92140cce7df1d44664c76175ec0abb`.
La versión adjunta checksum, certificado público, información del paquete,
commit y lockfile. No se ejecutó en dispositivo físico o emulador.
El workflow `android-real.yml` fuerza el modo real y la app no ofrece entrar a
la demostración.
Una respuesta `/health` con IA `configured_unverified` solo informa configuración;
no confirma una inferencia. Ver [APK_REAL.md](APK_REAL.md).

Render Free suspende la API por inactividad. Este Blueprint no ejecuta un worker
ni un programador, y mantiene el envío de correo deshabilitado. Las búsquedas y
los envíos automáticos requieren activar una alternativa de servidor programado,
fuentes de vacantes autorizadas y OAuth Gmail del usuario. `deploy/google-cloud`
prepara Cloud Run, un worker Job y Scheduler; requiere facturación habilitada y
puede generar cargos. `deploy/compose.yaml` ofrece la alternativa de VPS.
Ninguna de esas alternativas se desplegó desde esta sesión.

## APK de demostración publicada anteriormente

La APK **0.3.0 demo** se compiló y publicó en la
[ejecución 38427300341](https://github.com/ramalhectornano-sys/miapp/actions/runs/38427300341).
Pasaron TypeScript, 18 pruebas móviles, Expo prebuild y Gradle `assembleRelease`.
`apksigner` verificó la firma debug y `aapt` comprobó nombre `Trabajo YA`, paquete
`com.trabajoya.autoempleoia`, versión 0.3.0 y versionCode 3. No necesita Metro.

El archivo de aquella versión tiene 51.826.293 bytes y SHA-256
`3839f47c4bba1a0cab47d4c9f112132772e9d687830be8d44a783f1d2bbbead1`.
La [versión publicada](https://github.com/ramalhectornano-sys/miapp/releases/tag/trabajo-ya-v0.3.0-demo)
contiene sus huellas públicas en `certificado-prueba.txt`. Esa APK usa datos
de demostración; crear cuentas no cambia su configuración incorporada.
No se configuró una firma privada de producción.

La imagen `images/maqueta-trabajo-ya.png` es una maqueta y `preview.html` representa
el diseño. No son capturas de una ejecución Android. El logo proporcionado se
conserva en `mobile/assets/brand/trabajo-ya-logo.jpg`; el PNG del icono es su
adaptación. Falta comprobar el icono en un lanzador Android.

## Verificación funcional pendiente

El propietario confirmó que no configuró las plantillas numéricas de Supabase.
La APK0.3.1 no procesaba los enlaces de la plantilla predeterminada, y el
propietario informó `localhost:3000` con `access_denied`. Se le indicaron las plantillas Magic Link y Confirm signup con
`{{ .Token }}`. La captura posterior mostró que Supabase bloquea la edición de templates hasta
configurar SMTP propio, conforme al cambio de los proyectos Free nuevos del
3 de junio de 2026. Se corrigieron las guías y se preparó la configuración de
Gmail SMTP para pruebas, con contraseña de aplicación guardada solo en Supabase.
La APK0.3.2 añade el ingreso mediante el enlace predeterminado; SMTP propio
queda como requisito de personalización o entrega a otros usuarios. No se
solicitaron códigos desde estas herramientas ni se obtuvo una sesión de usuario.
[Regla oficial](https://supabase.com/changelog/46599-changes-to-email-template-customisation-on-free-tier).

No se probó en un dispositivo físico ni emulador. Con Supabase y
el backend creados, verificar en la APK real: ingreso por código, guardado y recuperación
del perfil, foto y CV al reiniciar, tema persistente y una respuesta real del chat.
El SMTP incluido de Supabase limita las pruebas a correos del equipo y a dos
mensajes por hora; para otros usuarios hace falta configurar SMTP propio.

Después de activar Gmail y un programador, comprobar consentimiento, revocación,
tareas con el celular apagado, máximo de 10 correos diarios por usuario, espera de
72 horas, detención por empresa e historial con confirmación del proveedor.
No se enviaron correos reales ni se ejecutaron búsquedas reales en esta sesión.
La detección automática de respuestas, OCR y ranking semántico avanzado siguen
pendientes. Una confirmación de Gmail demuestra aceptación de la operación,
no entrega al destinatario ni una respuesta.
