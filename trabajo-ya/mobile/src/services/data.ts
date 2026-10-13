import { Platform } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import * as Crypto from 'expo-crypto';
import type { AppState, ChatMessage, Profile, Resume } from '../types';
import { deleteResumeDocument, mapApplication } from './backend';
import { requireSession, requireSupabase } from './supabase';

export type UploadAsset = { uri: string; name?: string; mimeType?: string | null; size?: number; file?: File };
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ensureId = (id: string) => uuidPattern.test(id) ? id : Crypto.randomUUID();

function check(error: unknown, message: string) { if (error) throw new Error(message); }
function databaseRejected(error: unknown): boolean {
  // SQLSTATE/PostgREST codes come from a server rejection. A fetch/timeout
  // failure gives no assurance that the database transaction did not commit.
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : '';
  return /^(?:[0-9]{2}[0-9A-Z]{3}|P[0-9]{4}|XX[0-9]{3}|PGRST\d+)$/.test(code);
}
export const emptyProfile = (): Profile => ({ full_name: '', city: '', headline: '', photo_path: null, experiences: [], credentials: [], references: [] });

export function mapResume(row: Record<string, unknown>, isDefault = false): Resume {
  return { id: String(row.id), name: String(row.name ?? ''), file_name: String(row.original_filename ?? ''),
    storage_path: String(row.object_path ?? ''), mime_type: String(row.mime_type ?? ''), size_bytes: Number(row.size_bytes ?? 0),
    created_at: String(row.created_at), is_default: isDefault };
}

export async function loadState(): Promise<AppState> {
  const client = requireSupabase();
  const session = await requireSession();
  const userId = session.user.id;
  const results = await Promise.all([
    client.from('profiles').select('*').eq('user_id', userId).maybeSingle(),
    client.from('work_experiences').select('*').eq('user_id', userId).order('created_at'),
    client.from('credentials').select('*').eq('user_id', userId).order('created_at'),
    client.from('professional_references').select('*').eq('user_id', userId).order('created_at'),
    client.from('resume_versions').select('*').eq('user_id', userId).order('created_at', { ascending: false }),
    client.from('job_searches').select('*').eq('user_id', userId).order('created_at', { ascending: false }).limit(100),
    client.from('applications').select('*').eq('user_id', userId).order('created_at', { ascending: false }).limit(100),
    client.from('chat_messages').select('*').eq('user_id', userId).order('created_at', { ascending: false }).limit(100),
    client.from('sending_consents').select('id,expires_at,revoked_at,repeat_enabled,repeat_interval_days,policy_version,daily_limit').eq('user_id', userId),
    client.from('email_connections').select('id,email,provider,status').eq('user_id', userId).order('connected_at', { ascending: false }),
    client.from('recipient_suppressions').select('recipient_email,stopped_at,reason').eq('user_id', userId),
  ]);
  results.forEach(result => check(result.error, 'No se pudieron cargar tus datos privados. Intentá nuevamente.'));
  const [identity, experiences, credentials, references, resumes, searches, applications, messages, consents, connections, suppressions] = results;
  const base = identity.data ?? emptyProfile();
  const preferred = identity.data?.preferred_resume_id;
  const defaultId = resumes.data?.some(row => row.id === preferred) ? preferred : resumes.data?.[0]?.id;
  return {
    profile: { full_name: base.full_name ?? '', city: base.city ?? '', headline: base.headline ?? '', photo_path: base.photo_path ?? null,
      experiences: experiences.data ?? [], credentials: credentials.data ?? [], references: references.data ?? [] },
    resumes: (resumes.data ?? []).map(row => mapResume(row, row.id === defaultId)),
    searches: (searches.data ?? []).map(row => { const permission = (consents.data ?? []).find(item => item.id === row.consent_id); return { ...row, consent_expires_at: permission?.expires_at ?? null, consent_revoked_at: permission?.revoked_at ?? null, consent_daily_limit: permission?.daily_limit ?? null, consent_repeat_every_days: permission?.policy_version === 'v3' && permission.repeat_enabled && permission.repeat_interval_days === 3 ? 3 as const : 0 as const }; }),
    email_connections: connections.data ?? [],
    applications: (applications.data ?? []).map(row => {
      const stopped = (suppressions.data ?? []).find(item => item.recipient_email === String(row.recipient_email || '').trim().toLowerCase());
      return mapApplication({ ...row, followups_stopped: !!stopped, followups_stopped_at: stopped?.stopped_at, followups_stop_reason: stopped?.reason });
    }),
    messages: (messages.data ?? []).reverse().filter(row => row.role === 'user' || row.role === 'assistant').map(row => ({
      id: row.id, role: row.role as ChatMessage['role'], content: row.content, created_at: row.created_at,
      ...(row.metadata?.proposal ? { proposal: row.metadata.proposal } : {}), demo: row.metadata?.mode === 'demo',
    })),
  };
}

