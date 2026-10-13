# Acceso sin contraseña: enlace a Android y código opcional

Desde la APK **0.3.2 / 5**, Trabajo YA admite el enlace de acceso de Supabase.
La persona solicita el correo desde la app y abre su enlace en el mismo celular;
la app recibe `autoempleoia://auth/callback` y canjea el código de autorización
mediante PKCE. Supabase confirma la sesión y se conserva en SecureStore.
Si la plantilla muestra un código numérico, también puede ingresarse mediante
`verifyOtp(type: email)`. El enlace y el código son de un solo uso.

La APK 0.3.1 esperaba un OTP numérico: no enviaba `emailRedirectTo` ni tenía
un receptor de enlaces Auth. Cambiar solo el Dashboard no corrige aquella APK.
No se habilitó acceso sin verificar el correo ni se desactivó su confirmación.

## Valores exactos de Supabase para esta APK

En **Authentication → URL Configuration**, guardar:

| Campo | Valor exacto |
| --- | --- |
| **Site URL** | `autoempleoia://auth/callback` |
| **Redirect URLs** | Agregar `autoempleoia://auth/callback` |

No agregar comodines ni conservar `localhost:3000` como destino de esta
instalación Android. Es un URI real basado en `expo.scheme=autoempleoia`,
paquete `com.trabajoya.autoempleoia`; no es una página web ni el callback OAuth
de Google/Gmail. Supabase admite esquemas móviles también en Site URL.
[Documentación oficial de redirecciones](https://supabase.com/docs/guides/auth/redirect-urls).

La app solicita cada correo con `emailRedirectTo` exactamente igual a ese URI
y `flowType: pkce`. La comprobación de la compilación inspecciona el manifest
Android generado: exige un intent VIEW/BROWSABLE/DEFAULT del esquema. El receptor
JavaScript contempla la apertura inicial y los eventos con la app abierta,
valida host/ruta y deduplica el intercambio del código. Usa entropía nativa y
SHA-256 para PKCE; no muestra ni registra URL, código, tokens o error del proveedor.
Los tokens de enlaces implícitos antiguos se rechazan: solicitar un enlace nuevo
desde la APK actualizada. PKCE necesita el verificador guardado en esa misma
instalación; borrar datos, reinstalar o pedir otro correo puede invalidar el enlace
anterior. [Flujo PKCE](https://supabase.com/docs/guides/auth/sessions/pkce-flow).

Se usa **deep linking por esquema personalizado**. No se configuraron Android
App Links HTTPS ni `assetlinks.json`. Para esa alternativa harían falta un dominio
controlado, el archivo publicado y la huella SHA-256 del certificado que firma
la APK. No se inventó un endpoint HTTPS de confirmación.
[Enlaces móviles](https://supabase.com/docs/guides/auth/native-mobile-deep-linking).

## Primera prueba con la plantilla predeterminada

1. Instalar la APK 0.3.2 y guardar los dos valores de URL Configuration.
2. Solicitar un correo nuevo desde esa APK. Para el correo integrado Free,
   usar una dirección miembro de la organización del proyecto.
3. Abrir el correo real en ese celular y tocar su enlace una sola vez.
   El botón Sign in en el preview del Dashboard contiene una plantilla,
   no un token real, y no sirve para probar el acceso.
4. Confirmar que vuelve a Trabajo YA y se muestra el perfil de la cuenta.
   Cerrar/reabrir la app y verificar que conserva la sesión.

La plantilla predeterminada **sí sirve para este flujo por enlace**, sin editarla.
El proveedor incluido sigue restringido a correos del equipo y dos mensajes
por hora. Si se agotó ese cupo, esperar o configurar SMTP propio; cambiar la
redirección no elimina límites del correo. Para otras personas o producción,
configurar un remitente autorizado.
[SMTP de Supabase](https://supabase.com/docs/guides/auth/auth-smtp).

## Qué significa access_denied

`localhost:3000` es el destino predeterminado de Supabase cuando la solicitud
no define un redirect permitido. Corregir el URI evita esa salida a localhost.
`access_denied` indica además que Auth rechazó la operación: no demuestra por
sí solo cuál fue la causa. Si `error_code=otp_expired`, el enlace puede estar
vencido o consumido (incluidas previsualizaciones/escáneres de correo).
Solicitar un enlace nuevo; no reutilizar el que ya falló ni pegarlo en el chat.
La app muestra mensajes fijos y no autentica ante errores de Supabase.
Consultar los logs de Auth sin publicar tokens o el enlace completo.

## Plantillas personalizadas y códigos numéricos

Para personalizar el correo o mostrar OTP en proyectos Free nuevos, primero
configurar y guardar SMTP propio: el bloqueo observado en el Dashboard se
aplica a la edición de plantillas, no a la redirección del enlace predeterminado.
Se pueden conservar `{{ .Token }}` y añadir el enlace:

```html
<a href="{{ .ConfirmationURL }}">Ingresar a Trabajo YA</a>
<p>También podés ingresar este código en la app: {{ .Token }}</p>
```

Usar `{{ .ConfirmationURL }}` para que Supabase verifique primero el correo
y genere el código PKCE de regreso. No construir el href con `{{ .SiteURL }}`
ni copiar tokens reales a la plantilla. Cambiar Magic Link y Confirm signup,
seleccionar Source y guardar ambas. Mantener confirmación de correo y, para las
plantillas locales, OTP de 6 dígitos y 600 segundos de vencimiento.
[Variables oficiales](https://supabase.com/docs/guides/auth/auth-email-templates).

## Supabase local

`supabase/config.toml` habilita registro y confirmación de correo. Configura
`otp_length = 6`, `otp_expiry = 600` y `max_frequency = "60s"` en `[auth.email]`.
Las plantillas `magic_link` y `confirmation` muestran `{{ .Token }}` en español:

- [Código de ingreso](../supabase/templates/magic_link.html).
- [Confirmación de cuenta](../supabase/templates/confirmation.html).

Desde la raíz ejecutar `supabase start` y `supabase db reset`. Revisar la salida
de la CLI para abrir el buzón local de prueba y leer el código. Supabase local
no entrega correo al buzón personal del usuario salvo que se configure SMTP.
Si la CLI ya estaba iniciada, reiniciar el stack para aplicar los cambios de Auth.

## Personalizar las plantillas del proyecto remoto

El archivo local no cambia las opciones de un proyecto alojado. **Primero
comprobar si las plantillas se pueden editar.** En proyectos Free creados desde
el 3 de junio de 2026, el proveedor de correo predeterminado conserva sus
plantillas y bloquea su edición. Si aparece **“Set up custom SMTP to edit
templates”**, configurar y guardar un SMTP propio antes de cambiar el asunto
o el cuerpo. Activar el interruptor SMTP con los campos vacíos no configura
el envío. Esta restricción está documentada en el
[cambio oficial de Supabase](https://supabase.com/changelog/46599-changes-to-email-template-customisation-on-free-tier).

En el Dashboard:

1. En Authentication, habilitar el proveedor Email y el registro de nuevas
   cuentas; mantener la confirmación del correo habilitada.
2. En **Authentication → Emails → SMTP Settings**, configurar host, puerto,
   usuario, contraseña SMTP y dirección/nombre del remitente. Guardar los datos
   y validar el remitente según el proveedor elegido. No todos exigen comprar
   un dominio, pero su autorización de envío debe estar configurada. Las
   credenciales SMTP se cargan únicamente en Supabase; nunca en el código,
   Android o el chat. Seguir la
   [guía oficial de SMTP](https://supabase.com/docs/guides/auth/auth-smtp).
3. Cuando el editor esté habilitado, en Email Templates editar **Magic Link**
   para mostrar `{{ .Token }}` y el
   texto de `magic_link.html`. Editar también **Confirm signup** con el contenido
   de `confirmation.html`. En la CLI esa segunda plantilla se llama `confirmation`.
   Guardar ambas plantillas. `{{ .ConfirmationURL }}` permite volver a la APK0.3.2;
   `{{ .Token }}` añade la alternativa de ingresar el código numérico. `signInWithOtp` usa la plantilla de correo configurada;
   su nombre no obliga al proveedor a enviar números en vez de un enlace.
   Ver [Email OTP](https://supabase.com/docs/guides/auth/auth-email-passwordless)
   y [variables de las plantillas](https://supabase.com/docs/guides/auth/auth-email-templates).
4. Configurar el vencimiento del Email OTP en 600 segundos y 6 dígitos, si la
   opción de longitud está disponible; ajustar el intervalo de envío y los límites
   de Auth para producción. Si se elige otro vencimiento, actualizar también el
   texto de las dos plantillas.
5. Mantener Site URL y Redirect URLs válidas. El esquema técnico existente de
   la app es `autoempleoia://auth/callback`; el ingreso por código no necesita
   abrir un enlace para confirmar la sesión.

El correo predeterminado de Supabase está limitado a miembros de la organización
del proyecto; la documentación consultada indica dos mensajes por hora y no
garantiza entrega. No sirve para probar libremente el registro de otras personas.
Con SMTP propio también hay límites del proveedor y de Supabase; comprobar
entrega real antes de considerar terminado el acceso.
[Restricciones oficiales](https://supabase.com/docs/guides/auth/auth-smtp).

El **remitente de acceso OTP** es una cuenta de servicio configurada por el dueño
de Trabajo YA para enviar códigos. Las **postulaciones** usan la cuenta Gmail
que cada usuario conecta mediante OAuth y requieren su autorización separada.
Configurar SMTP de acceso no conecta Gmail para postulaciones ni activa envíos
laborales; conectar Gmail tampoco configura los códigos de ingreso.

## Gmail para pruebas

Para unas pocas pruebas, el dueño de Trabajo YA puede usar su Gmail como
remitente de los códigos, sin comprar un dominio. Esta configuración se realiza
en Supabase; no requiere otra APK ni cambiar Render.

1. En tu Cuenta de Google, habilitar **Verificación en dos pasos**. Abrir
   [Contraseñas de aplicación](https://myaccount.google.com/apppasswords), crear
   una llamada **Trabajo YA** y copiar sus **16 caracteres**. La opción depende
   de la cuenta: puede no aparecer sin verificación en dos pasos, con Protección
   Avanzada, con verificación configurada solo con llaves de seguridad o en una
   cuenta de organización. Si no está disponible, elegir otro proveedor SMTP.
   [Ayuda oficial de Google](https://support.google.com/accounts/answer/185833?hl=es).
2. En Supabase, abrir **Authentication → Emails → SMTP Settings**, habilitar
   **Enable custom SMTP** y completar:

   | Campo | Valor |
   | --- | --- |
   | Sender email | Tu dirección Gmail completa |
   | Sender name | `Trabajo YA` |
   | Host | `smtp.gmail.com` |
   | Port | `465` — conexión SSL |
   | Username | La misma dirección Gmail del remitente |
   | Password | La contraseña de aplicación generada, pegada directamente en Supabase |

   Guardar la configuración. La contraseña de aplicación no se envía por chat
   ni se agrega al proyecto.
   [Parámetros SMTP oficiales](https://knowledge.workspace.google.com/admin/gmail/send-email-from-a-printer-scanner-or-app?hl=es).
3. Volver a **Email Templates**. En **Magic Link** y **Confirm signup**, abrir
   **Source**, colocar los cuerpos incluidos con `{{ .Token }}` y pulsar
   **Save** en cada plantilla.
4. En la APK real, solicitar un código para un correo propio y comprobar que
   llega y permite ingresar. Hasta completar esta prueba no hay entrega OTP
   confirmada. Gmail tiene límites; para más usuarios usar un servicio de correo
   transaccional adecuado.

## Alternativa avanzada sin SMTP

Supabase ofrece **Send Email Auth Hook** en los planes Free y Pro. Puede enviar
el OTP generado por Auth mediante la API de un proveedor de correo, en lugar de
SMTP; la app conserva `verifyOtp` y la verificación de identidad. Requiere
implementar el hook, comprobar la firma de sus solicitudes, guardar sus secretos
solo en el servidor y disponer de un remitente autorizado. Esta alternativa
**no está implementada en el proyecto**; no habilita códigos por sí sola ni evita
la necesidad de entregar el mensaje al usuario.
[Disponibilidad de Auth Hooks](https://supabase.com/docs/guides/auth/auth-hooks)
y [Send Email Hook](https://supabase.com/docs/guides/auth/auth-hooks/send-email-hook).

## Comprobación manual pendiente con el proveedor

Con `EXPO_PUBLIC_DEMO_MODE=false`, probar un correo nuevo: solicitar código,
ingresar uno incorrecto y confirmar que no hay sesión; ingresar el código válido
y verificar la cuenta/perfil. Cerrar sesión y repetir con la misma dirección:
debe recuperar el mismo usuario. Comprobar vencimiento, reenvío después del
intervalo y un código ya utilizado. Repetir con otra cuenta y confirmar aislamiento
de CV, búsquedas y postulaciones.

La solicitud de código solo confirma que Auth aceptó la operación; no acredita
que el mensaje ya llegó al buzón. La demostración no envía códigos ni crea cuentas
en Supabase. Vincular Gmail para postulaciones es una operación OAuth independiente
del acceso a Trabajo YA y requiere su propia autorización de envío.
