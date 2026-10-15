// Public vacancy and audit links open only after a tap. Refuse local addresses,
// credentials and OAuth links even when a remote source supplies them.
export function publicOfferUrl(value: string | null | undefined): string | null {
  if (!value || value.length > 4096 || !/^https:\/\//i.test(value) || /[\s\u0000-\u001f\u007f\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (!host || host.length > 253 || host.includes(':') || /^[\d.]+$/.test(host)) return null;
    const labels = host.split('.');
    if (labels.length < 2 || labels.some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) return null;
    if (labels.some(label => label === 'localhost') || /\.(?:local|internal|localhost|localdomain|lan|home|intranet|invalid|test|example|onion|arpa|alt)$/.test(host)) return null;
    const secrets = /^(?:access_token|refresh_token|id_token|client_secret|api_key|apikey|authorization|password|token)$/i;
    if ([...url.searchParams.keys()].some(key => secrets.test(key))) return null;
    if (/(?:^|[&#])(?:access_token|refresh_token|id_token|client_secret|api_key|authorization|token)=/i.test(url.hash)) return null;
    return url.href;
  } catch { return null; }
}
