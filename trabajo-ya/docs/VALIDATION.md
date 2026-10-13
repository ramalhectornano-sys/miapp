# Validación de Trabajo YA: código 0.3.1 y APK demo 0.3.0

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
para recuperar el servicio existente se actualizaron. Todavía no se confirmó
un despliegue Live ni una inferencia real en Render.

La [ejecución 38446413798](https://github.com/ramalhectornano-sys/miapp/actions/runs/38446413798)
aprobó sobre el commit `6f6cc72f548aa56dae8030f7bc66ce51a273a16f`:
**149 pruebas backend**, incluyendo el arranque del script real con HTTP local;
**construcción Docker y HTTP 200 del contenedor** con un `PORT` asignado y el
comando `/app/start.sh`; seis migraciones y cuatro baterías SQL; TypeScript y
32 pruebas móviles; instalador actualizado y 29 pruebas de despliegue.
Las pruebas de arranque usan configuración de prueba y no confirman Groq,
Gmail, inicio de sesión ni persistencia en el servidor Render del propietario.

## Servidor y APK real pendientes de activación

Se preparó **Render Free** para probar el chat con Groq y los datos privados en
Supabase. El Blueprint incluye los datos públicos del proyecto y solicita las
claves privadas solamente en Render. La guía está en
[deploy/render/README.md](../deploy/render/README.md).

Render asignó una URL pública, pero todavía no hay un backend Live confirmado. `backend_url` permanece
vacío y `prepare_android_real.py` rechaza esa configuración antes de compilar.
El workflow `android-real.yml` fuerza el modo real y no muestra el acceso a la
demostración. No se compiló ni publicó todavía un APK conectado 0.3.1.
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

No se probó en un dispositivo físico ni emulador. Una vez activados Supabase y
el backend, verificar en la APK real: ingreso por código, guardado y recuperación
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
