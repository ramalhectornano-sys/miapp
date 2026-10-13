-- Datos EXCLUSIVAMENTE de prueba; rollback final. No se llama a Gmail.
begin;
insert into auth.users(id) values
 ('41111111-1111-1111-1111-111111111111'),
 ('42222222-2222-2222-2222-222222222222'),
 ('43333333-3333-3333-3333-333333333333'),
 ('44444444-4444-4444-4444-444444444444');

-- Helper con el mismo camino del servidor: nueva vacante, observación de fuente
-- en run vigente, y postulación inicial idempotente. Ningún recibo real se simula.
create function public.test_candidate(owner_id uuid,search_key uuid,cv_key uuid,account_key uuid,fixture_key text,recipient text)
returns uuid language plpgsql set search_path='' as $$
declare j uuid:=gen_random_uuid(); result jsonb; s public.job_searches%rowtype; run_key uuid;
begin
  select * into s from public.job_searches where id=search_key;
  select id into run_key from public.job_search_runs where user_id=owner_id and search_id=search_key
    and claim_token=s.claim_token and status='running';
  insert into public.jobs(id,user_id,source,fingerprint,company,title,city,recipient_email,
    recipient_verified_at,source_authorized,is_active,last_seen_at)
    values (j,owner_id,'authorized-feed',fixture_key,'Empresa '||fixture_key,'Chofer','Neuquén',recipient,now(),true,true,now());
  insert into public.job_search_matches(user_id,job_id,search_id,run_id,roles_snapshot,cities_snapshot)
    values (owner_id,j,search_key,run_key,s.roles,s.cities);
  result:=public.create_initial_application(jsonb_build_object('user_id',owner_id,'job_id',j,'search_id',search_key,
    'resume_id',cv_key,'email_connection_id',account_key,'company','Empresa '||fixture_key,'job_title','Chofer',
    'recipient_email',recipient,'recipient_verified_at',now(),'subject','Asunto verificable','body','Mensaje de fixture'));
  return (result->>'id')::uuid;
end;
$$;
grant execute on function public.test_candidate(uuid,uuid,uuid,uuid,text,text) to service_role;
set local role service_role;
do $$
declare
  budget_user uuid:='41111111-1111-1111-1111-111111111111';
  follow_user uuid:='42222222-2222-2222-2222-222222222222';
  scope_user uuid:='43333333-3333-3333-3333-333333333333';
  owner_id uuid; search_key uuid; search_two uuid; cv_key uuid; account_key uuid;
  search_claim jsonb; result jsonb; child jsonb; again jsonb; stopped jsonb;
  app_key uuid; root_key uuid; job_key uuid; follow_search uuid; follow_cv uuid; follow_account uuid;
  follow_claim jsonb; counter integer; rejected boolean; original_body text;
  v2_text text:='Autorizo los envíos automáticos de esta búsqueda';
  v3_text text:='Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día';
