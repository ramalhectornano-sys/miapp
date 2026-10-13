-- Solo para la prueba PostgreSQL embebida. NO es una migración Supabase.
-- Recrea el contrato mínimo de auth/storage; no reemplaza pruebas contra Supabase real.
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema auth;
create schema storage;
create table auth.users(id uuid primary key, raw_user_meta_data jsonb not null default '{}');
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
grant usage on schema public, auth, storage to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
create table storage.buckets(
  id text primary key, name text not null, public boolean not null default false,
  file_size_limit bigint, allowed_mime_types text[]
);
create table storage.objects(
  id uuid primary key default gen_random_uuid(),
  bucket_id text references storage.buckets(id), name text not null,
  unique(bucket_id, name)
);
create function storage.foldername(name text) returns text[] language sql immutable as $$
  select (string_to_array(name, '/'))[1:array_length(string_to_array(name, '/'), 1)-1]
$$;
alter table storage.objects enable row level security;
grant select, insert, update, delete on storage.objects to authenticated;

-- Supabase concede al servidor gestión privada de objetos; permite probar el
-- borrado total de cuenta sin desactivar el guard del CV para authenticated.
grant select,insert,delete on storage.objects to service_role;
