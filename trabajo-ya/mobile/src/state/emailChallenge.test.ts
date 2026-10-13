import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createEmailAuth, EMAIL_REQUEST_ERROR, EMAIL_VERIFY_ERROR, isValidEmailCode } from '../services/emailAuth.ts';
import { editEmailChallenge, emailCodeRequested, emailCodeWaitSeconds, emailVerificationCredentials, initialEmailChallenge } from './emailChallenge.ts';

test('solicitar un código permite crear cuenta y entrega a Supabase solo datos normalizados', async () => {
  const requests: unknown[] = [];
  const auth = createEmailAuth({
    signInWithOtp: async credentials => { requests.push(credentials); return { error: null }; },
    verifyOtp: async () => ({ data: { session: null }, error: null }),
  });
  await auth.requestEmailCode(' persona@ejemplo.com ', ' Ana López ');
  await auth.requestEmailCode('persona@ejemplo.com', '   ');
  assert.deepEqual(requests, [
    { email: 'persona@ejemplo.com', options: { shouldCreateUser: true, data: { full_name: 'Ana López' } } },
    { email: 'persona@ejemplo.com', options: { shouldCreateUser: true } },
  ]);
  await assert.rejects(auth.requestEmailCode('correo inválido'), /correo electrónico válido/);
  assert.equal(requests.length, 2);
});

test('solo verificar el código con el correo solicitado entrega una sesión', async () => {
  const session = { access_token: 'token-de-prueba' };
  const verifications: unknown[] = [];
  const auth = createEmailAuth({
    signInWithOtp: async () => ({ error: null }),
    verifyOtp: async credentials => { verifications.push(credentials); return { data: { session }, error: null }; },
  });
  const challenge = { ...emailCodeRequested(initialEmailChallenge(), ' persona@ejemplo.com ', 1000), email: 'otro@ejemplo.com', token: ' 12345678 ' };
  const credentials = emailVerificationCredentials(challenge)!;
  assert.strictEqual(await auth.verifyEmailCode(credentials.email, credentials.token), session);
  assert.deepEqual(verifications, [{ email: 'persona@ejemplo.com', token: '12345678', type: 'email' }]);
  await assert.rejects(auth.verifyEmailCode(credentials.email, '123abc'), { message: EMAIL_VERIFY_ERROR });
  assert.equal(verifications.length, 1);
});

test('resolicitar y cambiar correo eliminan el código previo y conservan la espera', () => {
  const original = { ...emailCodeRequested(initialEmailChallenge(), 'persona@ejemplo.com', 1000), token: '123456' };
  assert.equal(emailCodeWaitSeconds(original, 1000), 60);
  assert.equal(emailCodeWaitSeconds(original, 60_999), 1);
  assert.equal(emailCodeWaitSeconds(original, 61_000), 0);
  const editing = editEmailChallenge(original);
  assert.equal(emailVerificationCredentials(editing), null);
  assert.equal(editing.token, '');
  assert.equal(emailCodeWaitSeconds(editing, 1000), 60);
  const resent = emailCodeRequested(original, original.requestedEmail!, 61_000);
  assert.equal(resent.token, '');
  assert.equal(resent.resendAt, 121_000);
  assert.equal(emailVerificationCredentials(initialEmailChallenge()), null);
});

test('un error, una respuesta sin sesión o una excepción no conceden acceso ni exponen cuentas', async () => {
  for (const behavior of ['error', 'no-session', 'throw']) {
    const auth = createEmailAuth({
      signInWithOtp: async () => {
        if (behavior === 'throw') throw new Error('User already registered: persona@ejemplo.com');
        return { error: new Error('account-detail') };
      },
      verifyOtp: async () => {
        if (behavior === 'throw') throw new Error('provider-detail');
        return { data: { session: null }, error: behavior === 'error' ? new Error('account-detail') : null };
      },
    });
    await assert.rejects(auth.requestEmailCode('persona@ejemplo.com'), { message: EMAIL_REQUEST_ERROR });
    await assert.rejects(auth.verifyEmailCode('persona@ejemplo.com', '123456'), { message: EMAIL_VERIFY_ERROR });
  }
});

test('los códigos numéricos de seis a ocho dígitos preservan ceros iniciales', () => {
  for (const token of ['012345', '0123456', '01234567', ' 012345 ']) assert.equal(isValidEmailCode(token), true);
  for (const token of ['12345', '123456789', '12 3456', '12345A', '']) assert.equal(isValidEmailCode(token), false);
});