begin
  -- Dos búsquedas con zonas horarias diferentes comparten las DIEZ reservas.
  cv_key:=gen_random_uuid(); account_key:=gen_random_uuid(); search_key:=gen_random_uuid(); search_two:=gen_random_uuid();
  insert into public.resume_versions(id,user_id,name,original_filename,object_path,mime_type,size_bytes)
    values (cv_key,budget_user,'CV prueba','fixture.pdf',budget_user::text||'/fixture.pdf','application/pdf',100);
  insert into public.email_connections(id,user_id,provider,email,scopes)
    values (account_key,budget_user,'google','usuario@example.com',array['https://www.googleapis.com/auth/gmail.send']);
  insert into public.job_searches(id,user_id,name,roles,cities,timezone,next_run_at) values
    (search_key,budget_user,'Primera',array['Chofer'],array['Neuquén'],'Pacific/Kiritimati',now()-interval '1 minute'),
    (search_two,budget_user,'Segunda',array['Chofer'],array['Neuquén'],'Etc/GMT+12',now()-interval '1 minute');
  perform public.claim_search_now(search_key,budget_user,'test-first');
  perform public.claim_search_now(search_two,budget_user,'test-second');
  perform public.grant_sending_consent(budget_user,search_key,cv_key,account_key,array['authorized-feed'],now()+interval '30 days',v2_text);
  perform public.grant_sending_consent(budget_user,search_two,cv_key,account_key,array['authorized-feed'],now()+interval '30 days',v2_text);
  for counter in 1..11 loop
    app_key:=public.test_candidate(budget_user,case when counter%2=0 then search_two else search_key end,
      cv_key,account_key,'budget-'||counter,'empresa-'||counter||'@example.com');
    if counter=2 then
      result:=public.claim_application_send(app_key,budget_user,true,'Enviar esta postulación');
    else
      perform public.prepare_automatic_application(app_key,budget_user);
      result:=public.claim_application_send(app_key,budget_user);
    end if;
    if counter<=10 and result is null then raise exception 'Bloqueó antes del techo GLOBAL de diez: %',counter; end if;
    if counter=11 and result is not null then raise exception 'Permitió reserva once entre distintas búsquedas'; end if;
    if counter=11 and public.claim_application_send(app_key,budget_user,true,'Enviar esta postulación') is not null then
      raise exception 'La aprobación manual eludió el techo GLOBAL';
    end if;
    if result is not null then
      if result->>'provider_message_id' is not null or result->>'status'<>'pending' then raise exception 'Reserva simuló envío'; end if;
      if counter=1 then update public.applications set status='error',error='Error definitivo de prueba' where id=app_key; end if;
      if counter=2 then update public.applications set status='error',delivery_uncertain=true,error='Timeout de prueba' where id=app_key; end if;
    end if;
  end loop;
  if (select count(*) from public.applications where user_id=budget_user and send_attempt_id is not null)<>10 then
    raise exception 'Errores o envíos manuales no consumieron presupuesto';
  end if;
  rejected:=false;
  begin update public.profiles set sending_timezone='UTC' where user_id=budget_user;
  exception when raise_exception then rejected:=true; end;
  if not rejected then raise exception 'Permitió alterar zona para reciclar cuota'; end if;

  -- Una cuenta distinta tiene su propia cuota; preparando una fila con run válido.
  follow_cv:=gen_random_uuid(); follow_account:=gen_random_uuid(); follow_search:=gen_random_uuid();
  insert into public.resume_versions(id,user_id,name,original_filename,object_path,mime_type,size_bytes)
    values (follow_cv,follow_user,'CV followup','follow.pdf',follow_user::text||'/follow.pdf','application/pdf',100);
  insert into public.email_connections(id,user_id,provider,email,scopes)
    values (follow_account,follow_user,'google','follow@example.com',array['https://www.googleapis.com/auth/gmail.send']);
  insert into public.job_searches(id,user_id,name,roles,cities,next_run_at)
    values (follow_search,follow_user,'Seguimiento',array['Chofer'],array['Neuquén'],now()-interval '1 minute');
  follow_claim:=public.claim_search_now(follow_search,follow_user,'test-followup');
  result:=public.grant_sending_consent(follow_user,follow_search,follow_cv,follow_account,array['authorized-feed'],now()+interval '30 days',v2_text);
  if (result->'consent'->>'repeat_enabled')::boolean then raise exception 'Activó recordatorios al renovar v2'; end if;
  rejected:=false;
  begin perform public.grant_sending_consent(follow_user,follow_search,follow_cv,follow_account,
    array['authorized-feed'],now()+interval '30 days',v2_text,true);
  exception when raise_exception then rejected:=true; end;
  if not rejected then raise exception 'Aceptó recordatorios con texto de consentimiento antiguo'; end if;

  -- Insertar evidencia histórica de fixture antes de probar recordatorios. Es una
  -- fila de prueba declarada, no un correo enviado ni una operación de integración.
  root_key:=gen_random_uuid(); job_key:=gen_random_uuid();
  insert into public.jobs(id,user_id,source,fingerprint,company,title,city,recipient_email,recipient_verified_at,source_authorized)
    values (job_key,follow_user,'authorized-feed','follow-root','Empresa seguimiento','Chofer','Neuquén','rrhh@example.com',now(),true);
  insert into public.applications(id,user_id,job_id,search_id,resume_id,email_connection_id,company,job_title,
    recipient_email,recipient_verified_at,subject,body,status,send_attempt_id,send_attempt_started_at,
    provider_message_id,provider_confirmed_at,sent_at,sender_email)
  values (root_key,follow_user,job_key,follow_search,follow_cv,follow_account,'Empresa seguimiento','Chofer',
    'rrhh@example.com',now()-interval '4 days','Original','No reemplazar el historial','sent',gen_random_uuid(),
    now()-interval '73 hours','FIXTURE-NO-REAL-EMAIL',now()-interval '73 hours',now()-interval '73 hours','follow@example.com');
  insert into public.job_search_matches(user_id,job_id,search_id,run_id,roles_snapshot,cities_snapshot)
    values (follow_user,job_key,follow_search,(follow_claim->>'run_id')::uuid,array['Chofer'],array['Neuquén']);
  if public.prepare_followup_application(root_key,follow_user,follow_search,(follow_claim->>'run_id')::uuid,
    (follow_claim->>'claim_token')::uuid) is not null then raise exception 'v2 permitió reenvío'; end if;
  result:=public.grant_sending_consent(follow_user,follow_search,follow_cv,follow_account,array['authorized-feed'],now()+interval '30 days',v3_text,true);
  if result->'consent'->>'policy_version'<>'v3' or not (result->'consent'->>'repeat_enabled')::boolean then
    raise exception 'No guardó el alcance explícito v3';
  end if;
  update public.jobs set is_active=false where id=job_key;
  if public.prepare_followup_application(root_key,follow_user,follow_search,(follow_claim->>'run_id')::uuid,
    (follow_claim->>'claim_token')::uuid) is not null then raise exception 'Reenvió oferta cerrada'; end if;
  update public.jobs set is_active=true where id=job_key;
  update public.job_searches set roles=array['Administrativo'] where id=follow_search;
  if public.prepare_followup_application(root_key,follow_user,follow_search,(follow_claim->>'run_id')::uuid,
    (follow_claim->>'claim_token')::uuid) is not null then raise exception 'Reutilizó match tras editar requisitos'; end if;
  update public.job_searches set roles=array['Chofer'] where id=follow_search;
  child:=public.prepare_followup_application(root_key,follow_user,follow_search,(follow_claim->>'run_id')::uuid,
    (follow_claim->>'claim_token')::uuid);
  if child is null or (child->>'parent_application_id')::uuid<>root_key or (child->>'delivery_sequence')::integer<>1 then
    raise exception 'No creó nueva fila histórica de seguimiento';
  end if;
  again:=public.prepare_followup_application(root_key,follow_user,follow_search,(follow_claim->>'run_id')::uuid,
    (follow_claim->>'claim_token')::uuid);
  if again->>'id' is distinct from child->>'id' then raise exception 'Duplicó borrador de seguimiento'; end if;
  result:=public.claim_application_send((child->>'id')::uuid,follow_user);
  if result is null or result->>'sender_email'<>'follow@example.com' or result->>'sending_consent_id' is null then
    raise exception 'No reservó recordatorio con snapshot de remitente y autorización';
  end if;
  if (select status from public.applications where id=root_key)<>'sent' or
     (select body from public.applications where id=root_key)<>'No reemplazar el historial' or
     (select provider_message_id from public.applications where id=root_key)<>'FIXTURE-NO-REAL-EMAIL' then
    raise exception 'Reescribió la postulación inicial';
  end if;
  if public.claim_application_send((child->>'id')::uuid,follow_user) is not null then raise exception 'Reutilizó intento'; end if;
  if public.prepare_followup_application(root_key,follow_user,follow_search,(follow_claim->>'run_id')::uuid,
    (follow_claim->>'claim_token')::uuid) is not null then raise exception 'Duplicó correo con reserva pendiente'; end if;
  update public.applications set status='error',delivery_uncertain=true where id=(child->>'id')::uuid;
  if public.prepare_followup_application(root_key,follow_user,follow_search,(follow_claim->>'run_id')::uuid,
    (follow_claim->>'claim_token')::uuid) is not null then raise exception 'Reintentó entrega incierta'; end if;
  rejected:=false;
  begin update public.applications set delivery_uncertain=false where id=(child->>'id')::uuid;
  exception when raise_exception then rejected:=true; end;
  if not rejected then raise exception 'Liberó correo incierto sin conciliación'; end if;
  update public.applications set status='sent',delivery_uncertain=false,provider_message_id='FIXTURE-SECOND-NO-REAL-EMAIL',
    provider_confirmed_at=now(),sent_at=now() where id=(child->>'id')::uuid;
  if public.prepare_followup_application(root_key,follow_user,follow_search,(follow_claim->>'run_id')::uuid,
    (follow_claim->>'claim_token')::uuid) is not null then raise exception 'Ignoró intervalo desde última confirmación'; end if;
  rejected:=false;
  begin update public.applications set body='Reescrito' where id=root_key;
  exception when raise_exception then rejected:=true; end;
  if not rejected then raise exception 'Permite modificar historial confirmado'; end if;
  rejected:=false;
  begin update public.applications set send_attempt_id=null,send_attempt_started_at=null,status='pending' where id=(child->>'id')::uuid;
  exception when raise_exception then rejected:=true; end;
  if not rejected then raise exception 'Permite resetear entrega histórica'; end if;
  stopped:=public.stop_recipient_followups(follow_user,root_key,'responded');
  if stopped->>'reason'<>'responded' or (select status from public.applications where id=root_key)<>'responded' then
    raise exception 'No detuvo seguimientos ni registró respuesta';
  end if;
  again:=public.stop_recipient_followups(follow_user,root_key,'user_request');
  if again->>'stopped_at' is distinct from stopped->>'stopped_at' or again->>'reason'<>'responded' then
    raise exception 'Detención no idempotente o degradó respuesta';
  end if;
  if public.stop_recipient_followups(budget_user,root_key) is not null then raise exception 'Detuvo destinatario ajeno'; end if;

  -- Otra búsqueda, otra oferta, el MISMO destinatario (case/espacios) comparte
  -- bloqueo de 72h y bloqueo de reserva; no se elude cambiando puesto/búsqueda.
  app_key:=public.test_candidate(follow_user,follow_search,follow_cv,follow_account,'same-recipient',' RRHH@example.com ');
  perform public.prepare_automatic_application(app_key,follow_user);
  if public.claim_application_send(app_key,follow_user) is not null or
     public.claim_application_send(app_key,follow_user,true,'Enviar esta postulación') is not null then
    raise exception 'Cambió vacante/capitalización para eludir cooldown';
  end if;
  -- Una cuenta con cuota propia puede enviar a otro destinatario compatible.
  app_key:=public.test_candidate(follow_user,follow_search,follow_cv,follow_account,'independent','independiente@example.com');
  perform public.prepare_automatic_application(app_key,follow_user);
  if public.claim_application_send(app_key,follow_user) is null then raise exception 'Compartió cuota entre usuarios'; end if;

  -- Una oferta guardada sin una consulta del run no habilita automatización.
  job_key:=gen_random_uuid(); app_key:=gen_random_uuid();
  insert into public.jobs(id,user_id,source,fingerprint,company,title,city,recipient_email,recipient_verified_at,source_authorized)
    values (job_key,follow_user,'authorized-feed','stale','Antigua','Chofer','Neuquén','stale@example.com',now(),true);
  insert into public.applications(id,user_id,job_id,search_id,resume_id,email_connection_id,company,job_title,recipient_email,
    recipient_verified_at,subject,body) values (app_key,follow_user,job_key,follow_search,follow_cv,follow_account,
      'Antigua','Chofer','stale@example.com',now(),'Pendiente','Sin evidencia actual');
  if public.prepare_automatic_application(app_key,follow_user) is not null or
     public.claim_application_send(app_key,follow_user) is not null then raise exception 'Envió vacante cacheada sin consulta'; end if;
  rejected:=false;
  begin insert into public.job_search_matches(user_id,job_id,search_id,run_id,roles_snapshot,cities_snapshot,observed_at)
    values (follow_user,job_key,follow_search,(follow_claim->>'run_id')::uuid,array['Chofer'],array['Neuquén'],now()-interval '2 hours');
  exception when raise_exception then rejected:=true; end;
  if not rejected then raise exception 'Aceptó evidencia antigua'; end if;
