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

El archivo local no cambia las opciones de un proyecto alojado. En el Dashboard:

1. En Authentication, habilitar el proveedor Email y el registro de nuevas
   cuentas; mantener la confirmación del correo habilitada.
2. En Email Templates, editar **Magic Link** para mostrar `{{ .Token }}` y el
   texto de `magic_link.html`. Editar también **Confirm signup** con el contenido
   de `confirmation.html`. En la CLI esa segunda plantilla se llama `confirmation`.
   No dejar solo `{{ .ConfirmationURL }}`: la aplicación espera un código.
3. Configurar el vencimiento del Email OTP en 600 segundos y 6 dígitos, si la
   opción de longitud está disponible; ajustar el intervalo de envío y los límites
   de Auth para producción. Si se elige otro vencimiento, actualizar también el
   texto de las dos plantillas.
4. Conectar SMTP propio, validar el dominio remitente y comprobar entrega con
   cuentas de prueba. El correo integrado de desarrollo de Supabase tiene límites
   y puede restringir destinatarios; no es un servicio de envío para producción.
5. Mantener Site URL y Redirect URLs válidas. El esquema técnico existente de
   la app es `autoempleoia://auth/callback`; el ingreso por código no necesita
   abrir un enlace para confirmar la sesión.

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
