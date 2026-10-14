# Trabajo YA: lo que falta activar

**El proyecto Supabase ya existe y Render muestra el backend Live en
https://trabajo-ya-api.onrender.com.** La configuración pública de Android está
cargada y la **APK real 0.4.0 / 7 ya está publicada**:
[descargar Trabajo YA](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.4.0-real/Trabajo-YA-0.4.0-real.apk).
La [compilación 38579659455](https://github.com/ramalhectornano-sys/miapp/actions/runs/38579659455)
terminó correctamente. Los pasos de instalación y las comprobaciones pendientes
están en [APK conectada](docs/APK_REAL.md).

La actualización 0.3.2 recibe el enlace predeterminado de Supabase mediante
PKCE. Antes de ingresar, guardar **Site URL** y **Redirect URLs** con
`autoempleoia://auth/callback` y solicitar un correo nuevo desde esa APK.
El SMTP propio se necesita para personalizar las plantillas o ampliar los
usuarios de prueba; la plantilla predeterminada sirve para el ingreso por enlace.
Seguir [acceso sin contraseña](docs/AUTH_SETUP.md). Después falta probar en el teléfono el código OTP, el guardado
y la recuperación de perfil, foto y CV y una respuesta real de la IA. Esas
operaciones todavía no se comprobaron. No necesitás crear de nuevo Supabase ni
Render. Las búsquedas programadas y los correos automáticos requieren configuración
adicional: Render Free no aporta el worker/programador de esta app.

Como referencia histórica para recorrer las pantallas, está disponible la
[APK de demostración Trabajo YA 0.3.0](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.3.0-demo/Trabajo-YA-0.3.0-demo.apk).
No requiere Expo Go. Usa ejemplos identificados y no conecta IA ni envía correos;
seguí la [guía de instalación](docs/APK_GITHUB.md).

El proyecto trae el código de Android, servidor, tareas, base de datos y pruebas.
Los pasos siguientes se conservan para verificar el proyecto existente, preparar
otra instalación o activar las tareas del servidor. Las claves privadas se
cargan en tus cuentas, sin escribirlas en el código ni enviarlas por chat.

## 1. Verificar Supabase o preparar una base nueva

En el proyecto actual, confirmar las seis migraciones, los buckets privados y
las plantillas del código OTP. El instalador de proyecto nuevo no debe ejecutarse
otra vez sobre una instalación existente. Consultar
[Supabase](supabase/README.md) para aplicar solamente migraciones pendientes.

Solo para otra instalación, entrar a [Supabase](https://supabase.com/dashboard)
y crear un proyecto Free propio.
En un **proyecto nuevo sin usuarios de la app ni instalación anterior**, abrir
SQL Editor, copiar `supabase/install-new-project.sql` y ejecutar el archivo completo.
Incluye las seis migraciones en una transacción y se detiene si detecta una
instalación previa. No lo combines con la ejecución individual de esas migraciones.
No elimina datos para intentar instalar. La guía de actualizaciones está en
[Supabase](supabase/README.md).

En Authentication configurar el correo por código siguiendo
[AUTH_SETUP](docs/AUTH_SETUP.md). Para editar las plantillas Free y mostrar
un código numérico se necesita SMTP propio; el enlace predeterminado no requiere editarlo. Revisar también los límites del
proveedor de correo elegido.
Guardar la URL del proyecto, la clave pública y la privada en un gestor de claves.
La clave pública se usa en Android; la privada se usa solo en el servidor.

## 2. Preparar Google Cloud para tareas automáticas

La API de pruebas actual ya está publicada en Render. Para chat, perfil, fotos
y CV, conservar ese servicio y seguir [Render](deploy/render/README.md).
Google Cloud es la ruta alternativa preparada para API, worker y programador;
el servicio gratuito de Render no ejecuta por sí solo las búsquedas con el
celular apagado. No se activaron tareas ni envíos en la instalación actual.

Usar el proyecto donde ya creaste el cliente OAuth **Aplicación web**. Habilitar
facturación con un medio de pago y configurar presupuesto de pruebas. La solución
aprovecha cuotas gratuitas; superar cuotas o usar otros servicios puede generar cargos.

Descargar el ZIP actualizado, abrir Cloud Shell `>_` en Google Cloud, subir el ZIP
desde el menú del terminal y ejecutar:

```bash
unzip trabajo-ya.zip
cd trabajo-ya
python3 deploy/google-cloud/cloud.py setup
```

El asistente pide ID de proyecto Google, URL y clave pública de Supabase e ID
público del cliente Google. Luego solicita con entrada oculta la clave privada
de Supabase y el secreto del cliente Google. Genera y conserva la clave de cifrado,
prepara las identidades y secretos y despliega API y worker. Para fuentes todavía
no disponibles, ingresar `[]`: eso no inventa vacantes ni activa búsquedas reales.

Al terminar, imprime la URL HTTPS y el callback exacto. Copiar el callback en
las **URIs de redireccionamiento autorizados** del cliente OAuth web de Google.
Registrar tu correo como usuario de prueba si el consentimiento está en Testing.
Después de terminar el despliegue se puede cerrar Cloud Shell.

El asistente deja correo deshabilitado y no inicia el programador. La guía
[Google Cloud desde el celular](deploy/google-cloud/README.md) incluye pruebas,
fuentes, activación explícita, pausa, costes y diagnóstico. Esas verificaciones
evitan tratar un servidor que responde como prueba de búsqueda o envío.

## 3. Conectar la IA y las vacantes

El backend Render está preparado para Groq. Una vez instalada la APK conectada,
ingresar por código y probar el chat para confirmar una respuesta real; todavía
no se hizo esa comprobación. Render Free no ofrece terminal y el estado de
configuración de `/health` no acredita una inferencia.

Para una instalación alternativa en Google Cloud, la configuración inicial
identifica el asistente como **demo**. Para IA real, crear una clave en Groq y
ejecutar en Cloud Shell:

```bash
python3 deploy/google-cloud/cloud.py activate-ai
```

La [guía de IA real](docs/IA_REAL.md) explica la carga oculta de la clave y la
comprobación de una respuesta del modelo `openai/gpt-oss-20b`. Sin esa clave y
una comprobación satisfactoria, la integración no se considera conectada.
La máquina mínima de pruebas no ejecuta un modelo Ollama grande localmente.

También hace falta una fuente real con permiso de consulta y destinatarios
verificados que cumpla el [contrato del feed](backend/README.md). No hay un portal
laboral integrado por defecto. Configurar la fuente en Secret Manager y probar
una búsqueda antes de habilitar envíos. Vincular Gmail no concede por sí solo
permiso para enviar: se autoriza dentro de la app.

## 4. Compilar Android en la nube

La ruta actual usa GitHub Actions con los datos públicos ya cargados. La
compilación 0.4.0 / 7 terminó y publicó la APK conectada; no hace falta una cuenta
Expo para esa ruta. Descargarla desde el enlace de arriba e instalarla siguiendo
[APK conectada](docs/APK_REAL.md). La APK 0.3.0 de demostración no se conecta a
los nuevos servicios por instalarla de nuevo. Si Android rechaza la actualización
por una firma diferente, desinstalar la demo e instalar la APK nueva.

Como alternativa, para compilar con EAS después de `setup`, la configuración
pública de Google Cloud está en
`deploy/google-cloud/generated/mobile.env`. Desde la raíz, si todavía no tenés
una configuración local propia, copiarla:

```bash
cp deploy/google-cloud/generated/mobile.env mobile/.env.local
```

El archivo contiene solo URLs, modo y clave pública; no incluye secretos del servidor.
Crear/iniciar sesión en [Expo](https://expo.dev/signup), vincular el proyecto y
cargar las mismas variables públicas en el entorno EAS **preview**.
Seguir [ANDROID_BUILD](docs/ANDROID_BUILD.md), también desde Cloud Shell.

La compilación EAS `preview-real` produce una APK para instalar y probar. Requiere
tu cuenta, las variables reales y el certificado de EAS. El proyecto no incluye
todavía esa APK. Si el login o la firma piden verificación de tu cuenta, la completás vos.

## Qué ya está preparado

- Instalador SQL para proyecto nuevo y migraciones para desarrollo posterior.
- Asistente de despliegue, generación de variables públicas y carga privada de secretos.
- API, job de búsquedas y programador cada 15 minutos, independientes del celular.
- Gmail OAuth por usuario, autorizaciones y comprobantes, máximo de 10 intentos
  diarios y recordatorios después de 72 horas, sujetos a vacante vigente y permiso activo.
- Perfiles de compilación Android y controles locales/CI.
- Supabase creado y API de pruebas publicada en Render.
- Configuración pública y APK conectada 0.4.0 / 7 compilada, verificada y publicada.
- APK autónoma anterior de demostración compilada y publicada en GitHub.

Lo que requiere tu acceso ahora: comprobar las migraciones y el acceso OTP en
Supabase, instalar la APK conectada y probar perfil, foto,
CV y chat. Para automatización, preparar worker/programador, fuente autorizada,
Gmail y consentimiento. La compilación de la APK demo se ejecutó en GitHub
Actions; todavía no se comprobó el funcionamiento completo de la nueva
instalación desde un celular o emulador.
