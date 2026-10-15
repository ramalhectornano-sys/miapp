# Activar correos: qué muestran las capturas y cómo comprobarlo

Las capturas muestran un CV elegido, Gmail conectado y una fecha de vencimiento
válida. El botón estaba bloqueado porque la única fuente disponible era
**Búsqueda en Internet**: sus fragmentos no verifican un canal para recibir CV.
El aviso de envíos desactivados es otro requisito, necesario para ejecutar,
pero no para guardar una autorización con una fuente apta.

La versión **0.5.0** conserva la integración independiente incorporada en 0.4.1 con la
[API pública de Greenhouse](https://docs.greenhouse.io/job-board.html).
No convierte todos los hallazgos de Tavily en destinatarios verificados.

## Qué permite esta integración

Tavily descubre enlaces. Para enlaces oficiales reconocidos de Greenhouse, el
servidor consulta su API pública, comprueba publicación, puesto, ubicación y
empresa y busca una instrucción explícita para enviar el CV a un único correo.
Conserva la cita, identificador y momento de consulta. Nunca construye una
dirección ni toma un correo de soporte o privacidad como canal de postulación.
Se consulta otra vez inmediatamente antes de cada envío y de cada recordatorio.

Las ofertas que requieren formularios, las de otros portales y las que no tienen
ese canal permanecen para revisión. La existencia de esta fuente no garantiza
vacantes de chofer en una ciudad, ni la existencia o recepción del buzón. Gmail
confirma la aceptación del envío; eso tampoco confirma una contratación.

## Actualizar el servicio y guardar el permiso

1. Si ya están instaladas 001–006, aplicar **solo la migración 007** en Supabase
   para geografía e historial. No repetir el instalador inicial. Luego, en
   **Render → trabajo-ya-api → Manual Deploy → Deploy latest commit**, usar
   la rama **trabajo-ya-real** y esperar **Live**; `/health` debe identificar
   backend **0.5.0**. Se conservan documentos, sesiones y conexiones Gmail.
2. Conservar en **Environment** `WEB_SEARCH_PROVIDER=tavily` y la clave privada
   existente en `WEB_SEARCH_API_KEY`. Cambiar explícitamente
   `WEB_SEARCH_MAX_QUERIES=6` si seguía en 2. Greenhouse no necesita una clave adicional.
   `MAIL_SEND_ENABLED=false` permite revisar primero sin enviar.
3. Abrir la app actualizada y entrar en los permisos de la búsqueda. Debe aparecer
   **Ofertas verificadas de Greenhouse**. Elegirla junto al CV y Gmail, la fecha
   válida y la casilla de consentimiento. **Guardar autorización** registra
   únicamente el permiso; no confirma consultas ni entregas.
4. Ejecutar una búsqueda con los envíos desactivados y revisar **Ver ejecuciones**
   y **Ver ofertas encontradas**. Una oferta apta muestra el correo y su cita;
   las demás quedan para revisión. Cero ofertas aptas implica cero correos.

Si todavía aparece únicamente Búsqueda en Internet, el backend no está en esta
versión o no tiene el buscador configurado. El indicador de configuración de
`/health` no prueba que la clave funcione: se comprueba ejecutando la búsqueda.

## Prueba de envío y tareas programadas

Antes de activar la operación diaria hay que comprobar una entrega a un
destinatario de prueba propio o que haya aceptado la prueba. No usar una empresa
real como destinatario de ensayo. Esta entrega no realiza esa prueba por vos ni
marca un envío como confirmado.

Para una prueba controlada mediante una integración propia autorizada, el
servidor necesita un registro de prueba claramente identificado, con canal
certificado por esa fuente. Mantener desactivadas las autorizaciones automáticas
durante la prueba. Habilitar temporalmente `MAIL_SEND_ENABLED=true` **en Render**
y desplegar permite el envío manual expresamente aprobado. Revisar el mensaje,
CV y dirección antes de aprobar. Debe aparecer un identificador y fecha de
confirmación de Gmail en **Mis postulaciones**. Si no están, no repetir un intento
con resultado incierto.

Para ejecutar con el celular apagado, completar el
[programador de pruebas con GitHub Actions](WORKER_GITHUB.md). Render Free no
ejecuta por sí solo el worker continuo. GitHub necesita las mismas claves
privadas que Render, cargadas únicamente como **Actions Secrets**, y el mismo
ID público del cliente OAuth. No cambiar `TOKEN_ENCRYPTION_KEY`: tiene que
coincidir con la clave que cifró las conexiones ya guardadas.

Después de esa comprobación, mantener `MAIL_SEND_ENABLED=true` en Render y
configurar en **GitHub → Settings → Secrets and variables → Actions → Variables**
`MAIL_SEND_ENABLED=true` y `WORKER_ENABLED=true`. Registrar o renovar el permiso
de cada búsqueda y comprobar su historial. El programador gratuito puede
demorarse; no garantiza puntualidad exacta.

Se conserva el máximo compartido de **10 intentos diarios** por usuario, el CV
y la cuenta consentidos, y la espera mínima de **72 horas** para recordatorios
autorizados. Una respuesta de la IA, un permiso guardado o un workflow verde
no sustituyen una confirmación real de Gmail.
