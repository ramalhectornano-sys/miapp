/** Email callbacks are consumed only through Supabase's PKCE exchange. */
export const AUTH_CALLBACK_URL = 'autoempleoia://auth/callback';
export const AUTH_LINK_ERROR = 'No pudimos verificar el enlace. Solicitá un correo nuevo desde esta app y abrilo en este mismo celular.';
export const AUTH_LINK_EXPIRED = 'El enlace venció o ya fue utilizado. Solicitá un correo nuevo desde la aplicación.';

type LinkSession = { access_token: string; refresh_token: string; user: { id: string } };
type AuthAdapter<S> = { exchangeCodeForSession: (code: string) => Promise<{ data: { session: S | null }; error: unknown }> };
export type AuthLinkHandler<S> = { handle: (url: string) => Promise<S | null> };

function codeFromCallback(raw: string): string | null {
  if (typeof raw !== 'string' || raw.length > 8192 || /[\x00-\x20\x7f]/.test(raw)) return null;
  let url: URL;
  try { url = new URL(raw); } catch { return null; }
  if (url.protocol !== 'autoempleoia:' || url.hostname !== 'auth' || url.pathname !== '/callback'
      || url.username || url.password || url.port) return null;
  const parameters = new Map<string, string>();
  for (const source of [url.searchParams, new URLSearchParams(url.hash.slice(1))]) {
    for (const [key, value] of source.entries()) {
      if (parameters.has(key)) throw new Error(AUTH_LINK_ERROR);
      parameters.set(key, value);
    }
  }
  if (parameters.has('error') || parameters.has('error_code') || parameters.has('error_description')) {
    throw new Error(parameters.get('error_code') === 'otp_expired' ? AUTH_LINK_EXPIRED : AUTH_LINK_ERROR);
  }
  // Older implicit links and direct token-hash links bypass the local verifier.
  // Request a fresh PKCE link instead of accepting credentials from an arbitrary URL.
  if (['access_token', 'refresh_token', 'token_hash'].some(key => parameters.has(key))) throw new Error(AUTH_LINK_ERROR);
  const code = url.searchParams.get('code');
  if (!code || !/^[A-Za-z0-9._~-]{4,2048}$/.test(code)) throw new Error(AUTH_LINK_ERROR);
  return code;
}

export function createAuthLinkHandler<S extends LinkSession>(adapter: AuthAdapter<S>): AuthLinkHandler<S> {
  const seen = new Map<string, { at: number; pending?: Promise<S | null> }>();
  return {
    handle(raw) {
      let code: string | null;
      try { code = codeFromCallback(raw); } catch (error) { return Promise.reject(error); }
      if (!code) return Promise.resolve(null);
      const now = Date.now();
      for (const [key, value] of seen) if (!value.pending && now - value.at > 300_000) seen.delete(key);
      const previous = seen.get(code);
      if (previous) return previous.pending ?? Promise.resolve(null);
      if (seen.size >= 32) return Promise.reject(new Error(AUTH_LINK_ERROR));
      const entry: { at: number; pending?: Promise<S | null> } = { at: now };
      const exchange = Promise.resolve().then(async () => {
        try {
          const { data, error } = await adapter.exchangeCodeForSession(code!);
          const session = data?.session;
          if (error || typeof session?.user?.id !== 'string' || !session.user.id
              || typeof session.access_token !== 'string' || !session.access_token
              || typeof session.refresh_token !== 'string' || !session.refresh_token) throw new Error(AUTH_LINK_ERROR);
          return session;
        } catch { throw new Error(AUTH_LINK_ERROR); }
        finally { delete entry.pending; }
      });
      entry.pending = exchange;
      seen.set(code, entry);
      return exchange;
    },
  };
}

type LinkEvents = {
  addEventListener: (event: 'url', callback: (event: { url: string }) => void) => { remove: () => void };
  getInitialURL: () => Promise<string | null>;
};

/** Subscribe before reading the cold-start URL; stop UI updates on unmount. */
export function observeAuthLinkEvents<S>(links: LinkEvents, handler: AuthLinkHandler<S>,
  onSuccess: (session: S) => void, onError: (message: string) => void): () => void {
  let active = true;
  const consume = (url: string) => {
    if (!active) return;
    void handler.handle(url).then(session => { if (active && session) onSuccess(session); })
      .catch(error => { if (active) onError(error instanceof Error && error.message === AUTH_LINK_EXPIRED ? AUTH_LINK_EXPIRED : AUTH_LINK_ERROR); });
  };
  const subscription = links.addEventListener('url', ({ url }) => consume(url));
  void links.getInitialURL().then(url => { if (active && url) consume(url); })
    .catch(() => { if (active) onError(AUTH_LINK_ERROR); });
  return () => { active = false; subscription.remove(); };
}
