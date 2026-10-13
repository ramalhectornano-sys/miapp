#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Uso: scripts/android_certificate_sha1.sh --keystore archivo.jks alias' \
    '     scripts/android_certificate_sha1.sh --certificate certificado.pem' \
    'Muestra las huellas del certificado. La contraseña se pide por keytool; no se pasa como argumento.' >&2
}

if ! command -v keytool >/dev/null 2>&1; then
  printf '%s\n' 'Falta keytool. Instalá un JDK para consultar el certificado de firma Android.' >&2
  exit 1
fi

case "${1:-}" in
  --keystore)
    if [[ "$#" != 3 || ! -f "$2" || -z "$3" ]]; then usage; exit 2; fi
    exec keytool -J-Duser.language=en -J-Duser.country=US -list -v -keystore "$2" -alias "$3"
    ;;
  --certificate)
    if [[ "$#" != 2 || ! -f "$2" ]]; then usage; exit 2; fi
    exec keytool -J-Duser.language=en -J-Duser.country=US -printcert -file "$2"
    ;;
  *) usage; exit 2 ;;
esac
