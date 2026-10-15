# Avisos de datos, Gmail y envíos de Trabajo YA

Las capturas muestran tres problemas distintos. Se corrigió un defecto del
guardado del chat compatible con el aviso de datos; ese mensaje era genérico
y los logs remotos permiten distinguir otras causas. Las capturas iniciales también mostraban Gmail sin configurar. El propietario
confirmó posteriormente que ya lo vinculó; no hay que recrear esa conexión.
Las capturas recientes siguen mostrando envíos deshabilitados y ninguna fuente
apta para autorizar correo. El archivo
`render.yaml` gratuito prepara la API y la IA, pero no instala un worker ni
incorpora credenciales Google. Cambiar el texto del aviso no habilita el servicio.

Esta guía usa las direcciones públicas que ya están configuradas para este
proyecto. No contiene claves privadas.

## 1. Error de datos

El mensaje «No se pudo completar la operación de datos» procede del backend.
Se identificó un fallo en el guardado del chat: el servidor enviaba dos filas a
Supabase con campos distintos; una tenía `metadata` y la otra no. PostgREST
rechaza ese lote con `PGRST102`. La corrección envía ambas filas con el mismo
conjunto de campos, conservando el historial real. Para aplicarla en Render,
elegí **Manual Deploy → Deploy latest commit** y esperá **Live**; no hace falta
una APK nueva para esta corrección del backend.

El código actualizado identifica el backend como **0.5.3** en
https://trabajo-ya-api.onrender.com/health después de desplegarlo. La aplicación
0.5.0 necesita también la migración 007 para geografía e historial web.
Las versiones de servidor y aplicación son independientes. Esa respuesta
permite distinguir el servidor anterior, pero no confirma una llamada de IA
ni una conversación guardada: comprobá ambas desde el chat autenticado.

Que se pueda iniciar sesión o ver un CV no acredita la clave de servicio de
Render: la APK usa su propia sesión de Supabase y el backend utiliza otra
credencial para sus operaciones privadas.

En **Render → trabajo-ya-api → Environment**, comprobá que:

- `SUPABASE_URL` sea `https://ecdbcdbwcvwhawtzfkkk.supabase.co`.
- `SUPABASE_ANON_KEY` sea la clave pública Publishable/anon de ese proyecto.
- `SUPABASE_SERVICE_ROLE_KEY` sea una **Secret key** `sb_secret_…` o la antigua
  `service_role` del mismo proyecto; la Publishable key no sirve en este campo.

Copiá las claves solamente entre los paneles de Supabase y Render. No se necesita
volver a registrar al usuario, borrar documentos ni reinstalar la base para
revisar estas variables. Si se aplican correcciones del código, usá **Manual
Deploy → Deploy latest commit**, porque este servicio tiene Auto-Deploy apagado.

Si persiste el error, consultá el registro de la operación en **Render → Logs**.
Un `/health` con `status: ok` no demuestra por sí solo que los permisos y las
migraciones de Supabase sean correctos. No compartas valores del panel
Environment ni direcciones de autorización que contengan tokens o códigos.

## 2. Configurar Gmail desde el celular

Usá el cliente Google OAuth de tipo **Aplicación web** que ya creaste. Este flujo
recibe la autorización en FastAPI; no necesita la SHA-1 de la APK. El correo de
acceso de Supabase y el Gmail de postulaciones son configuraciones independientes.

