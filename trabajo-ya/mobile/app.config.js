// The existing app.json remains the source of the name, logo and Android package.
// EAS evaluates this file locally and in the remote build environment.
function publicHttpsUrl(name, value) {
  let url;
  try { url = new URL((value || '').trim()); }
  catch { throw new Error(`Falta ${name} o su URL no es válida. Configurá las variables públicas del entorno EAS.`); }
  const hostname = url.hostname.toLowerCase();
  const ipv6 = hostname.startsWith('[') ? hostname.slice(1, -1) : '';
  const localIpv6 = ipv6 === '::' || ipv6 === '::1' || /^(fc|fd|fe[89ab])/.test(ipv6);
  const ipv4 = hostname.split('.').map(Number);
  const localIpv4 = ipv4.length === 4 && ipv4.every(Number.isInteger) && (
    ipv4[0] === 0 || ipv4[0] === 10 || ipv4[0] === 127 ||
    (ipv4[0] === 172 && ipv4[1] >= 16 && ipv4[1] <= 31) ||
    (ipv4[0] === 192 && ipv4[1] === 168)
  );
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || url.search ||
      localIpv4 || localIpv6 || hostname === 'localhost' ||
      hostname.endsWith('.localhost') || hostname.endsWith('.local') ||
      hostname.endsWith('.example') || hostname === 'example' ||
      /(^|\.)(example\.(com|org|net)|invalid|test)$/.test(hostname)) {
    throw new Error(`${name} debe apuntar al servicio real mediante HTTPS público, sin credenciales en la URL.`);
  }
}

function validateRealBuild(env) {
  if (env.EXPO_PUBLIC_DEMO_MODE !== 'false') {
    throw new Error('La compilación real requiere EXPO_PUBLIC_DEMO_MODE=false. No se generará un APK de demostración con este perfil.');
  }
  publicHttpsUrl('EXPO_PUBLIC_BACKEND_URL', env.EXPO_PUBLIC_BACKEND_URL);
  publicHttpsUrl('EXPO_PUBLIC_SUPABASE_URL', env.EXPO_PUBLIC_SUPABASE_URL);
  const key = env.EXPO_PUBLIC_SUPABASE_ANON_KEY?.trim() || env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim() || '';
  if (key.startsWith('sb_publishable_') && key.length > 24) return;
  if (key.startsWith('sb_secret_')) {
    throw new Error('La app solo admite la clave pública de Supabase; nunca sb_secret ni service_role.');
  }
  try {
    const pieces = key.split('.');
    if (pieces.length === 3) {
      const payload = JSON.parse(Buffer.from(pieces[1], 'base64url').toString('utf8'));
      if (payload.role === 'anon') return;
    }
  } catch { /* Report only the variable name; never include the supplied key. */ }
  throw new Error('Falta una clave pública válida de Supabase: EXPO_PUBLIC_SUPABASE_ANON_KEY (anon) o EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY.');
}

module.exports = ({ config }) => {
  if (process.env.TRABAJO_YA_BUILD_MODE === 'real' ||
      ['preview-real', 'production'].includes(process.env.EAS_BUILD_PROFILE)) {
    validateRealBuild(process.env);
  }
  return config;
};
module.exports.validateRealBuild = validateRealBuild;
