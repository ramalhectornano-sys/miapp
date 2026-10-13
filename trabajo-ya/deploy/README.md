# Puesta en marcha en un servidor en la nube

Para pruebas desde un celular con el cliente Google OAuth ya creado, la opción
recomendada es [Google Cloud Run + Jobs + Scheduler](google-cloud/README.md).
Esa alternativa aprovecha cuotas gratuitas, exige facturación y permite usar
HTTPS `run.app` sin comprar un dominio. El contenido siguiente describe la
alternativa de servidor Linux con Docker y Ollama propio.

Este directorio prepara un despliegue Docker Compose con HTTPS, API FastAPI,
worker independiente del celular y Ollama. No se desplegó en un servidor real.
Supabase alojado conserva la autenticación, base de datos y archivos privados.
El proyecto necesita cuentas propias y una fuente de vacantes autorizada.

## Qué crear primero

1. Una cuenta y proyecto en [Supabase](https://supabase.com/dashboard), con las
   cinco migraciones del directorio `supabase/migrations` aplicadas en orden.
   Configurar registro por código y SMTP con [AUTH_SETUP](../docs/AUTH_SETUP.md).
   Los correos de acceso de Trabajo YA y el Gmail de postulaciones tienen
   configuraciones independientes; conectar Gmail no configura SMTP de Supabase.
2. Un proyecto en [Google Cloud](https://console.cloud.google.com/), habilitar
   Gmail API, configurar la pantalla de consentimiento y crear un cliente OAuth
   de tipo aplicación web. Registrar exactamente la URL HTTPS
   `https://<dominio-api>/api/mail/google/callback` como redirección autorizada.
   Para pruebas, agregar los correos como usuarios de prueba. La app solicita
   `gmail.send`, `userinfo.email` y `openid`; no necesita leer todo el buzón.
   En modo Testing externo, los refresh tokens pueden vencer a los siete días,
   por lo que ese modo no sirve para automatización permanente sin reconectar.
   Antes de abrir el producto al público, completar los requisitos de publicación
   y verificación que indique Google para el proyecto.
3. Una cuenta en [Expo](https://expo.dev/signup), para la compilación Android
   con EAS. Ver [ANDROID_BUILD](../docs/ANDROID_BUILD.md).
4. Un servidor Linux con Docker Engine y Compose v2, un dominio y DNS que apunte
   al servidor. Para empezar con Qwen 2.5 de 7B en CPU, reservar aproximadamente
   16 GB de RAM y espacio libre para el modelo y las imágenes; medir latencia y
   concurrencia antes de usarlo con varios usuarios. El modelo es configurable.
   El servidor y el dominio se contratan en una cuenta del propietario; no se
   seleccionó proveedor, precio ni se realizó una compra.
5. Una integración de vacantes que autorice consultas y postulaciones por correo.
   El feed JSON debe cumplir el contrato de [backend](../backend/README.md).
   No se incluye un portal habilitado por defecto: sin una fuente autorizada,
   no se pueden afirmar búsquedas ejecutadas ni preparar envíos automáticos.

Las claves privadas se cargan en el servidor o en los secretos del entorno de
trabajo; no se envían en el chat ni se incluyen en el ZIP. La URL y clave pública
de Supabase sí se incluyen en la app, protegidas por las políticas de la base.

## Instalar y arrancar

Copiar el proyecto al servidor. Abrir los puertos 80 y 443, mantener el acceso
SSH propio y configurar DNS. Ollama y la API solo se exponen a la red interna
de Compose; el acceso público pasa por HTTPS. No abrir 8000 ni 11434.

```bash
cd deploy
cp .env.example .env
chmod 600 .env
```

Completar `.env` con datos propios, incluido `API_DOMAIN`, `ACME_EMAIL`,
Supabase, el cliente OAuth y la URL de callback. Generar una clave Fernet con
la instalación Python del backend y guardarla como `TOKEN_ENCRYPTION_KEY`:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Conservar esa clave para poder descifrar las conexiones de correo tras reiniciar.
Mantener `MAIL_SEND_ENABLED=false` hasta la comprobación controlada. El feed JSON
de `AUTHORIZED_JOB_FEEDS` puede tenerse en una sola línea; usar comillas simples
al guardar todo el JSON en `.env` si contiene caracteres especiales para Compose.

Antes de arrancar, con Python 3.10 o posterior revisar la configuración pública
del móvil y las variables del servidor sin mostrarlas:

Crear `mobile/.env` a partir de su ejemplo y completar `EXPO_PUBLIC_DEMO_MODE=false`,
la URL HTTPS del backend y la URL/clave pública de Supabase. Si EAS descargó las
variables en `mobile/.env.local`, pasar ese archivo como `--mobile-env` y agregar
también el valor de modo real para esta comprobación; el perfil EAS lo fija al compilar.

```bash
python ../scripts/check_runtime.py --backend-env .env --mobile-env ../mobile/.env --mode real --profile production
```

El comprobador señala las cuentas/variables que faltan. No realiza solicitudes
de red ni acredita conexión, migraciones, entrega de correos o ejecución de tareas.

```bash
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --build
docker compose ps
curl --fail https://<dominio-api>/health
```

`model-init` descarga realmente el modelo antes de arrancar la API y el worker.
La primera descarga puede tardar; si falla, no inicia los servicios dependientes.
Las imágenes oficiales usan etiquetas mayores/actuales: antes de un despliegue
reproducible, registrar y fijar las versiones/digests que se hayan validado.
No imprimir `docker compose config` sin `--quiet`: mostraría secretos resueltos.

Un `/health` exitoso indica que la API responde y qué configuración conoce;
no confirma que Supabase, Gmail, un modelo o un feed estén operativos.

## Comprobar cada servicio

1. Configurar la app con `EXPO_PUBLIC_DEMO_MODE=false`, la URL HTTPS de la API
   y la URL/clave pública de Supabase. Crear un usuario mediante un código recibido
   en un correo propio; comprobar ingreso, perfil, CV privado y otra sesión.
2. Consultar al asistente y comprobar una respuesta `mode: live` de `/api/chat`
   con una propuesta válida. La propuesta requiere confirmación para guardarse;
   el modelo no concede permisos ni afirma haber ejecutado una búsqueda.
3. Vincular Gmail desde Mi perfil y comprobar que aparece la cuenta correcta.
4. Agregar una fuente con permiso real; ejecutar una búsqueda manual y comprobar
   la ejecución registrada y sus resultados. Configurar una búsqueda diaria.
5. Para probar correo, usar una vacante de prueba propia con destinatario
   autorizado, activar `MAIL_SEND_ENABLED=true`, recrear API/worker y aprobar
   expresamente esa postulación. Comprobar un ID de Gmail antes de mostrar enviado.
   Vincular una cuenta, activar la variable o reiniciar el worker no autoriza envíos.
6. Autorizar la búsqueda automática con CV, cuenta, fuentes y vencimiento. Si se
   desean recordatorios, aceptar la opción de 3 días. Verificar cupo global de
   10 intentos diarios, aislamiento entre usuarios y detención por destinatario.
   Para probar que el celular puede estar apagado, esperar una tarea programada
   real y revisar después el run y el comprobante del proveedor.

Actualizar una variable del servidor requiere recrear los contenedores:

```bash
docker compose --env-file .env up -d
```

API y worker deben mantenerse funcionando. Revisar logs sin divulgar tokens,
guardar la clave de cifrado y respaldar la base/archivos según el plan Supabase.
No se activa detección de respuestas por Gmail: por ahora se registran manualmente.
