import type { JobSearch } from '../types';

export type SendingPermission = 'demo' | 'manual' | 'active' | 'paused' | 'expired' | 'revoked' | 'unknown';

/** Display permission only when its current scope and expiration are known. */
export function sendingPermission(search: JobSearch, now = Date.now()): SendingPermission {
  if (search.demo) return 'demo';
  if (search.consent_revoked_at) return 'revoked';
  if (!search.auto_apply || !search.consent_id) return 'manual';
  const expires = search.consent_expires_at ? Date.parse(search.consent_expires_at) : NaN;
  if (!Number.isFinite(expires)) return 'unknown';
  if (expires <= now) return 'expired';
  return search.status === 'paused' ? 'paused' : 'active';
}

export function sendingPermissionLabel(permission: SendingPermission): string {
  return { demo: 'Demostración · sin envíos reales', manual: 'Envíos automáticos sin autorizar',
    active: 'Envíos automáticos autorizados', paused: 'Envíos automáticos en pausa',
    expired: 'Autorización vencida', revoked: 'Autorización revocada',
    unknown: 'Permiso pendiente de verificar' }[permission];
}
