# Conectar la IA real de Trabajo YA

El proveedor preparado es **Groq**, con el modelo de pesos abiertos
**`openai/gpt-oss-20b`**. El chat interpreta instrucciones laborales y produce una
propuesta validada por el servidor; el modelo no concede permisos ni ejecuta
búsquedas o correos. Las configuraciones se guardan cuando el usuario las confirma.

La integración está implementada. En este entorno no existe una clave privada
del proveedor ni un backend cloud accesible, por lo que todavía no se confirmó
una inferencia real. Configurar un nombre de modelo no acredita conexión.

## Tu cuenta y la clave

1. Crear o abrir una cuenta en [Groq Console](https://console.groq.com/).
2. En [API Keys](https://console.groq.com/keys), generar una clave del proyecto.
3. Guardarla en un gestor propio. Cargarla mediante entrada oculta del comando
   de activación o como secreto del servidor; no escribirla en el código,
   variables `EXPO_PUBLIC_*`, mensajes de chat ni argumentos del terminal.

El plan Free tiene cuotas. Verificar el modelo disponible y los límites de la
cuenta antes de probar con varios usuarios. El preset evita IDs de Llama que ya
no están disponibles para Free/Developer. Las condiciones pueden cambiar:
[modelos](https://console.groq.com/docs/models),
[límites](https://console.groq.com/docs/rate-limits) y
[deprecaciones](https://console.groq.com/docs/deprecations).

## Activación desde Cloud Shell

Primero preparar Supabase, el proyecto Google y la configuración del servidor
siguiendo [EMPEZAR](../EMPEZAR.md). Desde la raíz del proyecto ejecutar:

```bash
python3 deploy/google-cloud/cloud.py activate-ai
```

El comando usa este preset público:

```text
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://api.groq.com/openai/v1
AI_MODEL=openai/gpt-oss-20b
```

La clave se guarda como `AI_API_KEY` en Secret Manager. No se incluye en
`cloud-config.json` ni se copia a Android. Las claves y tokens anteriores se
conservan. La activación prepara el secreto, despliega la configuración nueva y
ejecuta una prueba del proveedor. Requiere facturación/permisos Google y puede
consumir cuotas de build, job y Groq; no garantiza coste total cero.

Como toda actualización del servidor, deja los envíos deshabilitados y pausa
un programador activo. La IA no activa automáticamente las postulaciones.
Reanudar tareas y correo requiere las comprobaciones y permisos de la
[guía de despliegue](../deploy/google-cloud/README.md).

Para repetir únicamente la comprobación de IA desplegada:

```bash
python3 deploy/google-cloud/cloud.py test-ai
```

La prueba usa una instrucción sintética de chofer en Rincón de los Sauces, diaria
a las 09:00, sin CV ni datos personales. El job solo recibe la configuración de
IA y la versión de su clave fijada en la API. No consulta Supabase, no busca
vacantes ni contacta Gmail. Solo informa éxito si el proveedor responde y se
valida una propuesta correcta. Una clave ausente, un rechazo, cuota agotada,
respuesta incompleta o JSON inválido producen un error sin imprimir el secreto
ni el texto del proveedor. No se reemplaza ese fallo por una respuesta demo.

## Si usás un servidor propio

Instalar las dependencias del backend y cargar las variables anteriores junto
con `AI_API_KEY` en `backend/.env`, que está excluido de Git. Después ejecutar:

```bash
cd backend
python -m app.check_ai
```

El comando imprime `verified: true` únicamente tras una llamada válida; en caso
de error imprime `verified: false` y termina con código 1. No valida todavía el
acceso desde Android: después hay que probar el chat desde una cuenta de la app
conectada al backend real.

## Adaptación del modelo

Se usa JSON Object Mode, salida limitada a 4096 tokens y razonamiento bajo,
sin incluir razonamiento en la respuesta. El backend aplica Pydantic al resultado
y conserva sus controles de autorización. Ollama y otros proveedores compatibles
continúan disponibles como alternativas configurables.
[JSON](https://console.groq.com/docs/structured-outputs) y
[parámetros de razonamiento](https://console.groq.com/docs/reasoning).
