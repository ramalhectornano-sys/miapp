import { normalizeEmail } from '../services/emailAuth.ts';

export const EMAIL_CODE_COOLDOWN_MS = 60_000;
export interface EmailChallenge {
  email: string;
  name: string;
  token: string;
  requestedEmail: string | null;
  resendAt: number;
}
export const initialEmailChallenge = (): EmailChallenge => ({ email: '', name: '', token: '', requestedEmail: null, resendAt: 0 });

/** Bind verification to the address that received the code, not an editable field. */
export function emailCodeRequested(state: EmailChallenge, email: string, now: number): EmailChallenge {
  const requestedEmail = normalizeEmail(email);
  return { ...state, email: requestedEmail, requestedEmail, token: '', resendAt: now + EMAIL_CODE_COOLDOWN_MS };
}

/** Changing the email invalidates the local challenge and typed code; the cooldown remains. */
export function editEmailChallenge(state: EmailChallenge): EmailChallenge {
  return { ...state, requestedEmail: null, token: '' };
}

export function emailCodeWaitSeconds(state: EmailChallenge, now: number): number {
  return Math.max(0, Math.ceil((state.resendAt - now) / 1000));
}

export function emailVerificationCredentials(state: EmailChallenge): { email: string; token: string } | null {
  if (!state.requestedEmail) return null;
  return { email: state.requestedEmail, token: state.token.trim() };
}
