# Trabajo YA: lo que falta activar

El proyecto trae el código de Android, servidor, tareas, base de datos y pruebas.
Todavía no hay un backend publicado ni un APK compilado con tus servicios reales.
Podés realizar los pasos siguientes desde el celular; las claves privadas se
cargan en tus cuentas, sin escribirlas en el código ni enviarlas por chat.

## 1. Crear la base en Supabase

Entrar a [Supabase](https://supabase.com/dashboard) y crear un proyecto Free propio.
En un **proyecto nuevo sin usuarios de la app ni instalación anterior**, abrir
SQL Editor, copiar `supabase/install-new-project.sql` y ejecutar el archivo completo.
Incluye las cinco migraciones en una transacción y se detiene si detecta una
instalación previa. No lo combines con la ejecución individual de esas migraciones.
No elimina datos para intentar instalar. La guía de actualizaciones está en
[Supabase](supabase/README.md).

En Authentication configurar el correo por código siguiendo
[AUTH_SETUP](docs/AUTH_SETUP.md). Para las primeras pruebas, revisar los destinatarios
y límites del correo de desarrollo; para usuarios externos hace falta SMTP propio.
Guardar la URL del proyecto, la clave pública y la privada en un gestor de claves.
La clave pública se usa en Android; la privada se usa solo en el servidor.

## 2. Preparar Google Cloud desde el celular

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

La configuración inicial de servidor identifica el asistente como **demo**.
Para IA real, crear una clave en Groq y ejecutar en Cloud Shell:

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

Después de `setup`, la configuración pública está en
`deploy/google-cloud/generated/mobile.env`. Desde la raíz, si todavía no tenés
una configuración local propia, copiarla:

```bash
cp deploy/google-cloud/generated/mobile.env mobile/.env.local
```

El archivo contiene solo URLs, modo y clave pública; no incluye secretos del servidor.
Crear/iniciar sesión en [Expo](https://expo.dev/signup), vincular el proyecto y
cargar las mismas variables públicas en el entorno EAS **preview**.
Seguir [ANDROID_BUILD](docs/ANDROID_BUILD.md), también desde Cloud Shell.

La compilación `preview-real` produce una APK para instalar y probar. Requiere
tu cuenta, las variables reales y el certificado de EAS. El proyecto no incluye
todavía esa APK. Si el login o la firma piden verificación de tu cuenta, la completás vos.

## Qué ya está preparado

- Instalador SQL para proyecto nuevo y migraciones para desarrollo posterior.
- Asistente de despliegue, generación de variables públicas y carga privada de secretos.
- API, job de búsquedas y programador cada 15 minutos, independientes del celular.
- Gmail OAuth por usuario, autorizaciones y comprobantes, máximo de 10 intentos
  diarios y recordatorios después de 72 horas, sujetos a vacante vigente y permiso activo.
- Perfiles de compilación Android y controles locales/CI.

Lo que requiere tu acceso: crear proyectos y cuentas, habilitar facturación,
cargar credenciales, conectar proveedor de IA y fuente autorizada, autorizar
Gmail y verificar la app instalada. Los resultados reales se comprueban después
de esos pasos; hasta ahora las comprobaciones se hicieron localmente.
