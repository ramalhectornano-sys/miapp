/** Passwordless authentication boundary, independent of React Native for testing. */
export const EMAIL_REQUEST_ERROR = 'No pudimos enviar el código. Esperá un minuto y volvé a intentarlo.';
export const EMAIL_VERIFY_ERROR = 'No pudimos verificar el código. Revisalo o solicitá uno nuevo.';

export function normalizeEmail(email: string): string { return email.trim(); }
export function isValidEmail(email: string): boolean { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizeEmail(email)); }
export function isValidEmailCode(token: string): boolean { return /^[0-9]{6,8}$/.test(token.trim()); }

interface EmailAuthAdapter<Session> {
  signInWithOtp: (credentials: { email: string; options: { shouldCreateUser: true; data?: { full_name: string } } }) => Promise<{ error: unknown }>;
  verifyOtp: (credentials: { email: string; token: string; type: 'email' }) => Promise<{ data: { session: Session | null }; error: unknown }>;
}

export function createEmailAuth<Session>(auth: EmailAuthAdapter<Session>) {
  return {
    async requestEmailCode(email: string, fullName = ''): Promise<void> {
      const normalizedEmail = normalizeEmail(email);
      if (!isValidEmail(normalizedEmail)) throw new Error('Ingresá un correo electrónico válido.');
      const name = fullName.trim();
      try {
        const { error } = await auth.signInWithOtp({
          email: normalizedEmail,
          options: { shouldCreateUser: true, ...(name ? { data: { full_name: name } } : {}) },
        });
        if (error) throw error;
      } catch { throw new Error(EMAIL_REQUEST_ERROR); }
    },
    async verifyEmailCode(email: string, token: string): Promise<Session> {
      if (!isValidEmail(email) || !isValidEmailCode(token)) throw new Error(EMAIL_VERIFY_ERROR);
      try {
        const { data, error } = await auth.verifyOtp({ email: normalizeEmail(email), token: token.trim(), type: 'email' });
        if (error || !data.session) throw error ?? new Error('Missing session');
        return data.session;
      } catch { throw new Error(EMAIL_VERIFY_ERROR); }
    },
  };
}
