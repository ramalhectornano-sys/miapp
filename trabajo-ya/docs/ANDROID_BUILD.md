# Compilar Trabajo YA para Android

Ya podés [descargar la APK de demostración Trabajo YA 0.3.0](https://github.com/ramalhectornano-sys/miapp/releases/download/trabajo-ya-v0.3.0-demo/Trabajo-YA-0.3.0-demo.apk).
Se compiló y publicó desde GitHub Actions; es autónoma, usa firma debug y no
requiere Expo Go ni una cuenta Expo para instalarla. No conecta IA, usuarios o
correo reales. La [guía de instalación](APK_GITHUB.md) explica sus límites.

Las instrucciones EAS siguientes sirven para nuevas compilaciones y para el
modo real. Este requiere Supabase y el backend desplegado con HTTPS público;
el APK usa esos servicios y no contiene el servidor, la IA ni las tareas
programadas. Todavía no se generó una APK conectada ni un AAB de producción.

## Artefactos y perfiles

| Perfil EAS | Archivo | Uso | Modo |
| --- | --- | --- | --- |
| `development` | APK con development client | Desarrollo con Metro | Demo |
| `demo` o `preview` | APK | Explorar interfaces sin servicios | Demo |
| `preview-real` | APK | Instalar y probar los servicios reales | Real |
| `production` | AAB | Subir a Google Play cuando esté validado | Real |

El perfil `preview` existente sigue siendo demostración. Para el APK conectado
hay que usar **`preview-real`**. Un AAB no se instala directamente como un APK.
Crear un AAB no publica la app ni confirma que pasó la revisión de Google Play.

## Preparar Expo/EAS

En una computadora con acceso a npm, o en Cloud Shell desde el celular:

```bash
cd mobile
npm install
npm install --global eas-cli
eas login
eas init
```

Crear una cuenta en [Expo](https://expo.dev/signup) si todavía no existe. `eas
init` vincula el proyecto y agrega su identificador a la configuración de Expo;
conservar el nombre, icono y paquete Android actuales. EAS solicitará la clave
de firma Android durante la primera compilación. Se puede dejar que EAS la
administre; guardar el acceso a la cuenta y los respaldos de firma.

Como existe una configuración dinámica `app.config.js`, `eas init` puede pedir
que se agregue manualmente `extra.eas.projectId`. Usar el UUID público del proyecto
que muestra Expo y agregarlo a `expo.extra.eas.projectId` en `app.json`, conservando
nombre, iconos, paquete y demás campos. No usar el ID de Google Cloud en ese campo.
Después volver a ejecutar `eas init` para comprobar la vinculación.

El `applicationId` es **`com.trabajoya.autoempleoia`**. Para obtener la SHA-1
del certificado elegido en EAS y configurar Google, seguir
[OAuth y certificado Android](GOOGLE_OAUTH_ANDROID.md). El flujo de Gmail actual
necesita un cliente OAuth web para el backend; no exige un cliente Android.

## Variables públicas del entorno real

Cuando Supabase y el backend ya estén desplegados, crear estas tres variables
en **EAS → Environment variables → preview**, con visibilidad *Plain text*:

| Variable | Valor |
| --- | --- |
| `EXPO_PUBLIC_BACKEND_URL` | URL HTTPS pública del backend |
| `EXPO_PUBLIC_SUPABASE_URL` | URL HTTPS del proyecto Supabase |
| `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Clave pública `sb_publishable_…` |

Como alternativa a la última variable se admite `EXPO_PUBLIC_SUPABASE_ANON_KEY`
con la clave JWT de rol `anon`. Usar una sola opción; una `ANON_KEY` vacía no
impide usar la clave `publishable`.
El backend usa las claves privadas, credenciales de IA, OAuth y cifrado. Nunca
agregarlas a variables `EXPO_PUBLIC_*`: esos valores quedan dentro del APK.

También se pueden crear desde EAS CLI, sin poner los valores en el historial:

```bash
eas env:create --environment preview --name EXPO_PUBLIC_BACKEND_URL --visibility plaintext
eas env:create --environment preview --name EXPO_PUBLIC_SUPABASE_URL --visibility plaintext
eas env:create --environment preview --name EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY --visibility plaintext
eas env:pull --environment preview
```

Responder a los valores solicitados. `env:pull` guarda la configuración local
en `.env.local`, que está excluida de Git. Las variables elegidas en `eas.json`
fijan `EXPO_PUBLIC_DEMO_MODE=false` para los perfiles reales. No hace falta
agregar este valor al panel EAS.

`mobile/app.config.js` rechaza una compilación real sin URLs HTTPS públicas,
sin clave pública o con una clave privada de Supabase. El guard se ejecuta
también en EAS; validar la configuración local no reemplaza configurar el
entorno remoto. Este control no confirma que las credenciales tengan permisos
ni que los servicios respondan.

## Compilar el APK real

Desde la raíz del repositorio:

```bash
scripts/build_android.sh preview-real --check
scripts/build_android.sh preview-real --cloud
```

El primer comando valida las variables locales sin usar la red. El segundo
inicia el build en EAS y muestra el enlace de descarga cuando termina. El script
usa `--check` por defecto; ejecutarlo solo no genera una compilación.

Después de instalar el APK, comprobar acceso por código de correo, perfil,
carga y descarga privada de CV, conversación con la IA, búsquedas programadas,
conexión OAuth, permiso de envío y confirmación del proveedor en el historial.
Los envíos deben probarse primero con un destinatario de prueba autorizado;
no activar envíos a empresas hasta completar esas verificaciones. Comprobar
también que el servidor siga funcionando al cerrar o apagar el teléfono.

## Preparar el AAB

Después de validar el APK, repetir las variables públicas en el entorno EAS
**production**, descargar ese entorno y compilar:

```bash
cd mobile
eas env:pull --environment production
cd ..
scripts/build_android.sh production --check
scripts/build_android.sh production --cloud
```

Antes de una siguiente publicación, incrementar `expo.version` y
`expo.android.versionCode` en `mobile/app.json`. El perfil conserva la versión
local para que esos valores coincidan con la entrega.

Para compilar sin EAS cloud, instalar un **JDK completo**, Android SDK y las
herramientas requeridas por Expo/EAS; después usar `--local`. Tener solo el
runtime `java` no alcanza. La compilación cloud no requiere Android SDK local.

## Estado comprobado

La [ejecución de GitHub Actions](https://github.com/ramalhectornano-sys/miapp/actions/runs/38427300341)
aprobó TypeScript, las 18 pruebas de lógica móvil, Expo prebuild y
`assembleRelease`. `apksigner` verificó la firma y `aapt` confirmó el nombre,
paquete y versión antes de publicar la APK demo. No se usó EAS para esa
compilación. No se ejecutó un emulador ni una prueba en dispositivo físico,
y no se generó un AAB ni se validaron servicios reales desde Android.
