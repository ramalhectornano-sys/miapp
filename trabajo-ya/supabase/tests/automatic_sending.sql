-- Pruebas reales de la política automática. Ninguna reserva afirma un envío.
begin;
insert into auth.users(id) values
  ('31111111-1111-1111-1111-111111111111'),
  ('32222222-2222-2222-2222-222222222222');
set local role service_role;
do $$
declare
  user_a uuid := '31111111-1111-1111-1111-111111111111';
  user_b uuid := '32222222-2222-2222-2222-222222222222';
  cv_a uuid := gen_random_uuid(); cv_a2 uuid := gen_random_uuid(); cv_b uuid := gen_random_uuid();
  account_a uuid := gen_random_uuid(); account_a2 uuid := gen_random_uuid(); account_b uuid := gen_random_uuid();
  search_a uuid := gen_random_uuid(); job_a uuid := gen_random_uuid(); app_a uuid := gen_random_uuid();
  grant_result jsonb; consent_a uuid; new_consent uuid; result jsonb; rejected boolean;
  search_claim jsonb; repeated_claim jsonb;
  local_timezone text; local_midnight timestamptz; quota_app uuid;
  j uuid; a uuid; counter integer;
begin
  insert into public.resume_versions(id,user_id,name,original_filename,object_path,mime_type,size_bytes) values
    (cv_a,user_a,'CV original','a.pdf',user_a::text || '/a.pdf','application/pdf',100),
    (cv_a2,user_a,'CV autorizado','a2.pdf',user_a::text || '/a2.pdf','application/pdf',100),
    (cv_b,user_b,'CV ajeno','b.pdf',user_b::text || '/b.pdf','application/pdf',100);
  insert into public.email_connections(id,user_id,provider,email,scopes) values
    (account_a,user_a,'google','a@example.com',array['https://www.googleapis.com/auth/gmail.send']),
    (account_a2,user_a,'google','a2@example.com',array['https://www.googleapis.com/auth/gmail.send']),
    (account_b,user_b,'google','b@example.com',array['https://www.googleapis.com/auth/gmail.send']);
  insert into public.job_searches(id,user_id,name,roles,cities,next_run_at) values
    (search_a,user_a,'Envíos diarios',array['Chofer'],array['Neuquén'],now()+interval '1 day');
  insert into public.jobs(id,user_id,source,fingerprint,company,title,recipient_email,recipient_verified_at,source_authorized)
    values (job_a,user_a,'authorized-feed','auto-fixture','Empresa','Chofer','rrhh@example.com',now(),true);
  insert into public.applications(id,user_id,job_id,search_id,resume_id,company,job_title,recipient_email,recipient_verified_at,subject,body)
    values (app_a,user_a,job_a,search_a,cv_a,'Empresa','Chofer','rrhh@example.com',now(),'Asunto original','Mensaje original');
  set constraints all immediate;
  if public.prepare_automatic_application(app_a,user_a) is not null or
     public.claim_application_send(app_a,user_a) is not null then
    raise exception 'Se preparó/envió un borrador previo sin autorización';
  end if;

  rejected := false;
  begin
    perform public.grant_sending_consent(user_a,search_a,cv_a,account_a,array['authorized-feed'],now()+interval '30 days',null);
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Grant aceptó texto NULL'; end if;
  rejected := false;
  begin
    perform public.grant_sending_consent(user_a,search_a,cv_a,account_a,array['authorized-feed'],null,'Autorizo los envíos automáticos de esta búsqueda');
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Grant aceptó expiración NULL'; end if;
  rejected := false;
  begin
    perform public.grant_sending_consent(user_a,search_a,cv_a,account_a,null,now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Grant aceptó lista de fuentes NULL'; end if;
  rejected := false;
  begin
    perform public.grant_sending_consent(user_a,search_a,cv_a,account_a,array['authorized-feed'],now()+interval '91 days','Autorizo los envíos automáticos de esta búsqueda');
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Grant permitió más de 90 días'; end if;
  rejected := false;
  begin
    perform public.grant_sending_consent(user_a,search_a,cv_a,account_a,array[null::text],now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Grant aceptó fuente NULL'; end if;
  rejected := false;
  begin
    perform public.grant_sending_consent(user_a,search_a,cv_b,account_a,array['authorized-feed'],now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Grant aceptó CV de otra cuenta'; end if;
  rejected := false;
  begin
    perform public.grant_sending_consent(user_a,search_a,cv_a,account_b,array['authorized-feed'],now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Grant aceptó Gmail de otra cuenta'; end if;
  update public.email_connections set scopes='{}' where id=account_a;
  rejected := false;
  begin
    perform public.grant_sending_consent(user_a,search_a,cv_a,account_a,array['authorized-feed'],now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Grant aceptó Gmail sin permiso de envío'; end if;
  update public.email_connections set scopes=array['https://www.googleapis.com/auth/gmail.send'] where id=account_a;

  grant_result := public.grant_sending_consent(user_a,search_a,cv_a2,account_a2,array['authorized-feed'],now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
  consent_a := (grant_result->'consent'->>'id')::uuid;
  if (grant_result->'consent'->>'daily_limit')::integer <> 10 or
     (grant_result->'search'->>'auto_apply')::boolean is distinct from true or
     (grant_result->'search'->>'preferred_resume_id')::uuid <> cv_a2 or
     (grant_result->'search'->>'consent_id')::uuid <> consent_a then
    raise exception 'Grant no habilitó la política de manera atómica';
  end if;
  if public.claim_application_send(app_a,user_a) is not null then
    raise exception 'Claim aceptó CV/correo antiguo sin preparar';
  end if;
  result := public.prepare_automatic_application(app_a,user_a);
  if result is null or (result->>'resume_id')::uuid <> cv_a2 or
     (result->>'email_connection_id')::uuid <> account_a2 or
     result->>'body' <> 'Mensaje original' or result->>'subject' <> 'Asunto original' or
     result->>'send_attempt_id' is not null or result->>'status' <> 'pending' then
    raise exception 'Preparación no alineó CV/correo o modificó el mensaje';
  end if;
  update public.applications set resume_id=cv_a where id=app_a;
  if public.claim_application_send(app_a,user_a) is not null then raise exception 'Claim aceptó CV distinto'; end if;
  perform public.prepare_automatic_application(app_a,user_a);
  update public.applications set email_connection_id=account_a where id=app_a;
  if public.claim_application_send(app_a,user_a) is not null then raise exception 'Claim aceptó remitente distinto'; end if;
  perform public.prepare_automatic_application(app_a,user_a);

  -- Expiración, revocación, fuentes y verificación se comprueban de nuevo al reservar.
  update public.sending_consents set resume_id=null where id=consent_a;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Permitió autorización antigua sin CV'; end if;
  update public.sending_consents set resume_id=cv_a2 where id=consent_a;
  update public.sending_consents set granted_at=now()-interval '2 days',expires_at=now()-interval '1 day' where id=consent_a;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró expiración'; end if;
  update public.sending_consents set expires_at=now()+interval '30 days',revoked_at=now() where id=consent_a;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró revocación'; end if;
  update public.sending_consents set revoked_at=null,authorized_sources=array['otra-fuente'] where id=consent_a;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró fuente no autorizada'; end if;
  update public.sending_consents set authorized_sources=array['authorized-feed'] where id=consent_a;
  update public.jobs set recipient_email='otro@example.com' where id=job_a;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró cambio de destinatario'; end if;
  update public.jobs set recipient_email='rrhh@example.com',recipient_verified_at=null where id=job_a;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró destinatario sin verificar'; end if;
  update public.jobs set recipient_verified_at=now(),source_authorized=false where id=job_a;
  if public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró fuente deshabilitada'; end if;
  update public.jobs set source_authorized=true where id=job_a;
  update public.email_connections set revoked_at=now() where id=account_a2;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró correo revocado'; end if;
  update public.email_connections set revoked_at=null,status='expired' where id=account_a2;
  if public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró correo expirado'; end if;
  update public.email_connections set status='connected',scopes='{}' where id=account_a2;
  if public.claim_application_send(app_a,user_a) is not null then raise exception 'Ignoró permiso Gmail ausente'; end if;
  update public.email_connections set scopes=array['https://www.googleapis.com/auth/gmail.send'],provider='microsoft' where id=account_a2;
  if public.claim_application_send(app_a,user_a) is not null then raise exception 'Permitió proveedor aún no soportado'; end if;
  update public.email_connections set provider='google' where id=account_a2;
  update public.job_searches set status='paused' where id=search_a;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Envió búsqueda pausada'; end if;
  update public.job_searches set status='enabled' where id=search_a;
  if public.claim_application_send(app_a,user_a,null,'Enviar esta postulación') is not null then raise exception 'NULL omitió política de consentimiento'; end if;
  rejected := false;
  begin
    perform public.claim_application_send(app_a,user_a,true,'Un texto largo que no es la aprobación exacta');
  exception when raise_exception then rejected := true; end;
  if not rejected then raise exception 'Aprobación manual no exigió texto exacto'; end if;

  -- Un nuevo consentimiento revoca el anterior y no cambia el borrador hasta prepararlo.
  grant_result := public.grant_sending_consent(user_a,search_a,cv_a,account_a,array['authorized-feed'],now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
  new_consent := (grant_result->'consent'->>'id')::uuid;
  if (select revoked_at from public.sending_consents where id=consent_a) is null then raise exception 'Grant dejó autorización anterior activa'; end if;
  if public.claim_application_send(app_a,user_a) is not null then raise exception 'Grant nuevo reutilizó CV/correo del anterior'; end if;
  perform public.prepare_automatic_application(app_a,user_a);
  result := public.claim_application_send(app_a,user_a);
  if result is null or result->>'send_attempt_id' is null or result->>'status' <> 'pending' or
     result->>'provider_message_id' is not null then raise exception 'Reserva confundida con envío confirmado'; end if;
  if public.prepare_automatic_application(app_a,user_a) is not null or public.claim_application_send(app_a,user_a) is not null then raise exception 'Permitió segundo intento'; end if;
  update public.applications set status='error',delivery_uncertain=true where id=app_a;
  if public.claim_application_send(app_a,user_a,true,'Enviar esta postulación') is not null then raise exception 'Reintentó envío incierto'; end if;

  -- Una frontera de día local difiere de UTC cualquiera sea la hora de la prueba.
  -- En la primera mitad de UTC se usa +14; en la segunda, -12.
  local_timezone := case when extract(hour from now() at time zone 'UTC') < 12
    then 'Pacific/Kiritimati' else 'Etc/GMT+12' end;
  local_midnight := (now() at time zone local_timezone)::date::timestamp at time zone local_timezone;
  update public.job_searches set timezone=local_timezone where id=search_a;
  update public.sending_consents set daily_limit=1 where id=new_consent;
  update public.applications set send_attempt_started_at=local_midnight+interval '1 second' where id=app_a;
  j := gen_random_uuid(); quota_app := gen_random_uuid();
  insert into public.jobs(id,user_id,source,fingerprint,company,title,recipient_email,recipient_verified_at,source_authorized)
    values (j,user_a,'authorized-feed','quota-fixture','Empresa cuota','Chofer','cuota@example.com',now(),true);
  insert into public.applications(id,user_id,job_id,search_id,resume_id,email_connection_id,company,job_title,recipient_email,recipient_verified_at,subject,body)
    values (quota_app,user_a,j,search_a,cv_a,account_a,'Empresa cuota','Chofer','cuota@example.com',now(),'Cuota','Mensaje');
  if public.claim_application_send(quota_app,user_a) is not null then raise exception 'Ignoró reserva del día local, incluso con error'; end if;
  update public.applications set send_attempt_started_at=local_midnight-interval '1 second' where id=app_a;
  if public.claim_application_send(quota_app,user_a) is null then raise exception 'Cuota usó UTC o contó reserva del día local anterior'; end if;

  -- El límite de diez también cuenta las reservas que terminaron en error.
  update public.sending_consents set daily_limit=10 where id=new_consent;
  update public.applications set send_attempt_started_at=now(),status='error' where id=app_a;
  for counter in 1..9 loop
    j := gen_random_uuid(); a := gen_random_uuid();
    insert into public.jobs(id,user_id,source,fingerprint,company,title,recipient_email,recipient_verified_at,source_authorized)
      values (j,user_a,'authorized-feed','limit-'||counter,'Empresa límite','Chofer','limite@example.com',now(),true);
    insert into public.applications(id,user_id,job_id,search_id,resume_id,email_connection_id,company,job_title,recipient_email,recipient_verified_at,subject,body)
      values (a,user_a,j,search_a,cv_a,account_a,'Empresa límite','Chofer','limite@example.com',now(),'Límite','Mensaje');
    result := public.claim_application_send(a,user_a);
    if counter <= 8 and result is null then raise exception 'Bloqueó antes de diez reservas'; end if;
    if counter = 9 and result is not null then raise exception 'Permitió más de diez reservas'; end if;
  end loop;
  -- La aprobación individual sigue disponible al agotar el permiso automático.
  result := public.claim_application_send(a,user_a,true,'Enviar esta postulación');
  if result is null or result->>'manual_approval_text' <> 'Enviar esta postulación' or
     result->>'manual_approved_at' is null then raise exception 'No registró aprobación individual'; end if;

  -- Cambiar consentimiento durante un run modifica updated_at, sin recalcular
  -- next_run_at. No debe preservar la fecha vencida ni ejecutar de nuevo enseguida.
  update public.job_searches set next_run_at=now()-interval '1 minute' where id=search_a;
  select item into search_claim from public.claim_due_searches('consent-during-run') item limit 1;
  if search_claim is null then raise exception 'No reclamó búsqueda para probar edición durante run'; end if;
  update public.job_search_runs set started_at=now()-interval '1 second'
    where id=(search_claim->>'run_id')::uuid;
  grant_result := public.grant_sending_consent(user_a,search_a,cv_a,account_a,array['authorized-feed'],now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
  new_consent := (grant_result->'consent'->>'id')::uuid;
  if not public.complete_search_run(search_a,(search_claim->>'claim_token')::uuid,
      (search_claim->>'run_id')::uuid,'completed',now()+interval '1 day') or
     (select next_run_at from public.job_searches where id=search_a) <> now()+interval '1 day' then
    raise exception 'Grant durante run conservó próxima fecha vencida';
  end if;
  select item into repeated_claim from public.claim_due_searches('worker-after-consent') item limit 1;
  if repeated_claim is not null then raise exception 'Grant durante run causó ejecución inmediata repetida'; end if;
  perform set_config('test.current_consent',new_consent::text,true);
  perform set_config('test.previous_consent',consent_a::text,true);
  perform set_config('test.current_search',search_a::text,true);
end;
$$;
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub','32222222-2222-2222-2222-222222222222',true);
do $$
begin
  begin
    perform public.grant_sending_consent(gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),array['authorized-feed'],now()+interval '30 days','Autorizo los envíos automáticos de esta búsqueda');
    raise exception 'Cliente accedió al RPC grant';
  exception when insufficient_privilege then null; end;
  begin
    perform public.prepare_automatic_application(gen_random_uuid(),gen_random_uuid());
    raise exception 'Cliente accedió al RPC prepare';
  exception when insufficient_privilege then null; end;
  begin
    perform public.claim_application_send(gen_random_uuid(),gen_random_uuid(),true,'Enviar esta postulación');
    raise exception 'Cliente accedió al RPC claim';
  exception when insufficient_privilege then null; end;
  if public.revoke_sending_consent(current_setting('test.current_consent')::uuid) then
    raise exception 'Cliente revocó autorización ajena';
  end if;
end;
$$;
select set_config('request.jwt.claim.sub','31111111-1111-1111-1111-111111111111',true);
do $$ begin
  if not public.revoke_sending_consent(current_setting('test.previous_consent')::uuid) or
     (select auto_apply from public.job_searches where id=current_setting('test.current_search')::uuid) is distinct from true then
    raise exception 'Revocar permiso anterior desactivó permiso actual';
  end if;
  if not public.revoke_sending_consent(current_setting('test.current_consent')::uuid) then
    raise exception 'Cliente no pudo revocar autorización propia';
  end if;
end; $$;
reset role;
do $$ begin
  if (select auto_apply from public.job_searches where id=current_setting('test.current_search')::uuid) then
    raise exception 'Revocación no desactivó los envíos';
  end if;
end; $$;
rollback;