function validDate(value?: string | null): string | null {
  if (!value?.trim()) return null;
  const date = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date) {
    throw new Error('Las fechas deben ser válidas y usar AAAA-MM-DD.');
  }
  return date;
}

export async function saveProfile(profile: Profile): Promise<Profile> {
  const client = requireSupabase();
  const userId = (await requireSession()).user.id;
  if (!profile.full_name.trim()) throw new Error('Completá tu nombre para guardar el perfil.');
  const experiences = profile.experiences.filter(item => item.company.trim() || item.role.trim() || item.description.trim()).map(item => {
    if (!item.company.trim() || !item.role.trim()) throw new Error('Cada experiencia necesita una empresa y un puesto.');
    const start = validDate(item.start_date), end = validDate(item.end_date);
    if (start && end && end < start) throw new Error('La fecha de finalización no puede ser anterior al inicio.');
    return { id: ensureId(item.id), user_id: userId, company: item.company.trim(), role: item.role.trim(), description: item.description.trim(), start_date: start, end_date: end };
  });
  const credentials = profile.credentials.filter(item => item.name.trim() || item.issuer.trim()).map(item => {
    if (!item.name.trim() || !['license', 'course', 'certification'].includes(item.kind)) throw new Error('Revisá el nombre y tipo de cada licencia o curso.');
    return { id: ensureId(item.id), user_id: userId, name: item.name.trim(), issuer: item.issuer.trim(), kind: item.kind };
  });
  const references = profile.references.filter(item => item.full_name.trim() || item.contact.trim()).map(item => {
    if (!item.full_name.trim()) throw new Error('Completá el nombre de cada referencia.');
    return { id: ensureId(item.id), user_id: userId, full_name: item.full_name.trim(), relationship: item.relationship.trim(), contact: item.contact.trim(), consent_to_contact: Boolean(item.consent_to_contact) };
  });
  // The photo has its own upload/commit operation. A profile draft can contain
  // an older path (for example after another device changed the photo), so a
  // text-only save must not overwrite the current private photo reference.
  const { error } = await client.from('profiles').upsert({ user_id: userId, full_name: profile.full_name.trim(), city: profile.city.trim(), headline: profile.headline.trim() });
  check(error, 'No se pudo guardar el perfil.');
  // Keep each upsert tied to its own row shape. Passing the union of these
  // arrays directly to Supabase makes its generic overload infer one section.
  const sections = [
    ['work_experiences', experiences, () => client.from('work_experiences').upsert(experiences)],
    ['credentials', credentials, () => client.from('credentials').upsert(credentials)],
    ['professional_references', references, () => client.from('professional_references').upsert(references)],
  ] as const;
  for (const [table, rows, upsertRows] of sections) {
    const existing = await client.from(table).select('id').eq('user_id', userId);
    check(existing.error, 'No se pudo consultar el perfil antes de guardar.');
    if (rows.length) {
      const result = await upsertRows();
      check(result.error, 'Una sección del perfil no se pudo guardar. Revisá los datos antes de volver a intentarlo.');
    }
    const kept = new Set(rows.map(row => row.id));
    const removed = (existing.data ?? []).filter(row => !kept.has(row.id)).map(row => row.id);
    if (removed.length) {
      const result = await client.from(table).delete().eq('user_id', userId).in('id', removed);
      check(result.error, 'No se pudieron quitar algunos datos del perfil.');
    }
  }
  return (await loadState()).profile;
}

