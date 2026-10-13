# Acceso sin contraseña

Trabajo YA crea la cuenta o inicia sesión con un código de un solo uso enviado al
correo del usuario. El nombre completo es opcional al ingresar y se completa en
Mi perfil. No se guarda una contraseña ni se permite entrar con un correo que no
haya sido verificado.

La aplicación solicita el código con `signInWithOtp`, `shouldCreateUser: true` y,
si se indicó, `data.full_name`. Después usa `verifyOtp` con `type: 'email'` y solo
considera al usuario autenticado cuando Supabase devuelve una sesión válida. La
sesión se guarda con SecureStore en Android. El campo acepta entre 6 y 8 dígitos
para soportar diferentes configuraciones del proveedor; este proyecto configura
6 dígitos, vencimiento de 10 minutos y un intervalo mínimo de 60 segundos entre
solicitudes de código.

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

## Proyecto Supabase remoto

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
   Guardar ambas plantillas. No dejar solo `{{ .ConfirmationURL }}`: la aplicación
   espera un código. `signInWithOtp` usa la plantilla de correo configurada;
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
