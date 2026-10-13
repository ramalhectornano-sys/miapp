# Google OAuth y certificado Android

## Identificador exacto

El nombre visible es **Trabajo YA**. El identificador Android existente,
conservado por compatibilidad con el proyecto AutoEmpleo IA, es:

```text
com.trabajoya.autoempleoia
```

Está definido en `mobile/app.json` como `expo.android.package`. Expo lo usa
como `applicationId` al generar Android; `app.config.js` y los perfiles EAS
no lo sobrescriben.

## Cliente Google necesario para la implementación actual

Crear un cliente OAuth de tipo **Aplicación web** para el backend. La app abre
la autorización en el navegador; FastAPI recibe el código y lo intercambia
por tokens que guarda cifrados. Ese flujo no usa un cliente OAuth Android ni
una huella SHA-1. El ingreso a Trabajo YA usa Email OTP de Supabase y es independiente.

En Google Cloud habilitar **Gmail API**, configurar la pantalla de consentimiento
y, si está en Testing, agregar las cuentas de prueba. El backend solicita:

- `https://www.googleapis.com/auth/gmail.send`
- `https://www.googleapis.com/auth/userinfo.email`
- `openid`

En **URIs de redireccionamiento autorizados**, registrar la URL real exacta:

```text
https://<dominio-publico-del-backend>/api/mail/google/callback
```

Sustituir el marcador por el dominio configurado en Caddy. El proyecto todavía
no tiene un dominio desplegado; la URL anterior es un formato, no una dirección activa.
Para pruebas en Google Cloud se puede usar directamente el HTTPS `run.app` que
entrega el despliegue; no hace falta comprar un dominio. Seguir la
[guía desde el celular](../deploy/google-cloud/README.md).
En el servidor completar `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` y
`GOOGLE_REDIRECT_URI`. La última variable debe ser idéntica a la URI registrada,
incluidos HTTPS, host y ruta. El secreto del cliente web no se incluye en Android.

Para desarrollo únicamente, existe el ejemplo
`http://localhost:8000/api/mail/google/callback`; no reemplaza la URL pública
del servidor en la nube. El esquema `autoempleoia://auth/callback` corresponde
al proyecto móvil/Supabase y no es el callback Google de este backend.

Los refresh tokens de una aplicación Google externa en Testing con estos scopes
pueden vencer a los siete días; prever reconexión durante pruebas y completar
los requisitos de publicación que indique Google para automatización permanente.

## Certificado de la APK de prueba y SHA-1

No existe un keystore de firma de esta APK en el proyecto y todavía no se generó
la APK ni se vinculó EAS. Por eso no hay una SHA-1 concreta que pueda registrarse
como la firma de la APK de prueba. La huella depende del certificado, no del
nombre del paquete ni del código fuente.

La ruta preparada usa credenciales de firma administradas por **Expo EAS**.
Preparar Expo siguiendo [ANDROID_BUILD](ANDROID_BUILD.md), y desde `mobile`:

```bash
eas credentials -p android
```

Seleccionar el perfil **`preview-real`** y, en la administración de credenciales
Android, crear/configurar un keystore si todavía no hay uno. Conservar ese
keystore asociado al mismo perfil al compilar. Consultar la **SHA1 Fingerprint**
del certificado en EAS; para un cliente OAuth Android, registrar esa huella junto
con `com.trabajoya.autoempleoia`. Esto no requiere compilar previamente una APK.

Si se descarga el keystore desde EAS, anotar su alias y consultar localmente:

```bash
keytool -list -v -keystore ./firma-prueba.jks -alias ALIAS_DEL_CERTIFICADO
```

`keytool` solicita la contraseña. Copiar la línea **SHA1**, conservando todos
los pares hexadecimales separados por `:`. No copiar SHA256 en un campo SHA-1.
El proyecto también incluye el helper, desde la raíz:

```bash
bash scripts/android_certificate_sha1.sh --keystore ./firma-prueba.jks ALIAS_DEL_CERTIFICADO
```

Si se dispone solo del certificado público exportado `.pem` o `.der`:

```bash
bash scripts/android_certificate_sha1.sh --certificate ./certificado-publico.pem
```

Una vez compilada la APK, confirmar la huella del archivo que se instalará con
Android SDK Build Tools:

```bash
apksigner verify --print-certs ./trabajo-ya.apk
```

Comparar **Signer #1 certificate SHA-1 digest** con la de EAS. Si se firma con
otro certificado, registrar la huella de ese certificado, no la anterior.

Para este flujo backend web, la huella no es un requisito para conectar Gmail.
Un cliente OAuth Android se necesita si más adelante se implementa autenticación
nativa de Google. En ese caso distinguir la firma de la APK EAS, la firma debug
de una compilación local y la firma de distribución de Google Play. Con Play App
Signing, consultar el certificado de firma de la aplicación en Play Console;
su huella puede diferir de la clave de carga.

Guardar keystore, contraseñas y `credentials.json` fuera del repositorio y de
los ZIP de código. El certificado público y su huella sí pueden compartirse.
