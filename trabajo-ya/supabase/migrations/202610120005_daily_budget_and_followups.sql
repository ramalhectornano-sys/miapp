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