end;
$$;
-- Vencimiento futuro de las 72h: agenda otra consulta real en lugar de esperar
-- al cuarto día. El worker deberá redescubrir la oferta con una nueva lease.
do $$
declare owner_id uuid:='43333333-3333-3333-3333-333333333333';
  cv_key uuid:=gen_random_uuid(); account_key uuid:=gen_random_uuid(); search_key uuid:=gen_random_uuid();
  root_key uuid:=gen_random_uuid(); job_key uuid:=gen_random_uuid(); claim jsonb; completed boolean;
  due_at timestamptz:=now()+interval '10 minutes'; next_daily timestamptz:=now()+interval '1 day';
begin
  insert into public.resume_versions(id,user_id,name,original_filename,object_path,mime_type,size_bytes)
    values (cv_key,owner_id,'CV agenda','agenda.pdf',owner_id::text||'/agenda.pdf','application/pdf',100);
  insert into public.email_connections(id,user_id,provider,email,scopes)
    values (account_key,owner_id,'google','agenda@example.com',array['https://www.googleapis.com/auth/gmail.send']);
  insert into public.job_searches(id,user_id,name,roles,cities,next_run_at)
    values (search_key,owner_id,'Agenda recordatorio',array['Chofer'],array['Neuquén'],now()-interval '1 minute');
  claim:=public.claim_search_now(search_key,owner_id,'test-wake');
  perform public.grant_sending_consent(owner_id,search_key,cv_key,account_key,array['authorized-feed'],now()+interval '30 days',
    'Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día',true);
  insert into public.jobs(id,user_id,source,fingerprint,company,title,city,recipient_email,recipient_verified_at,source_authorized)
    values (job_key,owner_id,'authorized-feed','future-wake','Agenda','Chofer','Neuquén','agenda-empresa@example.com',now(),true);
  insert into public.applications(id,user_id,job_id,search_id,resume_id,email_connection_id,company,job_title,
    recipient_email,recipient_verified_at,subject,body,status,send_attempt_id,send_attempt_started_at,
    provider_message_id,provider_confirmed_at,sent_at)
  values (root_key,owner_id,job_key,search_key,cv_key,account_key,'Agenda','Chofer','agenda-empresa@example.com',
    now()-interval '3 days','Agenda','Fixture explícito','sent',gen_random_uuid(),due_at-interval '72 hours',
    'FIXTURE-WAKE-NO-REAL-EMAIL',due_at-interval '72 hours',due_at-interval '72 hours');
  insert into public.job_search_matches(user_id,job_id,search_id,run_id,roles_snapshot,cities_snapshot)
    values (owner_id,job_key,search_key,(claim->>'run_id')::uuid,array['Chofer'],array['Neuquén']);
  if public.prepare_followup_application(root_key,owner_id,search_key,(claim->>'run_id')::uuid,(claim->>'claim_token')::uuid) is not null then
    raise exception 'Preparó recordatorio antes de cumplir 72h';
  end if;
  -- Observe the schedule only after completing the mutating function; SQL
  -- expression evaluation does not order a scalar subquery after that call.
  completed := public.complete_search_run(search_key,(claim->>'claim_token')::uuid,(claim->>'run_id')::uuid,'completed',next_daily);
  if completed is distinct from true then
    raise exception 'No completó la búsqueda para agendar el recordatorio';
  end if;
  if (select next_run_at from public.job_searches where id=search_key) is distinct from due_at then
    raise exception 'No agendó nueva consulta al vencer las 72h';
  end if;
  claim:=public.claim_search_now(search_key,owner_id,'test-wake-stopped');
  insert into public.job_search_matches(user_id,job_id,search_id,run_id,roles_snapshot,cities_snapshot)
    values (owner_id,job_key,search_key,(claim->>'run_id')::uuid,array['Chofer'],array['Neuquén']);
  perform public.stop_recipient_followups(owner_id,root_key);
  completed := public.complete_search_run(search_key,(claim->>'claim_token')::uuid,(claim->>'run_id')::uuid,'completed',next_daily);
  if completed is distinct from true then
    raise exception 'No completó la búsqueda con dirección detenida';
  end if;
  if (select next_run_at from public.job_searches where id=search_key) is distinct from next_daily then
    raise exception 'Una dirección detenida volvió a agendar wake de recordatorio';
  end if;
