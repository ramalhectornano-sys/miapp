import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomFillSync } from 'node:crypto';
import { createClient } from '@supabase/supabase-js';
import { AUTH_CALLBACK_URL, AUTH_LINK_ERROR, AUTH_LINK_EXPIRED, createAuthLinkHandler, observeAuthLinkEvents } from './authLinks.ts';
import { installPkceCrypto } from './pkceCrypto.ts';

const session = { access_token: 'offline-access', refresh_token: 'offline-refresh', user: { id: 'offline-user' } };
const fresh = () => {
  const calls: string[] = [];
  const handler = createAuthLinkHandler({ exchangeCodeForSession: async (code: string) => {
    calls.push(code); return { data: { session }, error: null };
  } });
  return { handler, calls };
};
const drain = () => new Promise<void>(resolve => setImmediate(resolve));

test('el callback exacto intercambia el código PKCE y requiere una sesión confirmada', async () => {
  const { handler, calls } = fresh();
  assert.strictEqual(await handler.handle(AUTH_CALLBACK_URL + '?code=pkce-code'), session);
  assert.deepEqual(calls, ['pkce-code']);
});

test('otros esquemas, hosts, rutas y credenciales URL no conceden acceso', async () => {
  const { handler, calls } = fresh();
  for (const url of ['https://auth/callback?code=pkce-code', 'autoempleoia://evil/callback?code=pkce-code',
    'autoempleoia://auth/callback/extra?code=pkce-code', 'autoempleoia://user@auth/callback?code=pkce-code',
    'autoempleoia://auth:8080/callback?code=pkce-code', 'autoempleoia://mail?connected=1', 'invalid']) {
    assert.equal(await handler.handle(url), null);
  }
  assert.equal(calls.length, 0);
});

test('errores de Supabase se muestran sin reutilizar credenciales ni revelar detalles', async () => {
  const { handler, calls } = fresh();
  await assert.rejects(handler.handle(AUTH_CALLBACK_URL + '#error=access_denied&error_description=PRIVATE_SECRET'), { message: AUTH_LINK_ERROR });
  await assert.rejects(handler.handle(AUTH_CALLBACK_URL + '?error_code=otp_expired&code=pkce-code'), { message: AUTH_LINK_EXPIRED });
  assert.equal(calls.length, 0);
});

test('parámetros repetidos o mezclados se rechazan antes de contactar Supabase', async () => {
  const { handler, calls } = fresh();
  for (const params of ['?code=code-one&code=code-two', '?code=code-one#code=code-two',
    '?code=code-one&token_hash=PRIVATE', '?code=code-one&access_token=PRIVATE', '?code=code-one&refresh_token=PRIVATE',
    '#code=code-one', '?code=', '?code=has%20space']) {
    await assert.rejects(handler.handle(AUTH_CALLBACK_URL + params), { message: AUTH_LINK_ERROR });
  }
  assert.equal(calls.length, 0);
});

test('enlaces antiguos con tokens implícitos exigen un correo nuevo generado por la app PKCE', async () => {
  const { handler, calls } = fresh();
  await assert.rejects(handler.handle(AUTH_CALLBACK_URL + '#access_token=PRIVATE&refresh_token=PRIVATE'), { message: AUTH_LINK_ERROR });
  assert.equal(calls.length, 0);
});

test('un error de transporte, un rechazo o una respuesta sin sesión válida no autentican', async () => {
  for (const behavior of ['throw', 'error', 'empty', 'malformed']) {
    const handler = createAuthLinkHandler({ exchangeCodeForSession: async () => {
      if (behavior === 'throw') throw new Error('PRIVATE_TRANSPORT_RESPONSE');
      return { data: { session: behavior === 'empty' ? null : behavior === 'malformed' ? { ...session, refresh_token: '' } : session },
        error: behavior === 'error' ? new Error('PRIVATE_PROVIDER_RESPONSE') : null };
    } });
    await assert.rejects(handler.handle(AUTH_CALLBACK_URL + '?code=code-one'), { message: AUTH_LINK_ERROR });
  }
});

test('apertura inicial y evento concurrentes consumen el código una sola vez', async () => {
  let finish!: (result: { data: { session: typeof session }; error: null }) => void;
  let calls = 0;
  const handler = createAuthLinkHandler({ exchangeCodeForSession: async () => {
    calls++; return new Promise<{ data: { session: typeof session }; error: null }>(resolve => { finish = resolve; });
  } });
  const first = handler.handle(AUTH_CALLBACK_URL + '?code=code-one');
  const second = handler.handle(AUTH_CALLBACK_URL + '?code=code-one');
  await drain();
  assert.equal(calls, 1);
  finish({ data: { session }, error: null });
  assert.strictEqual(await first, session);
  assert.strictEqual(await second, session);
  assert.equal(await handler.handle(AUTH_CALLBACK_URL + '?code=code-one'), null);
});

