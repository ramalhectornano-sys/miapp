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
