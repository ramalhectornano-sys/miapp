import 'react-native-url-polyfill/auto';
import { AppState as NativeAppState, Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js';
import { createEmailAuth } from './emailAuth';

export const DEMO_MODE = process.env.EXPO_PUBLIC_DEMO_MODE !== 'false';
const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL?.trim() ?? '';
const publicKey = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY?.trim() || process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim() || '';

function publicKeyIsSafe(key: string): boolean {
  if (key.startsWith('sb_secret_')) return false;
  if (key.startsWith('sb_publishable_')) return true;
  // Refuse the legacy service-role JWT, even if accidentally pasted into Expo config.
  const parts = key.split('.');
  const payload = parts.length === 3 ? parts[1] : null;
  if (payload) {
    try {
      const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
      const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
      let buffer = 0, bits = 0, decodedText = '';
      for (const char of normalized.replace(/=+$/, '')) {
        const digit = alphabet.indexOf(char);
        if (digit < 0) return false;
        buffer = (buffer << 6) | digit; bits += 6;
        if (bits >= 8) { bits -= 8; decodedText += String.fromCharCode((buffer >> bits) & 255); }
      }
      return JSON.parse(decodedText).role === 'anon';
    } catch { return false; }
  }
  return false;
}

export const SUPABASE_CONFIGURED = Boolean(supabaseUrl && publicKey && publicKeyIsSafe(publicKey));
type Manifest = { generation: string; chunks: number };
const memory = new Map<string, string>();
const keyBase = (key: string) => `autoempleo.${key.replace(/[^A-Za-z0-9._-]/g, '_')}`;
const nativeOptions = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };

function parseManifest(raw: string | null): Manifest | null {
  if (!raw) return null;
  try {
    const item = JSON.parse(raw);
    return typeof item.generation === 'string' && /^[a-f0-9-]+$/.test(item.generation)
      && Number.isInteger(item.chunks) && item.chunks >= 1 && item.chunks <= 128 ? item : null;
  } catch { return null; }
}

function utf8Chunks(value: string): string[] {
  const chunks: string[] = [];
  let chunk = '', length = 0;
  for (const char of value) {
    const code = char.codePointAt(0)!;
    const bytes = code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4;
    if (length + bytes > 1800) { chunks.push(chunk); chunk = ''; length = 0; }
    chunk += char; length += bytes;
  }
  chunks.push(chunk);
  return chunks;
}

async function removeChunks(base: string, manifest: Manifest | null) {
  if (!manifest) return;
  await Promise.all(Array.from({ length: manifest.chunks }, (_, index) =>
    SecureStore.deleteItemAsync(`${base}.${manifest.generation}.${index}`, nativeOptions)));
}

/** Native tokens use encrypted storage; browser tokens stay in memory only. */
export const sessionStorage = {
  async getItem(key: string): Promise<string | null> {
    if (Platform.OS === 'web') return memory.get(key) ?? null;
    const base = keyBase(key);
    const manifest = parseManifest(await SecureStore.getItemAsync(`${base}.manifest`, nativeOptions));
    if (!manifest) return null;
    const chunks = await Promise.all(Array.from({ length: manifest.chunks }, (_, index) =>
      SecureStore.getItemAsync(`${base}.${manifest.generation}.${index}`, nativeOptions)));
    return chunks.some(chunk => chunk === null) ? null : chunks.join('');
  },
  async setItem(key: string, value: string): Promise<void> {
    if (Platform.OS === 'web') { memory.set(key, value); return; }
    const base = keyBase(key);
    const previous = parseManifest(await SecureStore.getItemAsync(`${base}.manifest`, nativeOptions));
    const chunks = utf8Chunks(value);
    if (chunks.length > 128) throw new Error('La sesión excede el tamaño permitido.');
    const next = { generation: Crypto.randomUUID(), chunks: chunks.length };
    try {
      for (let index = 0; index < chunks.length; index++) {
        await SecureStore.setItemAsync(`${base}.${next.generation}.${index}`, chunks[index], nativeOptions);
      }
      // Commit the manifest last; an interrupted write keeps the preceding session intact.
      await SecureStore.setItemAsync(`${base}.manifest`, JSON.stringify(next), nativeOptions);
    } catch (error) {
      await removeChunks(base, next).catch(() => undefined);
      throw error;
    }
    await removeChunks(base, previous).catch(() => undefined);
  },
  async removeItem(key: string): Promise<void> {
    if (Platform.OS === 'web') { memory.delete(key); return; }
    const base = keyBase(key);
    const previous = parseManifest(await SecureStore.getItemAsync(`${base}.manifest`, nativeOptions));
    await SecureStore.deleteItemAsync(`${base}.manifest`, nativeOptions);
    await removeChunks(base, previous);
  },
};

export const supabase: SupabaseClient | null = SUPABASE_CONFIGURED
  ? createClient(supabaseUrl, publicKey, {
      auth: { storage: sessionStorage, autoRefreshToken: true, persistSession: true, detectSessionInUrl: false },
    }) : null;

export function requireSupabase(): SupabaseClient {
  if (!supabase) throw new Error('Configurá la URL y una clave pública de Supabase para usar tu cuenta real.');
  return supabase;
}

export async function getSession(): Promise<Session | null> {
  if (!supabase) return null;
  const { data, error } = await supabase.auth.getSession();
  if (error) throw new Error('No se pudo recuperar tu sesión. Iniciá sesión nuevamente.');
  return data.session;
}

export async function requireSession(): Promise<Session> {
  const session = await getSession();
  if (!session) throw new Error('Iniciá sesión para continuar.');
  return session;
}

export async function requestEmailCode(email: string, fullName?: string): Promise<void> {
  await createEmailAuth<Session>(requireSupabase().auth).requestEmailCode(email, fullName);
}

export async function verifyEmailCode(email: string, token: string): Promise<Session> {
  return createEmailAuth<Session>(requireSupabase().auth).verifyEmailCode(email, token);
}

export async function signOut(): Promise<void> {
  if (!supabase) return;
  const { error } = await supabase.auth.signOut();
  if (error) throw new Error('No se pudo cerrar la sesión. Intentá nuevamente.');
}

/** Call once from the app shell and dispose the returned subscription on unmount. */
export function observeAuthRefresh(): () => void {
  if (!supabase || Platform.OS === 'web') return () => undefined;
  if (NativeAppState.currentState === 'active') supabase.auth.startAutoRefresh();
  const subscription = NativeAppState.addEventListener('change', state => {
    if (state === 'active') supabase.auth.startAutoRefresh();
    else supabase.auth.stopAutoRefresh();
  });
  return () => subscription.remove();
}