test('un nuevo correo puede verificarse sin reactivar la sesión con el enlace anterior', async () => {
  const { handler, calls } = fresh();
  await handler.handle(AUTH_CALLBACK_URL + '?code=code-one');
  await handler.handle(AUTH_CALLBACK_URL + '?code=code-two');
  assert.equal(await handler.handle(AUTH_CALLBACK_URL + '?code=code-one'), null);
  assert.deepEqual(calls, ['code-one', 'code-two']);
});

test('el observador suscribe eventos antes de leer la URL de inicio y deduplica ambos', async () => {
  const { handler, calls } = fresh();
  const order: string[] = [];
  let listener!: (event: { url: string }) => void;
  let removed = false;
  let success = 0;
  const url = AUTH_CALLBACK_URL + '?code=code-one';
  const stop = observeAuthLinkEvents({
    addEventListener: (_event, callback) => { order.push('subscribe'); listener = callback; return { remove: () => { removed = true; } }; },
    getInitialURL: async () => { order.push('initial'); listener({ url }); return url; },
  }, handler, () => { success++; }, error => assert.fail(error));
  await drain();
  assert.deepEqual(order, ['subscribe', 'initial']);
  assert.deepEqual(calls, ['code-one']);
  assert.ok(success > 0);
  stop();
  assert.equal(removed, true);
});

test('desmontar el observador evita actualizar la pantalla con un intercambio pendiente', async () => {
  let complete!: (value: typeof session) => void;
  const stop = observeAuthLinkEvents<typeof session>({ addEventListener: () => ({ remove() {} }), getInitialURL: async () => AUTH_CALLBACK_URL + '?code=code-one' },
    { handle: () => new Promise<typeof session | null>(resolve => { complete = resolve; }) }, () => assert.fail('UI after unmount'), () => assert.fail('error after unmount'));
  await drain();
  stop(); complete(session); await drain();
});

const sha256 = async (data: ArrayBuffer | ArrayBufferView) => {
  const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  const hash = createHash('sha256').update(bytes).digest();
  return hash.buffer.slice(hash.byteOffset, hash.byteOffset + hash.byteLength) as ArrayBuffer;
};

test('el puente nativo produce SHA-256 de PKCE y conserva crypto existente', async () => {
  const target: { crypto?: unknown; TextEncoder?: unknown } = {};
  installPkceCrypto(target, { randomValues: randomFillSync, sha256 });
  const crypto = target.crypto as { subtle: { digest: (algorithm: string, data: Uint8Array) => Promise<ArrayBuffer> } };
  const Encoder = target.TextEncoder as new () => { encode: (input: string) => Uint8Array };
  for (const text of ['Trabajo YA', 'Neuquén 🚚', '\ud800']) assert.deepEqual(new Encoder().encode(text), new TextEncoder().encode(text));
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'));
  assert.equal(Buffer.from(digest).toString('base64url'), 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
  await assert.rejects(crypto.subtle.digest('MD5', new Uint8Array()));
  installPkceCrypto(target, { randomValues: () => assert.fail('replace existing'), sha256: async () => assert.fail('replace existing') });
  assert.strictEqual(target.crypto, crypto);
});

test('el SDK real envía el redirect exacto y un challenge S256 sin enviar el verifier', async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {} });
  try {
    installPkceCrypto(globalThis, { randomValues: randomFillSync, sha256 });
    const storage = new Map<string, string>();
    let request: Record<string, unknown> | undefined;
    const client = createClient('https://project.supabase.co', 'public-offline-key', {
      auth: { flowType: 'pkce', autoRefreshToken: false, persistSession: true, detectSessionInUrl: false,
        storage: { getItem: async key => storage.get(key) ?? null, setItem: async (key, value) => { storage.set(key, value); }, removeItem: async key => { storage.delete(key); } } },
      global: { fetch: async (url, options) => {
        assert.equal(new URL(String(url)).searchParams.get('redirect_to'), AUTH_CALLBACK_URL);
        request = JSON.parse(String(options?.body));
        return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
      } },
    });
    const { error } = await client.auth.signInWithOtp({ email: 'persona@ejemplo.com', options: { emailRedirectTo: AUTH_CALLBACK_URL } });
    assert.equal(error, null);
    assert.equal(request?.code_challenge_method, 's256');
    const verifier = JSON.parse([...storage.entries()].find(([key]) => key.endsWith('-code-verifier'))![1]) as string;
    const expected = Buffer.from(await sha256(new TextEncoder().encode(verifier))).toString('base64url');
    assert.equal(request?.code_challenge, expected);
    assert.ok(!JSON.stringify(request).includes(verifier));
  } finally {
    if (original) Object.defineProperty(globalThis, 'crypto', original);
    else Reflect.deleteProperty(globalThis, 'crypto');
  }
});
