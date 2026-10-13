#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="${1:-preview-real}"
action="${2:---check}"

case "$profile" in
  preview-real|production|demo|preview|development) ;;
  *) printf '%s\n' 'Perfil inválido: preview-real, production, demo, preview o development.' >&2; exit 2 ;;
esac
case "$action" in
  --check|--cloud|--local) ;;
  *) printf '%s\n' 'Uso: scripts/build_android.sh [perfil] [--check|--cloud|--local]' >&2; exit 2 ;;
esac
if ! command -v node >/dev/null 2>&1; then
  printf '%s\n' 'Falta Node.js 20.19.4 o posterior.' >&2
  exit 1
fi

# Read only public variables; never execute a .env file as a shell script.
# This is a local preflight. app.config.js repeats the guard on EAS remotely.
node - "$project_dir/mobile" "$profile" <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const mobileDir = process.argv[2];
const profileName = process.argv[3];
const loaded = {};
for (const filename of ['.env', '.env.local']) {
  const filepath = path.join(mobileDir, filename);
  if (!fs.existsSync(filepath)) continue;
  for (const line of fs.readFileSync(filepath, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?(EXPO_PUBLIC_[A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (!match) continue;
    let value = match[2];
    if (value.startsWith('"') || value.startsWith("'")) {
      const quote = value[0];
      const closing = value.indexOf(quote, 1);
      if (closing < 0) throw new Error(`Valor sin cerrar en ${filename}: ${match[1]}`);
      value = value.slice(1, closing);
    } else value = value.replace(/\s+#.*$/, '').trim();
    loaded[match[1]] = value;
  }
}
const profiles = JSON.parse(fs.readFileSync(path.join(mobileDir, 'eas.json'), 'utf8')).build;
function profileEnv(name, seen = new Set()) {
  if (seen.has(name) || !profiles[name]) throw new Error('Herencia EAS inválida.');
  seen.add(name);
  return { ...(profiles[name].extends ? profileEnv(profiles[name].extends, seen) : {}), ...profiles[name].env };
}
Object.assign(process.env, { ...loaded, ...process.env, ...profileEnv(profileName), EAS_BUILD_PROFILE: profileName });
const appConfig = require(path.join(mobileDir, 'app.config.js'));
const original = JSON.parse(fs.readFileSync(path.join(mobileDir, 'app.json'), 'utf8')).expo;
try { appConfig({ config: original }); }
catch (error) {
  console.error(error.message);
  process.exit(1);
}
console.log(`Configuración local válida para ${profileName}. No comprueba la disponibilidad de servicios ni genera un APK.`);
NODE

if [[ "$action" == '--check' ]]; then exit 0; fi
if ! command -v eas >/dev/null 2>&1; then
  printf '%s\n' 'Falta EAS CLI. Instalalo y conectá tu cuenta Expo según docs/ANDROID_BUILD.md.' >&2
  exit 1
fi
if [[ ! -d "$project_dir/mobile/node_modules" ]]; then
  printf '%s\n' 'Faltan dependencias del móvil. Ejecutá npm install dentro de mobile.' >&2
  exit 1
fi
if [[ "$action" == '--local' ]]; then
  if ! command -v javac >/dev/null 2>&1 || ! command -v adb >/dev/null 2>&1; then
    printf '%s\n' 'Falta JDK o Android SDK para compilar localmente. La compilación --cloud usa EAS.' >&2
    exit 1
  fi
fi
cd "$project_dir/mobile"
if [[ "$action" == '--local' ]]; then
  exec eas build --platform android --profile "$profile" --local
fi
exec eas build --platform android --profile "$profile"
