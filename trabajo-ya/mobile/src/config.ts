export const config = {
  demo: process.env.EXPO_PUBLIC_DEMO_MODE !== 'false',
  apiUrl: process.env.EXPO_PUBLIC_BACKEND_URL || 'http://10.0.2.2:8000',
  supabaseUrl: process.env.EXPO_PUBLIC_SUPABASE_URL || '',
  supabaseKey: process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY?.trim() || process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim() || '',
};
export const isSupabaseConfigured = Boolean(config.supabaseUrl && config.supabaseKey);