end;
$$;
reset role;
insert into storage.objects(bucket_id,name) values
  ('resumes','42222222-2222-2222-2222-222222222222/follow.pdf'),
  ('resumes','42222222-2222-2222-2222-222222222222/free.pdf');
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub','44444444-4444-4444-4444-444444444444',true);
do $$ begin
  if exists (select 1 from public.job_search_matches) or exists (select 1 from public.recipient_suppressions) then
    raise exception 'RLS expuso evidencia/destinatarios ajenos';
  end if;
  delete from public.profiles where user_id='44444444-4444-4444-4444-444444444444';
  begin insert into public.profiles(user_id,sending_timezone)
    values ('44444444-4444-4444-4444-444444444444','Pacific/Kiritimati');
    raise exception 'Recreó perfil en otra zona y eludió presupuesto'; exception when check_violation then null; end;
  insert into public.profiles(user_id) values ('44444444-4444-4444-4444-444444444444');
  begin perform public.prepare_followup_application(gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),gen_random_uuid());
    raise exception 'Cliente invocó preparación de recordatorio'; exception when insufficient_privilege then null; end;
  begin perform public.stop_recipient_followups(gen_random_uuid(),gen_random_uuid());
    raise exception 'Cliente invocó detención para otro usuario'; exception when insufficient_privilege then null; end;
  begin insert into public.recipient_suppressions(user_id,recipient_email,reason)
    values ('44444444-4444-4444-4444-444444444444','rrhh@example.com','user_request');
    raise exception 'Cliente escribió estado servidor'; exception when insufficient_privilege then null; end;
  begin update public.job_search_matches set observed_at=now();
    raise exception 'Cliente manipuló evidencia'; exception when insufficient_privilege then null; end;
end; $$;
select set_config('request.jwt.claim.sub','42222222-2222-2222-2222-222222222222',true);
do $$
declare rejected boolean:=false;
begin
  begin delete from storage.objects where bucket_id='resumes' and name='42222222-2222-2222-2222-222222222222/follow.pdf';
    exception when raise_exception then rejected:=true; end;
  if not rejected then raise exception 'Borró el CV adjunto al historial y podría reemplazar sus bytes'; end if;
  delete from storage.objects where bucket_id='resumes' and name='42222222-2222-2222-2222-222222222222/free.pdf';
  if exists (select 1 from storage.objects where name='42222222-2222-2222-2222-222222222222/free.pdf') then
    raise exception 'Bloqueó la eliminación de un documento sin postulaciones';
  end if;
end; $$;
reset role;
set local role service_role;
delete from storage.objects where bucket_id='resumes' and name='42222222-2222-2222-2222-222222222222/follow.pdf';
do $$ begin
  if exists (select 1 from storage.objects where name='42222222-2222-2222-2222-222222222222/follow.pdf') then
    raise exception 'La protección del historial bloqueó el borrado privado de cuenta';
  end if;
end; $$;
reset role;
rollback;
