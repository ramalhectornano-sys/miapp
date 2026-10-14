import type { Application, ChatMessage, FoundJob, Health, JobSearch, SearchProposal } from '../types';
import { requireSession } from './supabase';

export const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL?.trim().replace(/\/$/, '') ?? '';
export type ApiOptions = { method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'; body?: unknown; anonymous?: boolean };

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  if (!BACKEND_URL) throw new Error('Configurá la dirección del backend para usar integraciones reales.');
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error('La ruta del servicio no es válida.');
  const session = options.anonymous ? null : await requireSession();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path.endsWith('/run') ? 180000 : 120000);
  try {
    const response = await fetch(`${BACKEND_URL}${path}`, {
      method: options.method ?? 'GET',
      headers: { Accept: 'application/json', ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}) },
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}), signal: controller.signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data?.detail;
      throw new Error(typeof detail === 'string' ? detail : response.status === 401
        ? 'La sesión venció. Iniciá sesión nuevamente.' : 'El servidor no pudo completar la operación.');
    }
    return data as T;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('No se recibió una respuesta del servidor. Revisá el historial antes de repetir una búsqueda o un envío.');
    }
    if (error instanceof TypeError) throw new Error('No se pudo conectar con el servidor. Revisá tu conexión y la dirección del backend.');
    throw error;
  } finally { clearTimeout(timer); }
}

export type ChatResponse = { reply: string; proposal?: SearchProposal | null; mode: 'demo' | 'live' };
export function chat(message: string, history: Pick<ChatMessage, 'role' | 'content'>[] = []) {
  return api<ChatResponse>('/api/chat', { method: 'POST', body: { message, history: history.slice(-12).map(({ role, content }) => ({ role, content })) } });
}
export const createSearch = (proposal: SearchProposal) => api<{ search: JobSearch; automatic_authorization_required: boolean; message: string }>('/api/searches', { method: 'POST', body: proposal });
export const updateSearch = (id: string, patch: { status?: 'enabled' | 'paused'; time?: string; timezone?: string; frequency?: 'daily' | 'weekly'; weekdays?: number[]; resume_id?: string }) =>
  api<JobSearch>(`/api/searches/${encodeURIComponent(id)}`, { method: 'PATCH', body: patch });
export const runSearch = (id: string) => api<{ run_id: string; status: string; found_count: number; message: string; recorded: boolean }>(`/api/searches/${encodeURIComponent(id)}/run`, { method: 'POST' });
export type SearchRun = { id: string; status: 'running' | 'completed' | 'error' | 'blocked'; started_at: string; finished_at: string | null; found_count: number; message: string | null };
export const getRuns = (id: string) => api<SearchRun[]>(`/api/searches/${encodeURIComponent(id)}/runs`);
export const getSearchResults = (id: string) => api<FoundJob[]>(`/api/searches/${encodeURIComponent(id)}/results`);
export const extractResume = (id: string) => api<{ resume_id: string; text: string; profile_saved: false; requires_confirmation: true; extraction_method: string; message: string }>(`/api/resumes/${encodeURIComponent(id)}/extract`, { method: 'POST' });
export const startGoogleOAuth = () => api<{ authorization_url: string; message: string }>('/api/mail/google/start', { method: 'POST' });