function decodeBase64(value: string): Uint8Array {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const encoded = value.replace(/\s/g, '').replace(/=+$/, '');
  const output = new Uint8Array(Math.floor(encoded.length * 6 / 8));
  let bits = 0, buffer = 0, offset = 0;
  for (const char of encoded) {
    const digit = alphabet.indexOf(char);
    if (digit < 0) continue;
    buffer = (buffer << 6) | digit; bits += 6;
    if (bits >= 8) { bits -= 8; output[offset++] = (buffer >> bits) & 255; }
  }
  return output.subarray(0, offset);
}

async function assetBytes(asset: UploadAsset, maxSize: number): Promise<Uint8Array> {
  if (asset.size && asset.size > maxSize) throw new Error('El archivo supera el tamaño máximo permitido.');
  let bytes: Uint8Array;
  if (asset.file) bytes = new Uint8Array(await asset.file.arrayBuffer());
  else if (Platform.OS === 'web') {
    const response = await fetch(asset.uri);
    if (!response.ok) throw new Error('No se pudo leer el archivo seleccionado.');
    bytes = new Uint8Array(await response.arrayBuffer());
  } else {
    const base64 = await FileSystem.readAsStringAsync(asset.uri, { encoding: FileSystem.EncodingType.Base64 });
    bytes = decodeBase64(base64);
  }
  if (!bytes.byteLength || bytes.byteLength > maxSize) throw new Error('El archivo está vacío o supera el tamaño máximo permitido.');
  return bytes;
}

export async function uploadResume(asset: UploadAsset): Promise<Resume> {
  const client = requireSupabase();
  const userId = (await requireSession()).user.id;
  const filename = asset.name ?? asset.uri.split('/').pop() ?? 'curriculum.pdf';
  const extension = filename.toLowerCase().endsWith('.docx') ? 'docx' : filename.toLowerCase().endsWith('.pdf') ? 'pdf' : null;
  if (!extension) throw new Error('Seleccioná un currículum PDF o DOCX.');
  const mime = extension === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  const bytes = await assetBytes(asset, 10 * 1024 * 1024);
  const id = Crypto.randomUUID(), path = `${userId}/${id}.${extension}`;
  const upload = await client.storage.from('resumes').upload(path, bytes, { contentType: mime, upsert: false });
  check(upload.error, 'No se pudo cargar el currículum privado.');
  const result = await client.rpc('register_resume_version', {
    p_id: id, p_name: filename.replace(/\.(pdf|docx)$/i, ''),
    p_original_filename: filename, p_object_path: path,
    p_mime_type: mime, p_size_bytes: bytes.byteLength,
  }).single<Record<string, unknown>>();
  if (result.error || !result.data) {
    const confirmation = await client.from('resume_versions').select('*').eq('id', id).eq('user_id', userId).maybeSingle();
    if (!confirmation.error && confirmation.data?.object_path === path) {
      // The response was lost after the transactional registration committed.
      // A fresh account-owned row confirms the CV is saved; preserve its file.
      return mapResume(confirmation.data, true);
    }
    if (confirmation.error || !databaseRejected(result.error)) {
      throw new Error('No se pudo confirmar el registro del CV. El archivo privado se conserva para evitar pérdidas. Actualizá tus currículums antes de volver a intentarlo.');
    }
    const rollback = await client.storage.from('resumes').remove([path]);
    throw new Error(rollback.error ? 'No se guardó el CV y no se pudo limpiar el archivo cargado. Revisá el almacenamiento antes de repetir.' : 'No se pudo registrar el currículum; se retiró el archivo cargado.');
  }
  return mapResume(result.data, true);
}

