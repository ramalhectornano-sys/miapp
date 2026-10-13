-- Trabajo YA: instalación ÚNICAMENTE en un proyecto Supabase NUEVO y vacío.
-- Generado por: python scripts/build_database_install.py
-- No editar: las fuentes son supabase/migrations/*.sql.
-- Ejecutar el archivo COMPLETO una sola vez en SQL Editor, con rol postgres.
-- No ejecutar sobre una instalación existente ni combinar con supabase db push.
-- No contiene usuarios de prueba, semillas ni credenciales privadas.
-- Cantidad de migraciones: 5
-- SHA-256 del conjunto (nombre + NUL + SQL + NUL): 2a7d32f2def6d324c41d741373b92f8a7f9ab9d5a1b757c548cb1260a5a0186f
-- Manifiesto SHA-256 de los archivos originales, en orden de aplicación:
-- 202610120001_initial.sql  0b85b7ac2b14abe96d979c862a0de6947563cdb7e715e2c1baaf64f7574e4418
-- 202610120002_manual_search.sql  0fde00355d4126c4515708197880f2359d5b60bee065d5a93fa8d8952c9031ad
-- 202610120003_claim_fencing.sql  90a3e6f99eff20df458e5ef526ab514dbe016f39dacdb032c717dcc8daf30c12
-- 202610120004_automatic_sending_policy.sql  63d50c0b31382ee084629c9d36d5971fb9f4d1f75981257c59ab5c2f75078711
-- 202610120005_daily_budget_and_followups.sql  65bc6eed3e81706dd48e68329988d92887c4402ec9c7b6c25c17249aee7728a2

BEGIN;

-- La comprobación ocurre antes de crear o modificar cualquier objeto.
-- Auth y Storage estándar deben existir; sus tablas vacías son compatibles.
do $trabajoya_new_project_guard$
declare
  existing_objects text[];
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('trabajo-ya:install-new-project', 0)
  );
  if pg_catalog.to_regclass('auth.users') is null
     or pg_catalog.to_regclass('storage.buckets') is null
     or pg_catalog.to_regclass('storage.objects') is null then
    raise exception 'Trabajo YA: este archivo requiere un proyecto Supabase nuevo con Auth y Storage habilitados.';
  end if;

  select pg_catalog.array_agg(object_name order by object_name) into existing_objects
    from pg_catalog.unnest(array['private.email_connection_secrets','private.oauth_states','public.applications','public.chat_messages','public.credentials','public.email_connections','public.job_search_matches','public.job_search_runs','public.job_searches','public.jobs','public.professional_references','public.profiles','public.recipient_suppressions','public.resume_versions','public.sending_consents','public.work_experiences']::text[]) as objects(object_name)
    where pg_catalog.to_regclass(object_name) is not null;
  if existing_objects is not null then
    raise exception 'Trabajo YA: ya existen tablas u objetos de la aplicación (%). No se cambió nada. Aplicá solo las migraciones pendientes; este instalador es para un proyecto nuevo.',
      pg_catalog.array_to_string(existing_objects, ', ');
  end if;

  select pg_catalog.array_agg(distinct n.nspname || '.' || p.proname) into existing_objects
    from pg_catalog.pg_proc as p
    join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
    where n.nspname || '.' || p.proname = any(array['private.current_job_match','private.delivery_budget_available','private.freeze_sending_timezone','private.handle_new_user','private.preserve_delivery_evidence','private.protect_delivered_resume_object','private.touch_updated_at','private.validate_fresh_match','public.assert_search_claim','public.claim_application_send','public.claim_due_searches','public.claim_search_now','public.complete_search_run','public.consume_oauth_state','public.create_initial_application','public.get_email_secret','public.grant_sending_consent','public.prepare_automatic_application','public.prepare_followup_application','public.revoke_sending_consent','public.stop_recipient_followups','public.store_email_secret','public.store_oauth_state','public.valid_timezone','public.valid_weekdays']::text[]);
  if existing_objects is not null then
    raise exception 'Trabajo YA: ya existen funciones de la aplicación. No se cambió nada. Aplicá solo las migraciones pendientes en ese proyecto.';
  end if;

  if exists (
    select 1 from pg_catalog.pg_trigger as t
    join pg_catalog.pg_class as c on c.oid = t.tgrelid
    join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
    where not t.tgisinternal and (
      (n.nspname = 'auth' and c.relname = 'users' and t.tgname = 'autoempleo_new_user')
      or (n.nspname = 'storage' and c.relname = 'objects' and t.tgname = 'protect_delivered_resume_object')
    )
  ) or exists (
    select 1 from pg_catalog.pg_policy as p
    join pg_catalog.pg_class as c on c.oid = p.polrelid
    join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
    where n.nspname = 'storage' and c.relname = 'objects'
      and p.polname in ('autoempleo_private_objects_read', 'autoempleo_private_objects_insert', 'autoempleo_private_objects_delete')
  ) then
    raise exception 'Trabajo YA: ya existen permisos o triggers de la aplicación. No se cambió nada. Aplicá solo las migraciones pendientes.';
  end if;

  if exists (select 1 from storage.buckets where id in ('resumes', 'profile-photos')) then
    raise exception 'Trabajo YA: ya existen buckets resumes o profile-photos. No se cambió nada. Usá un proyecto nuevo dedicado o revisá las migraciones pendientes.';
  end if;
  if exists (select 1 from auth.users limit 1) then
    raise exception 'Trabajo YA: este proyecto ya tiene usuarios de la aplicación. No se cambió nada. Usá un proyecto nuevo o revisá las migraciones pendientes antes de continuar.';
  end if;
end;
$trabajoya_new_project_guard$;

-- ===== INICIO MIGRACIÓN: 202610120001_initial.sql =====
-- AutoEmpleo IA: esquema privado por usuario. Requiere Supabase PostgreSQL 15+.
-- Nunca ejecutar esta migración con la clave anon desde la aplicación.

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create function public.valid_timezone(value text) returns boolean
language sql stable set search_path = '' as $$
  select exists (select 1 from pg_catalog.pg_timezone_names where name = value)
$$;
create function public.valid_weekdays(value integer[]) returns boolean
language sql immutable set search_path = '' as $$
  select value is not null and not exists (
    select 1 from unnest(value) as day where day is null or day < 1 or day > 7
  ) and cardinality(value) = (select count(distinct day) from unnest(value) as day)
$$;
create function private.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null default '',
  city text not null default '',
  headline text not null default '',
  photo_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint profile_photo_owner check (photo_path is null or photo_path like user_id::text || '/%')
);
create table public.work_experiences (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  company text not null,
  role text not null,
  start_date date,
  end_date date,
  description text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (end_date is null or start_date is null or end_date >= start_date)
);
create table public.professional_references (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  full_name text not null,
  relationship text not null default '',
  contact text not null default '',
  consent_to_contact boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table public.credentials (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  issuer text not null default '',
  issued_at date,
  expires_at date,
  kind text not null check (kind in ('license', 'course', 'certification')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (expires_at is null or issued_at is null or expires_at >= issued_at)
);
create table public.resume_versions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  original_filename text not null,
  object_path text not null,
  mime_type text not null check (mime_type in (
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  )),
  size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 10485760),
  sha256 text check (sha256 is null or sha256 ~ '^[a-f0-9]{64}$'),
  extracted_text text,
  extracted_facts jsonb not null default '{}'::jsonb,
  extraction_status text not null default 'pending' check (extraction_status in ('pending', 'extracted', 'error')),
  extraction_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, id),
  unique (user_id, object_path),
  check (object_path like user_id::text || '/%'),
  check (jsonb_typeof(extracted_facts) = 'object')
);
create table public.email_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('google', 'microsoft')),
  email text not null,
  status text not null default 'connected' check (status in ('connected', 'disconnected', 'expired')),
  scopes text[] not null default '{}',
  connected_at timestamptz not null default now(),
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, id),
  unique (user_id, provider, email)
);
create table public.job_searches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  roles text[] not null check (cardinality(roles) > 0),
  cities text[] not null check (cardinality(cities) > 0),
  frequency text not null default 'daily' check (frequency in ('daily', 'weekly')),
  schedule_time time not null default '09:00:00',
  timezone text not null default 'America/Argentina/Salta' check (public.valid_timezone(timezone)),
  weekdays integer[] not null default '{}' check (public.valid_weekdays(weekdays)),
  status text not null default 'enabled' check (status in ('enabled', 'paused')),
  auto_apply boolean not null default false,
  preferred_resume_id uuid,
  consent_id uuid,
  next_run_at timestamptz not null,
  last_run_at timestamptz,
  claim_token uuid,
  lease_expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, id),
  foreign key (user_id, preferred_resume_id) references public.resume_versions(user_id, id) deferrable initially deferred,
  check (frequency <> 'weekly' or cardinality(weekdays) > 0),
  check ((claim_token is null) = (lease_expires_at is null)),
  check (not auto_apply or consent_id is not null)
);
create table public.sending_consents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  search_id uuid not null,
  resume_id uuid,
  email_connection_id uuid not null,
  authorized_sources text[] not null check (cardinality(authorized_sources) > 0),
  daily_limit integer not null check (daily_limit between 1 and 25),
  authorization_text text not null check (length(btrim(authorization_text)) >= 20),
  policy_version text not null default 'v1',
  granted_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  unique (user_id, id),
  foreign key (user_id, search_id) references public.job_searches(user_id, id) on delete cascade,
  foreign key (user_id, resume_id) references public.resume_versions(user_id, id) deferrable initially deferred,
  foreign key (user_id, email_connection_id) references public.email_connections(user_id, id) deferrable initially deferred,
  check (expires_at > granted_at),
  check (revoked_at is null or revoked_at >= granted_at)
);
alter table public.job_searches add constraint job_search_consent_owner
  foreign key (user_id, consent_id) references public.sending_consents(user_id, id) deferrable initially deferred;

create table public.job_search_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  search_id uuid not null,
  claim_token uuid not null unique,
  worker_id text not null,
  status text not null default 'running' check (status in ('running', 'completed', 'error', 'blocked')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  found_count integer not null default 0 check (found_count >= 0),
  message text,
  foreign key (user_id, search_id) references public.job_searches(user_id, id) on delete cascade,
  check ((status = 'running') = (finished_at is null))
);
create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  source text not null,
  external_id text,
  fingerprint text not null,
  company text not null,
  title text not null,
  city text not null default '',
  url text,
  recipient_email text,
  recipient_verified_at timestamptz,
  source_authorized boolean not null default false,
  description text not null default '',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, id),
  unique (user_id, fingerprint),
  unique (user_id, source, external_id),
  check (recipient_verified_at is null or recipient_email is not null)
);
create table public.applications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  search_id uuid,
  resume_id uuid not null,
  email_connection_id uuid,
  company text not null,
  job_title text not null,
  recipient_email text,
  recipient_verified_at timestamptz,
  subject text not null,
  body text not null,
  status text not null default 'pending' check (status in ('pending', 'sent', 'error', 'responded')),
  provider_message_id text,
  provider_confirmed_at timestamptz,
  sent_at timestamptz,
  error text,
  send_attempt_id uuid unique,
  send_attempt_started_at timestamptz,
  delivery_uncertain boolean not null default false,
  manual_approved_at timestamptz,
  manual_approval_text text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, job_id),
  foreign key (user_id, job_id) references public.jobs(user_id, id) on delete cascade,
  foreign key (user_id, search_id) references public.job_searches(user_id, id) deferrable initially deferred,
  foreign key (user_id, resume_id) references public.resume_versions(user_id, id) deferrable initially deferred,
  foreign key (user_id, email_connection_id) references public.email_connections(user_id, id) deferrable initially deferred,
  check ((send_attempt_id is null) = (send_attempt_started_at is null)),
  check ((manual_approved_at is null) = (manual_approval_text is null)),
  constraint sent_requires_provider_confirmation check (
    status not in ('sent', 'responded') or (
      nullif(btrim(provider_message_id), '') is not null and
      provider_confirmed_at is not null and sent_at is not null and
      recipient_email is not null and recipient_verified_at is not null and
      send_attempt_id is not null and not delivery_uncertain
    )
  )
);
create table public.chat_messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null check (length(btrim(content)) > 0),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table private.email_connection_secrets (
  connection_id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  encrypted_payload text not null check (length(encrypted_payload) > 0),
  key_id text not null default 'v1',
  updated_at timestamptz not null default now(),
  foreign key (user_id, connection_id) references public.email_connections(user_id, id) on delete cascade
);
create table private.oauth_states (
  state_hash text primary key check (state_hash ~ '^[a-f0-9]{64}$'),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('google', 'microsoft')),
  encrypted_verifier text not null,
  redirect_uri text not null,
  scopes text[] not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index searches_due on public.job_searches(next_run_at, lease_expires_at) where status = 'enabled';
create index runs_by_search on public.job_search_runs(user_id, search_id, started_at desc);
create index applications_history on public.applications(user_id, created_at desc);
create index applications_daily_attempts on public.applications(user_id, search_id, send_attempt_started_at);
create index chat_history on public.chat_messages(user_id, created_at);
create index oauth_expiry on private.oauth_states(expires_at);

-- Todas las tablas, incluidas las privadas, tienen RLS; service_role es exclusivo del backend.
do $$
declare table_name text;
begin
  foreach table_name in array array[
    'profiles','work_experiences','professional_references','credentials','resume_versions',
    'email_connections','job_searches','sending_consents','job_search_runs','jobs','applications','chat_messages'
  ] loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('create policy own_read on public.%I for select to authenticated using (user_id = (select auth.uid()))', table_name);
    execute format('revoke all on public.%I from public, anon, authenticated', table_name);
    execute format('grant select on public.%I to authenticated', table_name);
    execute format('grant all on public.%I to service_role', table_name);
  end loop;
  foreach table_name in array array['profiles','work_experiences','professional_references','credentials'] loop
    execute format('create policy own_insert on public.%I for insert to authenticated with check (user_id = (select auth.uid()))', table_name);
    execute format('create policy own_update on public.%I for update to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()))', table_name);
    execute format('create policy own_delete on public.%I for delete to authenticated using (user_id = (select auth.uid()))', table_name);
    execute format('grant insert, update, delete on public.%I to authenticated', table_name);
  end loop;
  foreach table_name in array array[
    'profiles','work_experiences','professional_references','credentials','resume_versions',
    'email_connections','job_searches','jobs','applications'
  ] loop
    execute format('create trigger touch_updated_at before update on public.%I for each row execute function private.touch_updated_at()', table_name);
  end loop;
end;
$$;
alter table private.email_connection_secrets enable row level security;
alter table private.oauth_states enable row level security;
revoke all on private.email_connection_secrets, private.oauth_states from public, anon, authenticated, service_role;

create policy own_resume_insert on public.resume_versions for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy own_resume_delete on public.resume_versions for delete to authenticated
  using (user_id = (select auth.uid()));
grant insert (id, user_id, name, original_filename, object_path, mime_type, size_bytes, sha256)
  on public.resume_versions to authenticated;
grant delete on public.resume_versions to authenticated;
create policy own_user_message_insert on public.chat_messages for insert to authenticated
  with check (user_id = (select auth.uid()) and role = 'user' and metadata = '{}'::jsonb);
grant insert (id, user_id, role, content) on public.chat_messages to authenticated;

-- Crea únicamente identidad básica; nunca atribuye experiencia desde metadata de registro.
create function private.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles(user_id, full_name)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'full_name', ''));
  return new;
end;
$$;
create trigger autoempleo_new_user after insert on auth.users
  for each row execute function private.handle_new_user();

-- Storage mantiene objetos privados. Se permiten subidas nuevas, nunca sobreescritura de CV.
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values
  ('resumes', 'resumes', false, 10485760, array['application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document']),
  ('profile-photos', 'profile-photos', false, 5242880, array['image/jpeg','image/png','image/webp'])
on conflict (id) do update set public = false,
  file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;
create policy autoempleo_private_objects_read on storage.objects for select to authenticated
  using (bucket_id in ('resumes','profile-photos') and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy autoempleo_private_objects_insert on storage.objects for insert to authenticated
  with check (bucket_id in ('resumes','profile-photos') and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy autoempleo_private_objects_delete on storage.objects for delete to authenticated
  using (bucket_id in ('resumes','profile-photos') and (storage.foldername(name))[1] = (select auth.uid())::text);

-- Revocar es atómico y desactiva auto_apply incluso si la búsqueda está alquilada.
create function public.revoke_sending_consent(p_consent_id uuid) returns boolean
language plpgsql security definer set search_path = '' as $$
declare owner_id uuid := auth.uid();
begin
  if owner_id is null then return false; end if;
  update public.sending_consents set revoked_at = coalesce(revoked_at, now())
    where id = p_consent_id and user_id = owner_id;
  if not found then return false; end if;
  update public.job_searches set auto_apply = false
    where user_id = owner_id and consent_id = p_consent_id;
  return true;
end;
$$;
revoke all on function public.revoke_sending_consent(uuid) from public, anon, authenticated;
grant execute on function public.revoke_sending_consent(uuid) to authenticated;

create function public.claim_due_searches(
  p_worker_id text, p_limit_count integer default 10, p_lease_seconds integer default 300
) returns setof jsonb
language plpgsql security definer set search_path = '' as $$
declare search_row public.job_searches%rowtype; new_token uuid; new_run_id uuid;
begin
  if nullif(btrim(p_worker_id), '') is null or p_limit_count not between 1 and 100 or
     p_lease_seconds not between 30 and 3600 then
    raise exception 'Parámetros de claim inválidos';
  end if;
  for search_row in
    select * from public.job_searches
    where status = 'enabled' and next_run_at <= now()
      and (lease_expires_at is null or lease_expires_at <= now())
    order by next_run_at, id for update skip locked limit p_limit_count
  loop
    if search_row.claim_token is not null then
      update public.job_search_runs set status = 'error', finished_at = now(),
        message = 'El worker perdió su lease; no se confirmó la ejecución.'
        where claim_token = search_row.claim_token and status = 'running';
    end if;
    new_token := gen_random_uuid(); new_run_id := gen_random_uuid();
    update public.job_searches set claim_token = new_token,
      lease_expires_at = now() + make_interval(secs => p_lease_seconds)
      where id = search_row.id returning * into search_row;
    insert into public.job_search_runs(id, user_id, search_id, claim_token, worker_id)
      values (new_run_id, search_row.user_id, search_row.id, new_token, p_worker_id);
    return next to_jsonb(search_row) || jsonb_build_object('run_id', new_run_id);
  end loop;
end;
$$;

create function public.complete_search_run(
  p_search_id uuid, p_claim_token uuid, p_run_id uuid, p_status text,
  p_next_run_at timestamptz, p_found_count integer default 0, p_message text default null
) returns boolean
language plpgsql security definer set search_path = '' as $$
declare search_row public.job_searches%rowtype;
begin
  if p_status not in ('completed','error','blocked') or p_found_count < 0 or
     p_next_run_at is null or p_next_run_at <= now() then
    raise exception 'Resultado o próxima ejecución inválidos';
  end if;
  select * into search_row from public.job_searches
    where id = p_search_id for update;
  if not found or search_row.claim_token is distinct from p_claim_token or
     search_row.lease_expires_at <= now() then return false; end if;
  update public.job_search_runs set status = p_status, finished_at = now(),
    found_count = p_found_count, message = p_message
    where id = p_run_id and search_id = p_search_id and claim_token = p_claim_token and status = 'running';
  if not found then return false; end if;
  update public.job_searches set next_run_at = p_next_run_at,
    last_run_at = case when p_status = 'completed' then now() else last_run_at end,
    claim_token = null, lease_expires_at = null where id = p_search_id;
  return true;
end;
$$;

-- Reserva el intento ANTES de llamar al proveedor. Un timeout permanece incierto;
-- nunca se reenvía automáticamente una reserva previa aunque su estado sea error.
create function public.claim_application_send(
  p_application_id uuid, p_user_id uuid, p_explicit_manual_consent boolean default false,
  p_manual_approval_text text default null
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare app_row public.applications%rowtype; job_row public.jobs%rowtype;
  search_row public.job_searches%rowtype; consent_row public.sending_consents%rowtype;
  attempted_today integer;
begin
  select * into app_row from public.applications
    where id = p_application_id and user_id = p_user_id for update;
  if not found or app_row.status not in ('pending','error') or
    app_row.send_attempt_id is not null or app_row.delivery_uncertain or
    app_row.recipient_verified_at is null or app_row.email_connection_id is null then return null; end if;
  select * into job_row from public.jobs where id = app_row.job_id and user_id = p_user_id;
  if not found or not job_row.source_authorized or job_row.recipient_verified_at is null or
    job_row.recipient_email is distinct from app_row.recipient_email then return null; end if;
  if not exists (select 1 from public.email_connections where id = app_row.email_connection_id
    and user_id = p_user_id and status = 'connected' and revoked_at is null) then return null; end if;
  if p_explicit_manual_consent then
    if length(btrim(coalesce(p_manual_approval_text, ''))) < 20 then
      raise exception 'La aprobación manual requiere texto explícito';
    end if;
  else
    select * into search_row from public.job_searches
      where id = app_row.search_id and user_id = p_user_id;
    if not found or not search_row.auto_apply or search_row.status <> 'enabled' then return null; end if;
    select * into consent_row from public.sending_consents
      where id = search_row.consent_id and user_id = p_user_id for update;
    if not found or consent_row.search_id <> app_row.search_id or consent_row.revoked_at is not null or
      consent_row.expires_at <= now() or not job_row.source = any(consent_row.authorized_sources) or
      consent_row.email_connection_id <> app_row.email_connection_id or
      (consent_row.resume_id is not null and consent_row.resume_id <> app_row.resume_id) then return null; end if;
    select count(*) into attempted_today from public.applications
      where user_id = p_user_id and search_id = app_row.search_id
        and manual_approved_at is null
        and send_attempt_started_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC';
    if attempted_today >= consent_row.daily_limit then return null; end if;
  end if;
  update public.applications set send_attempt_id = gen_random_uuid(), send_attempt_started_at = now(),
    manual_approved_at = case when p_explicit_manual_consent then now() else null end,
    manual_approval_text = case when p_explicit_manual_consent then p_manual_approval_text else null end,
    error = null, status = 'pending'
    where id = p_application_id returning * into app_row;
  return to_jsonb(app_row);
end;
$$;

create function public.store_email_secret(p_connection_id uuid, p_user_id uuid,
  p_encrypted_payload text, p_key_id text default 'v1') returns void
language plpgsql security definer set search_path = '' as $$
begin
  insert into private.email_connection_secrets(connection_id, user_id, encrypted_payload, key_id)
  values (p_connection_id, p_user_id, p_encrypted_payload, p_key_id)
  on conflict (connection_id) do update set encrypted_payload = excluded.encrypted_payload,
    key_id = excluded.key_id, updated_at = now()
    where private.email_connection_secrets.user_id = excluded.user_id;
end;
$$;
create function public.get_email_secret(p_connection_id uuid, p_user_id uuid) returns jsonb
language sql security definer set search_path = '' as $$
  select jsonb_build_object('encrypted_payload', encrypted_payload, 'key_id', key_id)
  from private.email_connection_secrets where connection_id = p_connection_id and user_id = p_user_id
$$;
create function public.store_oauth_state(p_state_hash text, p_user_id uuid, p_provider text,
  p_encrypted_verifier text, p_redirect_uri text, p_scopes text[], p_expires_at timestamptz) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if p_expires_at <= now() or p_expires_at > now() + interval '15 minutes' then
    raise exception 'Caducidad OAuth inválida';
  end if;
  delete from private.oauth_states where expires_at <= now();
  insert into private.oauth_states(state_hash,user_id,provider,encrypted_verifier,redirect_uri,scopes,expires_at)
  values (p_state_hash,p_user_id,p_provider,p_encrypted_verifier,p_redirect_uri,p_scopes,p_expires_at);
end;
$$;
create function public.consume_oauth_state(p_state_hash text, p_provider text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare state_row private.oauth_states%rowtype;
begin
  delete from private.oauth_states where state_hash = p_state_hash and provider = p_provider
    returning * into state_row;
  if not found or state_row.expires_at <= now() then return null; end if;
  return to_jsonb(state_row);
end;
$$;

revoke all on function public.claim_due_searches(text,integer,integer) from public, anon, authenticated;
revoke all on function public.complete_search_run(uuid,uuid,uuid,text,timestamptz,integer,text) from public, anon, authenticated;
revoke all on function public.claim_application_send(uuid,uuid,boolean,text) from public, anon, authenticated;
revoke all on function public.store_email_secret(uuid,uuid,text,text) from public, anon, authenticated;
revoke all on function public.get_email_secret(uuid,uuid) from public, anon, authenticated;
revoke all on function public.store_oauth_state(text,uuid,text,text,text,text[],timestamptz) from public, anon, authenticated;
revoke all on function public.consume_oauth_state(text,text) from public, anon, authenticated;
grant execute on function public.claim_due_searches(text,integer,integer) to service_role;
grant execute on function public.complete_search_run(uuid,uuid,uuid,text,timestamptz,integer,text) to service_role;
grant execute on function public.claim_application_send(uuid,uuid,boolean,text) to service_role;
grant execute on function public.store_email_secret(uuid,uuid,text,text) to service_role;
grant execute on function public.get_email_secret(uuid,uuid) to service_role;
grant execute on function public.store_oauth_state(text,uuid,text,text,text,text[],timestamptz) to service_role;
grant execute on function public.consume_oauth_state(text,text) to service_role;
revoke all on function public.valid_timezone(text), public.valid_weekdays(integer[]) from public, anon;
grant execute on function public.valid_timezone(text), public.valid_weekdays(integer[]) to authenticated, service_role;
-- ===== FIN MIGRACIÓN: 202610120001_initial.sql =====

-- ===== INICIO MIGRACIÓN: 202610120002_manual_search.sql =====
-- La ejecución manual conserva las mismas garantías de exclusión que el scheduler.
create function public.claim_search_now(
  p_search_id uuid, p_user_id uuid, p_worker_id text, p_lease_seconds integer default 300
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare search_row public.job_searches%rowtype; new_token uuid; new_run_id uuid;
begin
  if nullif(btrim(p_worker_id), '') is null or p_lease_seconds not between 30 and 3600 then
    raise exception 'Parámetros de claim inválidos';
  end if;
  select * into search_row from public.job_searches
    where id = p_search_id and user_id = p_user_id
      and (lease_expires_at is null or lease_expires_at <= now())
    for update skip locked;
  if not found then return null; end if;
  if search_row.claim_token is not null then
    update public.job_search_runs set status = 'error', finished_at = now(),
      message = 'El worker perdió su lease; no se confirmó la ejecución.'
      where claim_token = search_row.claim_token and status = 'running';
  end if;
  new_token := gen_random_uuid(); new_run_id := gen_random_uuid();
  update public.job_searches set claim_token = new_token,
    lease_expires_at = now() + make_interval(secs => p_lease_seconds)
    where id = p_search_id returning * into search_row;
  insert into public.job_search_runs(id,user_id,search_id,claim_token,worker_id)
    values (new_run_id,search_row.user_id,p_search_id,new_token,p_worker_id);
  return to_jsonb(search_row) || jsonb_build_object('run_id',new_run_id);
end;
$$;
revoke all on function public.claim_search_now(uuid,uuid,text,integer) from public, anon, authenticated;
grant execute on function public.claim_search_now(uuid,uuid,text,integer) to service_role;
-- ===== FIN MIGRACIÓN: 202610120002_manual_search.sql =====

-- ===== INICIO MIGRACIÓN: 202610120003_claim_fencing.sql =====
-- El servidor puede comprobar su lease antes de insertar resultados o enviar.
-- Esta comprobación debe repetirse antes de cada efecto externo; no prolonga la lease.
create function public.assert_search_claim(p_search_id uuid, p_claim_token uuid)
returns boolean language sql security definer set search_path = '' as $$
  select exists (
    select 1 from public.job_searches
    where id = p_search_id and claim_token = p_claim_token and lease_expires_at > now()
  )
$$;
revoke all on function public.assert_search_claim(uuid,uuid) from public, anon, authenticated;
grant execute on function public.assert_search_claim(uuid,uuid) to service_role;

-- Una edición del usuario posterior al inicio conserva el next_run_at recalculado.
-- El timestamp inicial del claim y started_at coinciden por now() transaccional;
-- el backend debe recalcular next_run_at en el mismo PATCH que cambia horario.
create or replace function public.complete_search_run(
  p_search_id uuid, p_claim_token uuid, p_run_id uuid, p_status text,
  p_next_run_at timestamptz, p_found_count integer default 0, p_message text default null
) returns boolean
language plpgsql security definer set search_path = '' as $$
declare search_row public.job_searches%rowtype; run_row public.job_search_runs%rowtype;
begin
  if p_status not in ('completed','error','blocked') or p_found_count < 0 or
     p_next_run_at is null or p_next_run_at <= now() then
    raise exception 'Resultado o próxima ejecución inválidos';
  end if;
  select * into search_row from public.job_searches where id = p_search_id for update;
  if not found or search_row.claim_token is distinct from p_claim_token or
     search_row.lease_expires_at is null or search_row.lease_expires_at <= now() then return false; end if;
  select * into run_row from public.job_search_runs
    where id = p_run_id and search_id = p_search_id and claim_token = p_claim_token and status = 'running'
    for update;
  if not found then return false; end if;
  update public.job_search_runs set status = p_status, finished_at = now(),
    found_count = p_found_count, message = p_message where id = p_run_id;
  update public.job_searches set
    next_run_at = case when search_row.updated_at > run_row.started_at then search_row.next_run_at else p_next_run_at end,
    last_run_at = case when p_status = 'completed' then now() else search_row.last_run_at end,
    claim_token = null, lease_expires_at = null
    where id = p_search_id;
  return true;
end;
$$;
revoke all on function public.complete_search_run(uuid,uuid,uuid,text,timestamptz,integer,text) from public, anon, authenticated;
grant execute on function public.complete_search_run(uuid,uuid,uuid,text,timestamptz,integer,text) to service_role;
-- ===== FIN MIGRACIÓN: 202610120003_claim_fencing.sql =====

-- ===== INICIO MIGRACIÓN: 202610120004_automatic_sending_policy.sql =====
-- Las autorizaciones, su revocación y las reservas de envío se serializan por
-- búsqueda. El servidor prepara borradores antiguos con la autorización vigente;
-- ni preparar ni reservar significan que el proveedor haya enviado el correo.
create function public.grant_sending_consent(
  p_user_id uuid, p_search_id uuid, p_resume_id uuid, p_email_connection_id uuid,
  p_authorized_sources text[], p_expires_at timestamptz, p_authorization_text text
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare search_row public.job_searches%rowtype; consent_row public.sending_consents%rowtype;
begin
  if p_user_id is null or p_search_id is null or p_resume_id is null or
     p_email_connection_id is null or p_authorization_text is distinct from
       'Autorizo los envíos automáticos de esta búsqueda' or
     p_expires_at is null or p_expires_at <= now() or
     p_expires_at > now() + interval '90 days' or
     p_authorized_sources is null or cardinality(p_authorized_sources) not between 1 and 20 or
     exists (select 1 from unnest(p_authorized_sources) as source
       where nullif(btrim(source), '') is null) then
    raise exception 'Autorización de envío inválida';
  end if;
  select * into search_row from public.job_searches
    where id = p_search_id and user_id = p_user_id for update;
  if not found then raise exception 'La búsqueda no pertenece al usuario'; end if;
  perform 1 from public.resume_versions
    where id = p_resume_id and user_id = p_user_id for share;
  if not found then raise exception 'El CV no pertenece al usuario'; end if;
  perform 1 from public.email_connections where id = p_email_connection_id
    and user_id = p_user_id and provider = 'google' and status = 'connected'
    and revoked_at is null and
    'https://www.googleapis.com/auth/gmail.send' = any(scopes) for share;
  if not found then raise exception 'Conectá Gmail con permiso de envío'; end if;
  update public.sending_consents set revoked_at = now()
    where user_id = p_user_id and search_id = p_search_id and revoked_at is null;
  insert into public.sending_consents(user_id, search_id, resume_id,
    email_connection_id, authorized_sources, daily_limit, expires_at,
    authorization_text, policy_version)
    values (p_user_id, p_search_id, p_resume_id, p_email_connection_id,
      array(select distinct source from unnest(p_authorized_sources) as source order by source),
      10, p_expires_at, p_authorization_text, 'v2')
    returning * into consent_row;
  update public.job_searches set auto_apply = true, consent_id = consent_row.id,
    preferred_resume_id = p_resume_id where id = p_search_id returning * into search_row;
  return jsonb_build_object('consent', to_jsonb(consent_row), 'search', to_jsonb(search_row));
end;
$$;

-- Mantener el mismo orden de locks que el alta y el envío: búsqueda, consentimiento.
create or replace function public.revoke_sending_consent(p_consent_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
declare owner_id uuid := auth.uid(); target_search_id uuid;
begin
  if owner_id is null then return false; end if;
  select search_id into target_search_id from public.sending_consents
    where id = p_consent_id and user_id = owner_id;
  if not found then return false; end if;
  perform 1 from public.job_searches
    where id = target_search_id and user_id = owner_id for update;
  if not found then return false; end if;
  update public.sending_consents set revoked_at = coalesce(revoked_at, now())
    where id = p_consent_id and user_id = owner_id;
  if not found then return false; end if;
  update public.job_searches set auto_apply = false
    where id = target_search_id and user_id = owner_id and consent_id = p_consent_id;
  return true;
end;
$$;

create function public.prepare_automatic_application(p_application_id uuid, p_user_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare app_row public.applications%rowtype; job_row public.jobs%rowtype;
  search_row public.job_searches%rowtype; consent_row public.sending_consents%rowtype;
begin
  select * into app_row from public.applications
    where id = p_application_id and user_id = p_user_id for update;
  if not found or app_row.status <> 'pending' or app_row.send_attempt_id is not null or
     app_row.delivery_uncertain is distinct from false or
     app_row.recipient_verified_at is null or
     nullif(btrim(app_row.recipient_email), '') is null then return null; end if;
  select * into search_row from public.job_searches
    where id = app_row.search_id and user_id = p_user_id for update;
  if not found or search_row.status <> 'enabled' or
     search_row.auto_apply is distinct from true then return null; end if;
  select * into consent_row from public.sending_consents
    where id = search_row.consent_id and user_id = p_user_id for update;
  if not found or consent_row.search_id is distinct from app_row.search_id or
     consent_row.revoked_at is not null or consent_row.expires_at <= now() or
     consent_row.resume_id is null or consent_row.daily_limit not between 1 and 10 or
     consent_row.authorization_text is distinct from
       'Autorizo los envíos automáticos de esta búsqueda' then return null; end if;
  select * into job_row from public.jobs
    where id = app_row.job_id and user_id = p_user_id for share;
  if not found or job_row.source_authorized is distinct from true or
     job_row.recipient_verified_at is null or
     job_row.recipient_email is distinct from app_row.recipient_email or
     (job_row.source = any(consent_row.authorized_sources)) is distinct from true then
    return null;
  end if;
  perform 1 from public.resume_versions
    where id = consent_row.resume_id and user_id = p_user_id for share;
  if not found then return null; end if;
  perform 1 from public.email_connections where id = consent_row.email_connection_id
    and user_id = p_user_id and provider = 'google' and status = 'connected'
    and revoked_at is null and
    'https://www.googleapis.com/auth/gmail.send' = any(scopes) for share;
  if not found then return null; end if;
  update public.applications set resume_id = consent_row.resume_id,
    email_connection_id = consent_row.email_connection_id
    where id = p_application_id returning * into app_row;
  return to_jsonb(app_row);
end;
$$;

create or replace function public.claim_application_send(
  p_application_id uuid, p_user_id uuid, p_explicit_manual_consent boolean default false,
  p_manual_approval_text text default null
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare app_row public.applications%rowtype; job_row public.jobs%rowtype;
  search_row public.job_searches%rowtype; consent_row public.sending_consents%rowtype;
  attempted_today integer; local_day_start timestamptz; local_day_end timestamptz;
begin
  -- Un NULL no puede sustituir la elección entre consentimiento manual y automático.
  if p_explicit_manual_consent is null then return null; end if;
  if p_explicit_manual_consent and p_manual_approval_text is distinct from 'Enviar esta postulación' then
    raise exception 'La aprobación manual debe ser: Enviar esta postulación';
  end if;
  select * into app_row from public.applications
    where id = p_application_id and user_id = p_user_id for update;
  if not found or app_row.status not in ('pending','error') or
     app_row.send_attempt_id is not null or app_row.delivery_uncertain is distinct from false or
     app_row.recipient_verified_at is null or app_row.email_connection_id is null or
     nullif(btrim(app_row.recipient_email), '') is null then return null; end if;
  select * into job_row from public.jobs
    where id = app_row.job_id and user_id = p_user_id for share;
  if not found or job_row.source_authorized is distinct from true or
     job_row.recipient_verified_at is null or
     job_row.recipient_email is distinct from app_row.recipient_email then return null; end if;
  perform 1 from public.resume_versions
    where id = app_row.resume_id and user_id = p_user_id for share;
  if not found then return null; end if;
  if not p_explicit_manual_consent then
    select * into search_row from public.job_searches
      where id = app_row.search_id and user_id = p_user_id for update;
    if not found or search_row.auto_apply is distinct from true or
       search_row.status <> 'enabled' then return null; end if;
    select * into consent_row from public.sending_consents
      where id = search_row.consent_id and user_id = p_user_id for update;
    if not found or consent_row.search_id is distinct from app_row.search_id or
       consent_row.revoked_at is not null or consent_row.expires_at <= now() or
       (job_row.source = any(consent_row.authorized_sources)) is distinct from true or
       consent_row.email_connection_id is distinct from app_row.email_connection_id or
       consent_row.resume_id is null or consent_row.resume_id is distinct from app_row.resume_id or
       consent_row.daily_limit not between 1 and 10 or
       consent_row.authorization_text is distinct from
         'Autorizo los envíos automáticos de esta búsqueda' then return null; end if;
    local_day_start := (now() at time zone search_row.timezone)::date::timestamp at time zone search_row.timezone;
    local_day_end := ((now() at time zone search_row.timezone)::date + 1)::timestamp at time zone search_row.timezone;
    select count(*) into attempted_today from public.applications
      where user_id = p_user_id and search_id = app_row.search_id and manual_approved_at is null
        and send_attempt_started_at >= local_day_start and send_attempt_started_at < local_day_end;
    if attempted_today >= consent_row.daily_limit then return null; end if;
  end if;
  perform 1 from public.email_connections where id = app_row.email_connection_id
    and user_id = p_user_id and provider = 'google' and status = 'connected'
    and revoked_at is null and
    'https://www.googleapis.com/auth/gmail.send' = any(scopes) for share;
  if not found then return null; end if;
  update public.applications set send_attempt_id = gen_random_uuid(), send_attempt_started_at = now(),
    manual_approved_at = case when p_explicit_manual_consent then now() else null end,
    manual_approval_text = case when p_explicit_manual_consent then p_manual_approval_text else null end,
    error = null, status = 'pending'
    where id = p_application_id returning * into app_row;
  return to_jsonb(app_row);
end;
$$;

-- Alta/revocación también cambian updated_at mientras un worker trabaja. Solo
-- conservar next_run_at si una edición ya dejó una próxima fecha futura; nunca
-- conservar una fecha vencida que volvería a reclamar la búsqueda inmediatamente.
create or replace function public.complete_search_run(
  p_search_id uuid, p_claim_token uuid, p_run_id uuid, p_status text,
  p_next_run_at timestamptz, p_found_count integer default 0, p_message text default null
) returns boolean
language plpgsql security definer set search_path = '' as $$
declare search_row public.job_searches%rowtype; run_row public.job_search_runs%rowtype;
begin
  if p_status not in ('completed','error','blocked') or p_found_count < 0 or
     p_next_run_at is null or p_next_run_at <= now() then
    raise exception 'Resultado o próxima ejecución inválidos';
  end if;
  select * into search_row from public.job_searches where id = p_search_id for update;
  if not found or search_row.claim_token is distinct from p_claim_token or
     search_row.lease_expires_at is null or search_row.lease_expires_at <= now() then return false; end if;
  select * into run_row from public.job_search_runs
    where id = p_run_id and search_id = p_search_id and claim_token = p_claim_token and status = 'running'
    for update;
  if not found then return false; end if;
  update public.job_search_runs set status = p_status, finished_at = now(),
    found_count = p_found_count, message = p_message where id = p_run_id;
  update public.job_searches set
    next_run_at = case when search_row.updated_at > run_row.started_at and search_row.next_run_at > now()
      then search_row.next_run_at else p_next_run_at end,
    last_run_at = case when p_status = 'completed' then now() else search_row.last_run_at end,
    claim_token = null, lease_expires_at = null
    where id = p_search_id;
  return true;
end;
$$;

revoke all on function public.grant_sending_consent(uuid,uuid,uuid,uuid,text[],timestamptz,text)
  from public, anon, authenticated;
revoke all on function public.prepare_automatic_application(uuid,uuid) from public, anon, authenticated;
revoke all on function public.claim_application_send(uuid,uuid,boolean,text) from public, anon, authenticated;
grant execute on function public.grant_sending_consent(uuid,uuid,uuid,uuid,text[],timestamptz,text) to service_role;
grant execute on function public.prepare_automatic_application(uuid,uuid) to service_role;
grant execute on function public.claim_application_send(uuid,uuid,boolean,text) to service_role;
-- ===== FIN MIGRACIÓN: 202610120004_automatic_sending_policy.sql =====

-- ===== INICIO MIGRACIÓN: 202610120005_daily_budget_and_followups.sql =====
-- Trabajo YA: presupuesto GLOBAL de 10 reservas/día y recordatorios con evidencia
-- nueva. Una reserva NO equivale a un envío. Nunca reciclar intentos ni historial.
alter table public.profiles add column sending_timezone text not null
  default 'America/Argentina/Buenos_Aires' check (sending_timezone = 'America/Argentina/Buenos_Aires');
create function private.freeze_sending_timezone() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.sending_timezone is distinct from old.sending_timezone then
    raise exception 'La zona del presupuesto diario es fija; no depende de las búsquedas';
  end if;
  return new;
end;
$$;
create trigger freeze_sending_timezone before update on public.profiles
  for each row execute function private.freeze_sending_timezone();

alter table public.sending_consents add column repeat_enabled boolean not null default false;
alter table public.sending_consents add column repeat_interval_days integer not null default 3
  check (repeat_interval_days = 3);
alter table public.sending_consents add constraint repeats_require_v3
  check (not repeat_enabled or (policy_version = 'v3' and authorization_text =
    'Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día'));
alter table public.jobs add column is_active boolean not null default true;
alter table public.jobs add column last_seen_at timestamptz;
alter table public.job_search_runs add constraint search_run_owner_key unique (user_id, search_id, id);

-- Solo el servidor registra un match DESPUÉS de consultar la fuente autorizada.
-- La lease, el run y los criterios vigentes deben coincidir: no se confía en flags
-- enviados por Android ni se reutiliza el resultado de un run anterior.
create table public.job_search_matches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  search_id uuid not null,
  run_id uuid not null,
  observed_at timestamptz not null default now(),
  roles_snapshot text[] not null,
  cities_snapshot text[] not null,
  unique (user_id, id),
  unique (user_id, job_id, search_id, run_id),
  foreign key (user_id, job_id) references public.jobs(user_id, id) on delete cascade,
  foreign key (user_id, search_id) references public.job_searches(user_id, id) on delete cascade,
  foreign key (user_id, search_id, run_id) references public.job_search_runs(user_id, search_id, id) on delete cascade
);
alter table public.job_search_matches enable row level security;
create policy own_read on public.job_search_matches for select to authenticated using (user_id = (select auth.uid()));
revoke all on public.job_search_matches from public, anon, authenticated;
grant select on public.job_search_matches to authenticated;
grant select, insert, delete on public.job_search_matches to service_role;
create index job_match_lookup on public.job_search_matches(user_id, job_id, search_id, observed_at desc);
create function private.validate_fresh_match() returns trigger
language plpgsql set search_path = '' as $$
declare s public.job_searches%rowtype; r public.job_search_runs%rowtype; j public.jobs%rowtype;
begin
  select * into s from public.job_searches where id = new.search_id and user_id = new.user_id for share;
  select * into r from public.job_search_runs where id = new.run_id and user_id = new.user_id and search_id = new.search_id;
  select * into j from public.jobs where id = new.job_id and user_id = new.user_id;
  if s.id is null or r.id is null or j.id is null or s.claim_token is distinct from r.claim_token or
     s.lease_expires_at is null or s.lease_expires_at <= now() or r.status <> 'running' or
     new.roles_snapshot is distinct from s.roles or new.cities_snapshot is distinct from s.cities or
     j.source_authorized is distinct from true or j.is_active is distinct from true or
     new.observed_at < r.started_at or new.observed_at > now() or new.observed_at < now() - interval '1 hour' then
    raise exception 'La evidencia no corresponde a una consulta vigente y autorizada';
  end if;
  return new;
end;
$$;
create trigger validate_fresh_match before insert on public.job_search_matches
  for each row execute function private.validate_fresh_match();

alter table public.applications drop constraint applications_user_id_job_id_key;
alter table public.applications add constraint applications_owner_key unique (user_id, id);
alter table public.applications add column parent_application_id uuid;
alter table public.applications add column delivery_sequence integer not null default 0;
alter table public.applications add column job_match_id uuid;
alter table public.applications add column sending_consent_id uuid;
alter table public.applications add column sender_email text;
alter table public.applications add constraint application_parent_owner
  foreign key (user_id, parent_application_id) references public.applications(user_id, id) on delete cascade;
alter table public.applications add constraint application_match_owner
  foreign key (user_id, job_match_id) references public.job_search_matches(user_id, id) deferrable initially deferred;
alter table public.applications add constraint application_consent_owner
  foreign key (user_id, sending_consent_id) references public.sending_consents(user_id, id) deferrable initially deferred;
alter table public.applications add constraint application_delivery_shape
  check ((parent_application_id is null and delivery_sequence = 0) or
         (parent_application_id is not null and delivery_sequence > 0 and parent_application_id <> id));
create unique index applications_initial_job on public.applications(user_id, job_id) where parent_application_id is null;
create unique index applications_followup_sequence on public.applications(user_id, parent_application_id, delivery_sequence)
  where parent_application_id is not null;
create index applications_global_daily_attempts on public.applications(user_id, send_attempt_started_at)
  where send_attempt_id is not null;
create index applications_recipient_history on public.applications(user_id, lower(btrim(recipient_email)), provider_confirmed_at desc);

-- El mensaje, el CV, el destinatario y el intento reservado forman evidencia
-- histórica. Solo se puede añadir resultado/recibo; ningún envío se resetea.
create function private.preserve_delivery_evidence() returns trigger
language plpgsql set search_path = '' as $$
declare root_row public.applications%rowtype;
begin
  if tg_op = 'UPDATE' and old.send_attempt_id is not null then
    if row(new.user_id,new.job_id,new.search_id,new.resume_id,new.email_connection_id,
      new.company,new.job_title,new.recipient_email,new.recipient_verified_at,new.subject,new.body,
      new.parent_application_id,new.delivery_sequence,new.job_match_id,new.sending_consent_id,new.sender_email,
      new.send_attempt_id,new.send_attempt_started_at,new.manual_approved_at,new.manual_approval_text)
      is distinct from row(old.user_id,old.job_id,old.search_id,old.resume_id,old.email_connection_id,
      old.company,old.job_title,old.recipient_email,old.recipient_verified_at,old.subject,old.body,
      old.parent_application_id,old.delivery_sequence,old.job_match_id,old.sending_consent_id,old.sender_email,
      old.send_attempt_id,old.send_attempt_started_at,old.manual_approved_at,old.manual_approval_text) then
      raise exception 'No se puede modificar ni reutilizar una entrega reservada';
    end if;
    if old.delivery_uncertain and not new.delivery_uncertain and new.provider_confirmed_at is null then
      raise exception 'La entrega incierta exige conciliación con evidencia del proveedor';
    end if;
    if old.provider_confirmed_at is not null and row(new.provider_message_id,new.provider_confirmed_at,new.sent_at)
       is distinct from row(old.provider_message_id,old.provider_confirmed_at,old.sent_at) then
      raise exception 'El recibo de una entrega confirmada es inmutable';
    end if;
    if old.status in ('sent','responded') and (new.status not in ('sent','responded') or
       (old.status = 'responded' and new.status <> 'responded')) then
      raise exception 'No se puede borrar un envío confirmado o una respuesta';
    end if;
  end if;
  if new.parent_application_id is not null then
    select * into root_row from public.applications where id = new.parent_application_id and user_id = new.user_id;
    if root_row.id is null or root_row.parent_application_id is not null or
       root_row.job_id is distinct from new.job_id or root_row.search_id is distinct from new.search_id or
       lower(btrim(root_row.recipient_email)) is distinct from lower(btrim(new.recipient_email)) or
       root_row.provider_confirmed_at is null then
      raise exception 'Un recordatorio debe pertenecer a la postulación inicial confirmada';
    end if;
  end if;
  return new;
end;
$$;
create trigger preserve_delivery_evidence before insert or update on public.applications
  for each row execute function private.preserve_delivery_evidence();

-- Detener recordatorios para una dirección afecta todas las búsquedas del usuario.
create table public.recipient_suppressions (
  user_id uuid not null references auth.users(id) on delete cascade,
  recipient_email text not null check (recipient_email = lower(btrim(recipient_email)) and length(recipient_email)>0),
  stopped_at timestamptz not null default now(),
  reason text not null check (reason in ('user_request','responded')),
  primary key (user_id,recipient_email)
);
alter table public.recipient_suppressions enable row level security;
create policy own_read on public.recipient_suppressions for select to authenticated using (user_id=(select auth.uid()));
revoke all on public.recipient_suppressions from public,anon,authenticated;
grant select on public.recipient_suppressions to authenticated;
grant select,insert,update,delete on public.recipient_suppressions to service_role;

-- Las referencias al CV conservan también los bytes de Storage: el usuario
-- puede eliminar documentos libres, pero no borrar/recrear el adjunto histórico
-- en la misma ruta. service_role conserva el borrado completo de la cuenta.
create function private.protect_delivered_resume_object() returns trigger
language plpgsql set search_path = '' as $$
begin
  if current_user='authenticated' and old.bucket_id='resumes' then
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(auth.uid()::text,0));
    if exists (select 1 from public.resume_versions r join public.applications a
      on a.resume_id=r.id and a.user_id=r.user_id where r.object_path=old.name) then
      raise exception 'El CV asociado al historial no puede eliminarse ni reemplazarse';
    end if;
  end if;
  return old;
end;
$$;
create trigger protect_delivered_resume_object before delete on storage.objects
  for each row execute function private.protect_delivered_resume_object();

-- Debe llamarse mientras se posee el advisory lock por usuario. Cuenta también
-- errores, reservas no finalizadas, recordatorios y aprobaciones manuales.
create function private.delivery_budget_available(p_user_id uuid, p_recipient_email text, p_followup boolean)
returns boolean language plpgsql stable set search_path = '' as $$
declare tz text; day_start timestamptz; day_end timestamptz; used_count integer;
begin
  select sending_timezone into tz from public.profiles where user_id = p_user_id;
  if tz is null or nullif(btrim(p_recipient_email),'') is null then return false; end if;
  day_start := (now() at time zone tz)::date::timestamp at time zone tz;
  day_end := ((now() at time zone tz)::date + 1)::timestamp at time zone tz;
  select count(*) into used_count from public.applications where user_id = p_user_id
    and send_attempt_started_at >= day_start and send_attempt_started_at < day_end;
  if used_count >= 10 then return false; end if;
  if p_followup and exists (select 1 from public.recipient_suppressions where user_id=p_user_id
    and recipient_email=lower(btrim(p_recipient_email))) then return false; end if;
  if exists (select 1 from public.applications where user_id = p_user_id
    and lower(btrim(recipient_email)) = lower(btrim(p_recipient_email)) and
      ((send_attempt_id is not null and provider_confirmed_at is null and
        (p_followup or status = 'pending' or delivery_uncertain)) or
       provider_confirmed_at > now() - interval '72 hours' or
       (p_followup and status = 'responded'))) then return false; end if;
  return true;
end;
$$;

create function private.current_job_match(p_user_id uuid, p_job_id uuid, p_search_id uuid)
returns uuid language sql stable set search_path = '' as $$
  select m.id from public.job_search_matches m
    join public.job_searches s on s.id=m.search_id and s.user_id=m.user_id
    join public.job_search_runs r on r.id=m.run_id and r.search_id=s.id and r.user_id=s.user_id
    join public.jobs j on j.id=m.job_id and j.user_id=m.user_id
  where m.user_id=p_user_id and m.job_id=p_job_id and m.search_id=p_search_id
    and r.status='running' and s.claim_token=r.claim_token and s.lease_expires_at > now()
    and m.roles_snapshot=s.roles and m.cities_snapshot=s.cities
    and m.observed_at >= r.started_at and m.observed_at >= now()-interval '1 hour' and m.observed_at <= now()
    and j.source_authorized and j.is_active
  order by m.observed_at desc limit 1
$$;

-- La firma anterior se amplía con default false. Los permisos existentes v2 NO
-- se convierten en v3: el usuario debe aprobar el texto nuevo explícitamente.
drop function public.grant_sending_consent(uuid,uuid,uuid,uuid,text[],timestamptz,text);
create function public.grant_sending_consent(
  p_user_id uuid, p_search_id uuid, p_resume_id uuid, p_email_connection_id uuid,
  p_authorized_sources text[], p_expires_at timestamptz, p_authorization_text text,
  p_repeat_enabled boolean default false
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare s public.job_searches%rowtype; c public.sending_consents%rowtype; expected_text text;
begin
  expected_text := case when p_repeat_enabled then
    'Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día'
    else 'Autorizo los envíos automáticos de esta búsqueda' end;
  if p_user_id is null or p_search_id is null or p_resume_id is null or p_email_connection_id is null or
     p_repeat_enabled is null or p_authorization_text is distinct from expected_text or
     p_expires_at is null or p_expires_at <= now() or p_expires_at > now()+interval '90 days' or
     p_authorized_sources is null or cardinality(p_authorized_sources) not between 1 and 20 or
     exists (select 1 from unnest(p_authorized_sources) as source where nullif(btrim(source),'') is null) then
    raise exception 'Autorización de envío inválida';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_user_id::text, 0));
  select * into s from public.job_searches where id=p_search_id and user_id=p_user_id for update;
  if not found then raise exception 'La búsqueda no pertenece al usuario'; end if;
  perform 1 from public.resume_versions where id=p_resume_id and user_id=p_user_id for share;
  if not found then raise exception 'El CV no pertenece al usuario'; end if;
  perform 1 from public.email_connections where id=p_email_connection_id and user_id=p_user_id
    and provider='google' and status='connected' and revoked_at is null
    and 'https://www.googleapis.com/auth/gmail.send'=any(scopes) for share;
  if not found then raise exception 'Conectá Gmail con permiso de envío'; end if;
  update public.sending_consents set revoked_at=now() where user_id=p_user_id and search_id=p_search_id and revoked_at is null;
  insert into public.sending_consents(user_id,search_id,resume_id,email_connection_id,authorized_sources,daily_limit,
    expires_at,authorization_text,policy_version,repeat_enabled,repeat_interval_days)
  values (p_user_id,p_search_id,p_resume_id,p_email_connection_id,
    array(select distinct source from unnest(p_authorized_sources) as source order by source),10,p_expires_at,
    p_authorization_text,case when p_repeat_enabled then 'v3' else 'v2' end,p_repeat_enabled,3) returning * into c;
  update public.job_searches set auto_apply=true,consent_id=c.id,preferred_resume_id=p_resume_id
    where id=p_search_id returning * into s;
  return jsonb_build_object('consent',to_jsonb(c),'search',to_jsonb(s));
end;
$$;
create or replace function public.revoke_sending_consent(p_consent_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
declare owner_id uuid:=auth.uid(); target_search_id uuid;
begin
  if owner_id is null then return false; end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(owner_id::text,0));
  select search_id into target_search_id from public.sending_consents where id=p_consent_id and user_id=owner_id;
  if not found then return false; end if;
  perform 1 from public.job_searches where id=target_search_id and user_id=owner_id for update;
  if not found then return false; end if;
  update public.sending_consents set revoked_at=coalesce(revoked_at,now()) where id=p_consent_id and user_id=owner_id;
  update public.job_searches set auto_apply=false where id=target_search_id and user_id=owner_id and consent_id=p_consent_id;
  return true;
end;
$$;

create or replace function public.prepare_automatic_application(p_application_id uuid,p_user_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare a public.applications%rowtype; j public.jobs%rowtype; s public.job_searches%rowtype;
  c public.sending_consents%rowtype; match_id uuid;
begin
  if p_user_id is null then return null; end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_user_id::text,0));
  select * into a from public.applications where id=p_application_id and user_id=p_user_id for update;
  if not found or a.status<>'pending' or a.send_attempt_id is not null or a.delivery_uncertain then return null; end if;
  select * into s from public.job_searches where id=a.search_id and user_id=p_user_id for update;
  if not found or s.status<>'enabled' or not s.auto_apply then return null; end if;
  select * into c from public.sending_consents where id=s.consent_id and user_id=p_user_id for update;
  if not found or c.search_id is distinct from a.search_id or c.revoked_at is not null or c.expires_at<=now() or
     c.resume_id is null or c.daily_limit not between 1 and 10 or
     (c.policy_version='v2' and c.authorization_text is distinct from 'Autorizo los envíos automáticos de esta búsqueda') or
     (c.policy_version='v3' and (not c.repeat_enabled or c.authorization_text is distinct from
       'Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día')) or
     c.policy_version not in ('v2','v3') or
     (a.parent_application_id is not null and (c.policy_version<>'v3' or not c.repeat_enabled)) then return null; end if;
  select * into j from public.jobs where id=a.job_id and user_id=p_user_id for share;
  if not found or not j.source_authorized or not j.is_active or j.recipient_verified_at is null or
     a.recipient_verified_at is null or nullif(btrim(a.recipient_email),'') is null or
     lower(btrim(j.recipient_email)) is distinct from lower(btrim(a.recipient_email)) or (j.source=any(c.authorized_sources)) is distinct from true then return null; end if;
  match_id:=private.current_job_match(p_user_id,a.job_id,a.search_id);
  if match_id is null then return null; end if;
  perform 1 from public.resume_versions where id=c.resume_id and user_id=p_user_id for share;
  if not found then return null; end if;
  perform 1 from public.email_connections where id=c.email_connection_id and user_id=p_user_id and provider='google'
    and status='connected' and revoked_at is null and 'https://www.googleapis.com/auth/gmail.send'=any(scopes) for share;
  if not found then return null; end if;
  update public.applications set resume_id=c.resume_id,email_connection_id=c.email_connection_id,job_match_id=match_id
    where id=a.id returning * into a;
  return to_jsonb(a);
end;
$$;

create or replace function public.claim_application_send(
  p_application_id uuid,p_user_id uuid,p_explicit_manual_consent boolean default false,p_manual_approval_text text default null
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare a public.applications%rowtype; j public.jobs%rowtype; s public.job_searches%rowtype;
  c public.sending_consents%rowtype; e public.email_connections%rowtype; match_id uuid;
  local_day_start timestamptz; local_day_end timestamptz; tz text; consent_attempts integer;
begin
  if p_user_id is null or p_explicit_manual_consent is null then return null; end if;
  if p_explicit_manual_consent and p_manual_approval_text is distinct from 'Enviar esta postulación' then
    raise exception 'La aprobación manual debe ser: Enviar esta postulación';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_user_id::text,0));
  select * into a from public.applications where id=p_application_id and user_id=p_user_id for update;
  if not found or a.status not in ('pending','error') or a.send_attempt_id is not null or a.delivery_uncertain or
     a.recipient_verified_at is null or a.email_connection_id is null or nullif(btrim(a.recipient_email),'') is null then return null; end if;
  if not private.delivery_budget_available(p_user_id,a.recipient_email,a.parent_application_id is not null) then return null; end if;
  select * into j from public.jobs where id=a.job_id and user_id=p_user_id for share;
  if not found or not j.source_authorized or not j.is_active or j.recipient_verified_at is null or
     lower(btrim(j.recipient_email)) is distinct from lower(btrim(a.recipient_email)) then return null; end if;
  perform 1 from public.resume_versions where id=a.resume_id and user_id=p_user_id for share;
  if not found then return null; end if;
  if not p_explicit_manual_consent then
    select * into s from public.job_searches where id=a.search_id and user_id=p_user_id for update;
    if not found or not s.auto_apply or s.status<>'enabled' then return null; end if;
    select * into c from public.sending_consents where id=s.consent_id and user_id=p_user_id for update;
    if not found or c.search_id is distinct from a.search_id or c.revoked_at is not null or c.expires_at<=now() or
       (j.source=any(c.authorized_sources)) is distinct from true or c.resume_id is distinct from a.resume_id or
       c.email_connection_id is distinct from a.email_connection_id or c.daily_limit not between 1 and 10 or
       c.policy_version not in ('v2','v3') or
       (c.policy_version='v2' and c.authorization_text is distinct from 'Autorizo los envíos automáticos de esta búsqueda') or
       (c.policy_version='v3' and (not c.repeat_enabled or c.authorization_text is distinct from
         'Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día')) or
       (a.parent_application_id is not null and (c.policy_version<>'v3' or not c.repeat_enabled)) then return null; end if;
    match_id:=private.current_job_match(p_user_id,a.job_id,a.search_id);
    if match_id is null or match_id is distinct from a.job_match_id then return null; end if;
    -- Un permiso con límite menor conserva su restricción, además del techo global.
    select sending_timezone into tz from public.profiles where user_id=p_user_id;
    local_day_start:=(now() at time zone tz)::date::timestamp at time zone tz;
    local_day_end:=((now() at time zone tz)::date+1)::timestamp at time zone tz;
    select count(*) into consent_attempts from public.applications where user_id=p_user_id and search_id=a.search_id
      and send_attempt_started_at>=local_day_start and send_attempt_started_at<local_day_end;
    if consent_attempts>=c.daily_limit then return null; end if;
  end if;
  select * into e from public.email_connections where id=a.email_connection_id and user_id=p_user_id
    and provider='google' and status='connected' and revoked_at is null
    and 'https://www.googleapis.com/auth/gmail.send'=any(scopes) for share;
  if not found then return null; end if;
  update public.applications set send_attempt_id=gen_random_uuid(),send_attempt_started_at=now(),
    manual_approved_at=case when p_explicit_manual_consent then now() else null end,
    manual_approval_text=case when p_explicit_manual_consent then p_manual_approval_text else null end,
    sending_consent_id=case when p_explicit_manual_consent then null else c.id end,
    sender_email=e.email,error=null,status='pending' where id=a.id returning * into a;
  return to_jsonb(a);
end;
$$;

-- Idempotencia de la postulación inicial sin depender de un ON CONFLICT sobre
-- la antigua restricción (ahora un índice parcial).
create function public.create_initial_application(p_application jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare a public.applications%rowtype; owner_id uuid:=(p_application->>'user_id')::uuid;
  target_job uuid:=(p_application->>'job_id')::uuid;
begin
  if owner_id is null or target_job is null then raise exception 'Postulación inicial inválida'; end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(owner_id::text,0));
  select * into a from public.applications where user_id=owner_id and job_id=target_job and parent_application_id is null;
  if found then return to_jsonb(a); end if;
  insert into public.applications(id,user_id,job_id,search_id,resume_id,email_connection_id,company,job_title,
    recipient_email,recipient_verified_at,subject,body,job_match_id)
  values (coalesce((p_application->>'id')::uuid,gen_random_uuid()),owner_id,target_job,
    (p_application->>'search_id')::uuid,(p_application->>'resume_id')::uuid,(p_application->>'email_connection_id')::uuid,
    p_application->>'company',p_application->>'job_title',p_application->>'recipient_email',
    (p_application->>'recipient_verified_at')::timestamptz,p_application->>'subject',p_application->>'body',
    (p_application->>'job_match_id')::uuid) returning * into a;
  return to_jsonb(a);
end;
$$;

create function public.prepare_followup_application(
  p_root_application_id uuid,p_user_id uuid,p_search_id uuid,p_run_id uuid,p_claim_token uuid
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare root_row public.applications%rowtype; a public.applications%rowtype;
  s public.job_searches%rowtype; c public.sending_consents%rowtype; j public.jobs%rowtype;
  match_id uuid; sequence_number integer;
begin
  if p_user_id is null then return null; end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_user_id::text,0));
  select * into root_row from public.applications where id=p_root_application_id and user_id=p_user_id for update;
  if not found or root_row.parent_application_id is not null or root_row.status<>'sent' or
     root_row.provider_confirmed_at is null or root_row.search_id is distinct from p_search_id then return null; end if;
  if not private.delivery_budget_available(p_user_id,root_row.recipient_email,true) then return null; end if;
  select * into s from public.job_searches where id=p_search_id and user_id=p_user_id for update;
  if not found or not s.auto_apply or s.status<>'enabled' or s.claim_token is distinct from p_claim_token or
     s.lease_expires_at is null or s.lease_expires_at<=now() then return null; end if;
  perform 1 from public.job_search_runs where id=p_run_id and user_id=p_user_id and search_id=p_search_id
    and claim_token=p_claim_token and status='running';
  if not found then return null; end if;
  select * into c from public.sending_consents where id=s.consent_id and user_id=p_user_id for update;
  if not found or c.search_id is distinct from p_search_id or c.policy_version<>'v3' or not c.repeat_enabled or
     c.repeat_interval_days<>3 or c.revoked_at is not null or c.expires_at<=now() or c.resume_id is null or
     c.authorization_text is distinct from
       'Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día' then return null; end if;
  select * into j from public.jobs where id=root_row.job_id and user_id=p_user_id for share;
  if not found or not j.source_authorized or not j.is_active or j.recipient_verified_at is null or
     lower(btrim(j.recipient_email)) is distinct from lower(btrim(root_row.recipient_email)) or (j.source=any(c.authorized_sources)) is distinct from true then return null; end if;
  match_id:=private.current_job_match(p_user_id,j.id,p_search_id);
  if match_id is null then return null; end if;
  perform 1 from public.job_search_matches where id=match_id and run_id=p_run_id;
  if not found then return null; end if;
  perform 1 from public.resume_versions where id=c.resume_id and user_id=p_user_id for share;
  if not found then return null; end if;
  perform 1 from public.email_connections where id=c.email_connection_id and user_id=p_user_id and provider='google'
    and status='connected' and revoked_at is null and 'https://www.googleapis.com/auth/gmail.send'=any(scopes) for share;
  if not found then return null; end if;
  select * into a from public.applications where user_id=p_user_id and parent_application_id=root_row.id
    and send_attempt_id is null and status='pending' and not delivery_uncertain order by delivery_sequence limit 1 for update;
  if found then
    update public.applications set resume_id=c.resume_id,email_connection_id=c.email_connection_id,job_match_id=match_id
      where id=a.id returning * into a;
    return to_jsonb(a);
  end if;
  select coalesce(max(delivery_sequence),0)+1 into sequence_number from public.applications
    where user_id=p_user_id and parent_application_id=root_row.id;
  insert into public.applications(user_id,job_id,search_id,resume_id,email_connection_id,company,job_title,
    recipient_email,recipient_verified_at,subject,body,parent_application_id,delivery_sequence,job_match_id)
  values (p_user_id,j.id,p_search_id,c.resume_id,c.email_connection_id,root_row.company,root_row.job_title,
    j.recipient_email,j.recipient_verified_at,root_row.subject,root_row.body,root_row.id,sequence_number,match_id)
    returning * into a;
  return to_jsonb(a);
end;
$$;

-- Si las 72h vencen minutos después del horario diario, programar una nueva
-- consulta de fuente a esa hora. No adelantar un envío ni usar la vacante cacheada.
-- Solo wakes FUTUROS: una cola bloqueada jamás genera un bucle de ejecución.
create or replace function public.complete_search_run(
  p_search_id uuid,p_claim_token uuid,p_run_id uuid,p_status text,
  p_next_run_at timestamptz,p_found_count integer default 0,p_message text default null
) returns boolean language plpgsql security definer set search_path = '' as $$
declare s public.job_searches%rowtype; r public.job_search_runs%rowtype;
  c public.sending_consents%rowtype; owner_id uuid; next_time timestamptz;
  reminder_wake timestamptz; tz text; day_start timestamptz; day_end timestamptz; used_count integer;
begin
  if p_status is null or p_status not in ('completed','error','blocked') or p_found_count is null or p_found_count<0 or
     p_next_run_at is null or p_next_run_at<=now() then raise exception 'Resultado o próxima ejecución inválidos'; end if;
  select user_id into owner_id from public.job_searches where id=p_search_id;
  if owner_id is null then return false; end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(owner_id::text,0));
  select * into s from public.job_searches where id=p_search_id for update;
  if not found or s.claim_token is distinct from p_claim_token or s.lease_expires_at is null or s.lease_expires_at<=now() then return false; end if;
  select * into r from public.job_search_runs where id=p_run_id and search_id=p_search_id and
    claim_token=p_claim_token and status='running' for update;
  if not found then return false; end if;
  next_time:=case when s.updated_at>r.started_at and s.next_run_at>now() then s.next_run_at else p_next_run_at end;
  if p_status='completed' and s.status='enabled' and s.auto_apply then
    select * into c from public.sending_consents where id=s.consent_id and user_id=owner_id;
    select sending_timezone into tz from public.profiles where user_id=owner_id;
    day_start:=(now() at time zone tz)::date::timestamp at time zone tz;
    day_end:=((now() at time zone tz)::date+1)::timestamp at time zone tz;
    select count(*) into used_count from public.applications where user_id=owner_id
      and send_attempt_started_at>=day_start and send_attempt_started_at<day_end;
    if c.id is not null and c.search_id=p_search_id and c.policy_version='v3' and c.repeat_enabled and
       c.revoked_at is null and c.expires_at>now() and c.resume_id is not null and c.daily_limit between 1 and 10 and
       c.authorization_text='Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día' and
       exists (select 1 from public.resume_versions where id=c.resume_id and user_id=owner_id) and
       exists (select 1 from public.email_connections where id=c.email_connection_id and user_id=owner_id
         and provider='google' and status='connected' and revoked_at is null and
         'https://www.googleapis.com/auth/gmail.send'=any(scopes)) then
      select min(last_delivery.confirmed_at+interval '72 hours') into reminder_wake
      from public.applications a
      join public.jobs j on j.id=a.job_id and j.user_id=a.user_id
      join public.job_search_matches m on m.job_id=j.id and m.user_id=j.user_id and m.search_id=p_search_id and m.run_id=p_run_id
      cross join lateral (select max(history.provider_confirmed_at) as confirmed_at from public.applications history
        where history.user_id=owner_id and lower(btrim(history.recipient_email))=lower(btrim(a.recipient_email))) last_delivery
      where a.user_id=owner_id and a.search_id=p_search_id and a.parent_application_id is null and a.status='sent'
        and j.source_authorized and j.is_active and j.recipient_verified_at is not null
        and lower(btrim(j.recipient_email))=lower(btrim(a.recipient_email)) and j.source=any(c.authorized_sources)
        and m.roles_snapshot=s.roles and m.cities_snapshot=s.cities and m.observed_at>=r.started_at
        and m.observed_at>=now()-interval '1 hour' and m.observed_at<=now()
        and last_delivery.confirmed_at+interval '72 hours'>now()
        and last_delivery.confirmed_at+interval '72 hours'<next_time
        and last_delivery.confirmed_at+interval '72 hours'<c.expires_at
        and (used_count<10 or last_delivery.confirmed_at+interval '72 hours'>=day_end)
        and not exists (select 1 from public.recipient_suppressions stop where stop.user_id=owner_id
          and stop.recipient_email=lower(btrim(a.recipient_email)))
        and not exists (select 1 from public.applications uncertain where uncertain.user_id=owner_id
          and lower(btrim(uncertain.recipient_email))=lower(btrim(a.recipient_email)) and
          ((uncertain.send_attempt_id is not null and uncertain.provider_confirmed_at is null) or uncertain.status='responded'));
      if reminder_wake is not null then next_time:=least(next_time,reminder_wake); end if;
    end if;
  end if;
  update public.job_search_runs set status=p_status,finished_at=now(),found_count=p_found_count,message=p_message where id=p_run_id;
  update public.job_searches set next_run_at=next_time,last_run_at=case when p_status='completed' then now() else s.last_run_at end,
    claim_token=null,lease_expires_at=null where id=p_search_id;
  return true;
end;
$$;

create function public.stop_recipient_followups(
  p_user_id uuid,p_application_id uuid,p_reason text default 'user_request'
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare a public.applications%rowtype; stopped public.recipient_suppressions%rowtype;
begin
  if p_user_id is null or p_reason is null or p_reason not in ('user_request','responded') then
    raise exception 'Solicitud de detención inválida';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_user_id::text,0));
  select * into a from public.applications where id=p_application_id and user_id=p_user_id for update;
  if not found or nullif(btrim(a.recipient_email),'') is null then return null; end if;
  if p_reason='responded' then
    if a.status not in ('sent','responded') or a.provider_confirmed_at is null then
      raise exception 'Solo una entrega confirmada puede registrarse como respondida';
    end if;
    update public.applications set status='responded' where id=a.id;
  end if;
  insert into public.recipient_suppressions(user_id,recipient_email,reason)
    values (p_user_id,lower(btrim(a.recipient_email)),p_reason)
    on conflict (user_id,recipient_email) do update set reason=case
      when recipient_suppressions.reason='responded' then 'responded' else excluded.reason end
    returning * into stopped;
  return to_jsonb(stopped);
end;
$$;

revoke all on function private.delivery_budget_available(uuid,text,boolean), private.current_job_match(uuid,uuid,uuid)
  from public,anon,authenticated,service_role;
revoke all on function public.grant_sending_consent(uuid,uuid,uuid,uuid,text[],timestamptz,text,boolean),
  public.create_initial_application(jsonb),public.prepare_followup_application(uuid,uuid,uuid,uuid,uuid),
  public.stop_recipient_followups(uuid,uuid,text)
  from public,anon,authenticated;
grant execute on function public.grant_sending_consent(uuid,uuid,uuid,uuid,text[],timestamptz,text,boolean),
  public.create_initial_application(jsonb),public.prepare_followup_application(uuid,uuid,uuid,uuid,uuid),
  public.stop_recipient_followups(uuid,uuid,text) to service_role;
-- CREATE OR REPLACE conserva ACL de prepare/claim/revoke; las funciones nuevas
-- de triggers solo se ejecutan por los triggers, con privilegios del servidor.
-- ===== FIN MIGRACIÓN: 202610120005_daily_budget_and_followups.sql =====

-- Commit confirma únicamente el esquema; no verifica IA, Gmail ni tareas.
COMMIT;