export function mapApplication(row: Record<string, unknown>): Application {
  return {
    id: String(row.id), company: String(row.company ?? ''), role: String(row.job_title ?? row.role ?? ''),
    recipient_email: String(row.recipient_email ?? ''), subject: String(row.subject ?? ''), body: String(row.body ?? ''),
    resume_id: typeof row.resume_id === 'string' ? row.resume_id : null,
    status: row.status as Application['status'], created_at: String(row.created_at),
    provider_message_id: typeof row.provider_message_id === 'string' ? row.provider_message_id : null,
    provider_confirmed_at: typeof row.provider_confirmed_at === 'string' ? row.provider_confirmed_at : null,
    parent_application_id: typeof row.parent_application_id === 'string' ? row.parent_application_id : null,
    delivery_sequence: typeof row.delivery_sequence === 'number' && Number.isInteger(row.delivery_sequence) && row.delivery_sequence >= 0 ? row.delivery_sequence : 0,
    job_match_id: typeof row.job_match_id === 'string' ? row.job_match_id : null,
    sending_consent_id: typeof row.sending_consent_id === 'string' ? row.sending_consent_id : null,
    sender_email: typeof row.sender_email === 'string' ? row.sender_email : null,
    send_attempt_id: typeof row.send_attempt_id === 'string' ? row.send_attempt_id : null,
    attempted_at: typeof row.send_attempt_started_at === 'string' ? row.send_attempt_started_at : typeof row.attempted_at === 'string' ? row.attempted_at : null,
    sent_at: typeof row.sent_at === 'string' ? row.sent_at : null,
    delivery_uncertain: row.delivery_uncertain === true,
    followups_stopped: row.followups_stopped === true,
    followups_stopped_at: typeof row.followups_stopped_at === 'string' ? row.followups_stopped_at : null,
    followups_stop_reason: typeof row.followups_stop_reason === 'string' ? row.followups_stop_reason : null,
    error_message: typeof row.error === 'string' ? row.error : null,
  };
}

export async function sendApplication(id: string): Promise<Application> {
  return mapApplication(await api<Record<string, unknown>>(`/api/applications/${encodeURIComponent(id)}/send`, {
    method: 'POST', body: { consent: true, acknowledgment: 'Enviar esta postulación' },
  }));
}
export const stopApplicationFollowups = (id: string) => api<{ stopped: boolean; recipient_email: string; stopped_at: string; reason: string; message: string }>(`/api/applications/${encodeURIComponent(id)}/stop-followups`, { method: 'POST', body: { reason: 'user_request' } });
export const editApplication = (id: string, body: { subject?: string; body?: string; resume_id?: string; email_connection_id?: string }) =>
  api<Record<string, unknown>>(`/api/applications/${encodeURIComponent(id)}`, { method: 'PATCH', body });
export const deleteAccount = () => api<{ deleted: boolean; message: string }>('/api/account', { method: 'DELETE' });
export const deleteResumeDocument = (id: string) => api<{ deleted: boolean; message: string }>(`/api/resumes/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const sendingAuthorizationText = (repeatEveryDays: 0 | 3) => repeatEveryDays === 3
  ? 'Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día'
  : 'Autorizo los envíos automáticos de esta búsqueda';
export const grantSendingConsent = (body: { search_id: string; resume_id: string; email_connection_id: string; allowed_sources: string[]; expires_at: string; repeat_every_days: 0 | 3 }) =>
  api<{ consent: Record<string, unknown>; search: JobSearch; message: string }>('/api/mail/consents', { method: 'POST', body: { ...body, acknowledgment: sendingAuthorizationText(body.repeat_every_days) } });
export const revokeSendingConsent = (id: string) => api<{ revoked: boolean }>(`/api/mail/consents/${encodeURIComponent(id)}`, { method: 'DELETE' });
export type MailPolicy = { daily_limit: number; timezone: string; repeat_every_days: 0 | 3 };
export type Integrations = { sources: { id: string; name: string; description?: string; supports_automatic_email: boolean }[]; email_connections: { id: string; provider: string; email: string; status: string; connected_at: string }[]; sending_enabled: boolean; mail_policy?: MailPolicy };
export const getIntegrations = () => api<Integrations>('/api/integrations');

type BackendHealth = { integrations: { ai: string; job_sources: string; mail_oauth: string; mail_sending: string; scheduler: string }; status: string };
export async function getHealth(): Promise<Health> {
  const result = await api<BackendHealth>('/health', { anonymous: true });
  return { mode: result.integrations.ai === 'demo' ? 'demo' : 'live', ai: result.integrations.ai,
    source: result.integrations.job_sources, mail: result.integrations.mail_sending === 'enabled' ? result.integrations.mail_oauth : 'disabled', scheduler: result.integrations.scheduler };
}