1. Abrí [Google Cloud Console](https://console.cloud.google.com/) y elegí el
   proyecto donde creaste el cliente OAuth. En Chrome, activá **Sitio para
   computadoras** si algún control queda oculto.
2. En **APIs y servicios → Biblioteca**, habilitá **Gmail API**.
3. En **Google Auth Platform → Público/Audience**, agregá tu dirección Gmail como
   usuario de prueba si el proyecto sigue en Testing. En el menú anterior, esta
   opción está dentro de **APIs y servicios → Pantalla de consentimiento OAuth**.
4. En **Google Auth Platform → Clientes/Clients**, abrí el cliente de tipo web.
   En el menú anterior: **APIs y servicios → Credenciales → cliente OAuth web**.
5. En **URIs de redireccionamiento autorizados**, agregá exactamente:

```text
https://trabajo-ya-api.onrender.com/api/mail/google/callback
```

6. Guardá. Conservá el **ID de cliente** y el **secreto de cliente**; el segundo
   se pega solamente en Render. El esquema `autoempleoia://auth/callback`
   corresponde al ingreso mediante Supabase y se mantiene separado de este
   callback HTTPS de Gmail.

En **Render → trabajo-ya-api → Environment → Add Environment Variable**, cargá:

| Variable | Valor que corresponde |
| --- | --- |
| `GOOGLE_CLIENT_ID` | ID del cliente web, terminado en `.apps.googleusercontent.com`. |
| `GOOGLE_CLIENT_SECRET` | Secreto privado de ese mismo cliente web. |
| `GOOGLE_REDIRECT_URI` | `https://trabajo-ya-api.onrender.com/api/mail/google/callback` |
| `TOKEN_ENCRYPTION_KEY` | Clave Fernet privada, generada una sola vez como se explica abajo. |
| `MAIL_SEND_ENABLED` | Conservá `false` mientras se prepara y comprueba la integración. |

`SUPABASE_SERVICE_ROLE_KEY` también debe estar configurada: guarda el estado de
autorización y los tokens cifrados en Supabase. No pongas ninguna de estas claves
privadas en `EXPO_PUBLIC_…`, en GitHub o en la APK.

### Generar la clave de cifrado

Podés hacerlo en tu propia computadora con Python 3 o desde el celular en
[Google Cloud Shell](https://shell.cloud.google.com/). Este comando utiliza la
biblioteca estándar de Python; no instala paquetes ni llama a un proveedor:

```bash
python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"))'
```

El resultado es una **clave privada**. Copiala directamente al campo
`TOKEN_ENCRYPTION_KEY` de Render y guardá una copia en tu gestor de contraseñas.
No compartas el resultado ni una captura. Generarla en Cloud Shell no despliega
un worker; cerrar Cloud Shell tampoco detiene un servicio que ya se desplegó.
Conservá la misma clave en API y worker y en las actualizaciones: reemplazarla
impide descifrar los correos vinculados previamente.

Existe un comprobador de configuración, sin red y sin mostrar valores, para
desarrolladores con los archivos `.env` privados preparados:

```bash
python3 scripts/check_runtime.py --backend-env backend/.env --mobile-env mobile/.env --mode real --profile production
```

No es necesario crear esos archivos para usar los paneles desde el celular.
El comprobador no confirma que Google autorizó la cuenta, que una fuente tiene
permiso o que un correo se entregó.

### Comprobar la conexión

1. Guardá las variables de Render y elegí **Save, rebuild, and deploy** cuando
   aparezca. Si solo permite guardar, ejecutá **Manual Deploy → Deploy latest
   commit**. Esperá el estado **Live**.
2. Abrí Trabajo YA y elegí **Mi perfil → Conectar correo**.
3. En Google, elegí tu cuenta de prueba y concedé el permiso de envío. El backend
   solicita `gmail.send`, `userinfo.email` y `openid`; no lee tu bandeja.
4. Google vuelve al callback HTTPS y este debe confirmar **Correo conectado**.
   Volvé a la app, cerrá la pestaña del navegador si sigue abierta y actualizá
   los datos. En Mi perfil debe aparecer la dirección correcta.

Vincular Gmail no autoriza por sí solo envíos automáticos. Si Google informa
`redirect_uri_mismatch`, compará la URI autorizada y `GOOGLE_REDIRECT_URI`,
incluidos HTTPS, host y ruta. Si mantiene el aviso de integración no configurada,
verificá las cuatro variables de Gmail, la clave de servicio y que el despliegue
terminó. En Testing externo, Google puede limitar los refresh tokens a siete
días; reconectá durante pruebas y completá los requisitos de publicación antes
de depender de una autorización permanente.

## 3. Qué falta para los envíos con el celular apagado

El aviso de envíos desactivados corresponde a `MAIL_SEND_ENABLED=false`. La
configuración actual también tiene `AUTHORIZED_JOB_FEEDS=[]` y **no tiene worker**.
Activar únicamente esa variable no configura fuentes ni tareas programadas.

Para completar la automatización hacen falta:

1. **Una fuente real autorizada de vacantes**, con el contrato JSON del
   [backend](../backend/README.md#fuentes-permitidas), destinatarios verificados y
   permiso para consultas/postulaciones. No hay un portal habilitado por defecto.
2. **Un proceso de servidor independiente de la API**, continuo con
   `python -m app.worker`, o invocado por un programador con
   `python -m app.worker --once`. Usa la misma base, configuración y clave de
   cifrado que la API. No se ejecuta dentro de Android.
3. **Una comprobación controlada y autorizada** con una vacante/destinatario
   propios y una cuenta vinculada. Se habilita el interruptor en API y worker
   cuando las dependencias están listas; no se muestra «enviado» hasta recibir
   un identificador de Gmail y guardar la confirmación.
4. **Consentimiento por búsqueda**, con CV, cuenta, fuentes y vencimiento.
   Los recordatorios cada tres días requieren su opción explícita.

Render Free suspende la API cuando no tiene tráfico y no aporta workers ni cron
gratuitos. No garantiza la ejecución automática diaria con el teléfono apagado.
Los archivos preparados para [Google Cloud Run Jobs + Scheduler](../deploy/google-cloud/README.md)
permiten ejecutar el worker desde el servidor, pero requieren facturación
habilitada y pueden generar cargos; no se promete costo cero. Una VM propia
con Docker/cron es otra alternativa. No hay que crear un segundo Supabase.

La política existente limita a **10 intentos de correo por día y usuario** entre
todas sus búsquedas y envíos manuales; envía menos si no hay vacantes aptas. Los
recordatorios esperan **72 horas completas** desde el último envío confirmado,
se vuelven a validar contra la fuente actual y dejan de prepararse si la oferta
ya no está vigente o el usuario detiene los envíos al destinatario. Las nuevas
oportunidades tienen prioridad. Los timeouts inciertos no provocan reenvíos
automáticos del mismo intento.

Fuentes del proveedor: [Render Free](https://render.com/docs/free),
[Google OAuth para servidores web](https://developers.google.com/identity/protocols/oauth2/web-server)
y [vencimiento de refresh tokens de Google](https://developers.google.com/identity/protocols/oauth2#expiration).