export async function makeDefaultResume(id: string): Promise<void> {
  const client = requireSupabase();
  const userId = (await requireSession()).user.id;
  const { data, error } = await client.from('resume_versions').select('id').eq('id', id).eq('user_id', userId).maybeSingle();
  if (error || !data) throw new Error('No se encontró esa versión del currículum en tu cuenta.');
  const updated = await client.from('profiles').update({ preferred_resume_id: id }).eq('user_id', userId).select('user_id');
  if (updated.error || !updated.data?.length) throw new Error('No se pudo guardar el currículum principal en tu cuenta.');
}

export async function deleteResume(resume: Resume): Promise<void> {
  const result = await deleteResumeDocument(resume.id);
  if (!result.deleted) throw new Error('No se confirmó la eliminación del currículum.');
}

async function signedUrl(bucket: 'resumes' | 'profile-photos', path: string): Promise<string> {
  const userId = (await requireSession()).user.id;
  if (!path.startsWith(`${userId}/`) || path.split('/').includes('..')) throw new Error('El documento no pertenece a tu cuenta.');
  const { data, error } = await requireSupabase().storage.from(bucket).createSignedUrl(path, 300);
  if (error || !data?.signedUrl) throw new Error('No se pudo abrir el documento privado.');
  return data.signedUrl;
}
export const getResumeUrl = (resume: Resume) => signedUrl('resumes', resume.storage_path);
export const getPhotoUrl = (path: string) => signedUrl('profile-photos', path);

export async function uploadPhoto(asset: UploadAsset): Promise<{ path: string; url: string }> {
  const client = requireSupabase();
  const userId = (await requireSession()).user.id;
  const mime = asset.mimeType || 'image/jpeg';
  const extension = ({ 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp' } as Record<string, string>)[mime];
  if (!extension) throw new Error('Usá una fotografía JPG, PNG o WebP.');
  const bytes = await assetBytes(asset, 5 * 1024 * 1024);
  const path = `${userId}/${Crypto.randomUUID()}.${extension}`;
  const previous = await client.from('profiles').select('photo_path').eq('user_id', userId).maybeSingle();
  check(previous.error, 'No se pudo consultar la fotografía actual.');
  const upload = await client.storage.from('profile-photos').upload(path, bytes, { contentType: mime, upsert: false });
  check(upload.error, 'No se pudo cargar la fotografía privada.');
  // Verify the image can be opened before replacing the persisted reference or
  // deleting the previous image. Otherwise a signed-URL failure would leave
  // the app displaying an already deleted photo after a successful DB update.
  let url: string;
  try {
    url = await getPhotoUrl(path);
  } catch {
    const rollback = await client.storage.from('profile-photos').remove([path]);
    throw new Error(rollback.error
      ? 'No se pudo preparar la fotografía privada ni retirar el archivo nuevo. La fotografía anterior se conserva.'
      : 'No se pudo preparar la fotografía privada. La fotografía anterior se conserva; intentá nuevamente.');
  }
  const updated = await client.from('profiles').update({ photo_path: path }).eq('user_id', userId).select('user_id');
  if (updated.error || !updated.data?.length) {
    const confirmation = await client.from('profiles').select('photo_path').eq('user_id', userId).maybeSingle();
    if (confirmation.error || (confirmation.data?.photo_path !== path && updated.error && !databaseRejected(updated.error))) {
      throw new Error('No se pudo confirmar la fotografía del perfil. Los archivos privados se conservan para evitar pérdidas. Actualizá el perfil antes de volver a intentarlo.');
    }
    if (confirmation.data?.photo_path !== path) {
      const rollback = await client.storage.from('profile-photos').remove([path]);
      throw new Error(rollback.error
        ? 'No se pudo asociar la fotografía al perfil ni retirar el archivo nuevo. La fotografía anterior se conserva.'
        : 'No se pudo asociar la fotografía al perfil. La fotografía anterior se conserva.');
    }
  }
  if (previous.data?.photo_path) await client.storage.from('profile-photos').remove([previous.data.photo_path]);
  return { path, url };
}
