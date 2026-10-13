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
