-- No external HTTP calls: PostgreSQL verifies that only the current server
-- worker can append real-call evidence and clients cannot forge that evidence.
begin;
insert into auth.users(id,raw_user_meta_data) values
  ('11111111-1111-1111-1111-111111111111','{"full_name":"Usuario A"}'),
  ('22222222-2222-2222-2222-222222222222','{"full_name":"Usuario B"}');
insert into public.job_searches(id,user_id,name,roles,cities,next_run_at,province,country,radius_km,location)
values ('cccccccc-cccc-cccc-cccc-cccccccccccc','11111111-1111-1111-1111-111111111111',
  'Investigación A',array['Chofer'],array['Rincón de los Sauces'],now()-interval '1 minute',
  'Neuquén','Argentina',100,
  '{"id":"local-test","city":"Rincón de los Sauces","province":"Neuquén","country":"Argentina","latitude":-37.4,"longitude":-68.9}');
do $$ begin
  if not exists(select 1 from public.job_searches where research_mode='general') then
    raise exception 'La migración no habilitó investigación general por defecto';
  end if;
  begin
    update public.job_searches set research_mode='portal_inventado';
    raise exception 'Se aceptó un modo de investigación desconocido';
  exception when check_violation then null; end;
  begin
    update public.job_searches set radius_km=1001;
    raise exception 'Se aceptó un radio fuera del límite';
  exception when check_violation then null; end;
  begin
    update public.job_searches set location='{"latitude":91,"longitude":0}';
    raise exception 'Se aceptó latitud fuera de rango';
  exception when check_violation then null; end;
  begin
    update public.job_searches set location='{"latitude":0}';
    raise exception 'Se aceptó una coordenada incompleta';
  exception when check_violation then null; end;
  begin
    update public.job_searches set location='{"latitude":"0","longitude":0}';
    raise exception 'Se aceptó una coordenada de texto';
  exception when check_violation then null; end;
  begin
    update public.job_searches set location='{"latitude":0,"longitude":181}';
    raise exception 'Se aceptó longitud fuera de rango';
  exception when check_violation then null; end;
  begin
    update public.job_searches set location='[]';
    raise exception 'Se aceptó ubicación no estructurada';
  exception when check_violation then null; end;
  begin
    update public.job_searches set country=' ';
    raise exception 'Se aceptó un país vacío';
  exception when check_violation then null; end;
end; $$;

set local role service_role;
do $$
declare claim jsonb; event_id uuid:=gen_random_uuid(); event jsonb; ok boolean; i integer;
  invalid_event jsonb;
begin
  claim:=public.claim_search_now('cccccccc-cccc-cccc-cccc-cccccccccccc',
    '11111111-1111-1111-1111-111111111111','research-test',300);
  if claim is null then raise exception 'No se creó ejecución para la prueba'; end if;
  if not public.safe_research_url('https://empresa.com.ar/empleos/Rinc%C3%B3n-de-los-Sauces') then
    raise exception 'Se rechazó una URL con ruta Unicode codificada';
  end if;
  event:=jsonb_build_object('event_id',event_id,'kind','tavily_query','provider','tavily',
    'query','vacantes chofer Rincón de los Sauces Neuquén Argentina',
    'url','https://api.tavily.com/search','status','started','started_at',now(),
    'metadata',jsonb_build_object('query_kind','general','radius_km',100));
  ok:=public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,gen_random_uuid(),event);
  if ok then raise exception 'Se aceptó evidencia con lease ajena'; end if;
  ok:=public.record_web_research_event((claim->>'id')::uuid,gen_random_uuid(),(claim->>'claim_token')::uuid,event);
  if ok then raise exception 'Se aceptó evidencia con run ajeno'; end if;
  ok:=public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
    (claim->>'claim_token')::uuid,event || '{"user_id":"22222222-2222-2222-2222-222222222222"}');
  if ok then raise exception 'El cliente pudo elegir propietario del historial'; end if;
  ok:=public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,(claim->>'claim_token')::uuid,event);
  if not ok then raise exception 'No se registró el inicio de consulta'; end if;
  if (select finished_at from public.web_research_events where id=event_id) is not null then
    raise exception 'Una consulta iniciada figura como terminada';
  end if;
  if public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
     (claim->>'claim_token')::uuid,event) then raise exception 'Se permitió reiniciar un evento'; end if;
  event:=event || jsonb_build_object('status','succeeded','http_status',200,
    'provider_request_id','public-request-proof','credits',1,
    'result_urls',jsonb_build_array('https://empresa.com.ar/empleos/chofer'),
    'source_hosts',jsonb_build_array('empresa.com.ar'));
  if not public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
    (claim->>'claim_token')::uuid,event) then raise exception 'No se completó la evidencia'; end if;
  if (select count(*) from public.web_research_events) <> 1 then
    raise exception 'Inicio y final consumieron dos registros';
  end if;
  if not exists(select 1 from public.web_research_events where id=event_id and
    user_id='11111111-1111-1111-1111-111111111111' and status='succeeded' and
    finished_at is not null and recorded_at is not null and credits=1 and
    provider_request_id='public-request-proof') then raise exception 'No se conservó evidencia completa'; end if;
  if public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
     (claim->>'claim_token')::uuid,event || '{"status":"failed","error":"Sobreescritura"}') then
    raise exception 'Se cambió un evento ya finalizado';
  end if;

  event:=event || jsonb_build_object('event_id',gen_random_uuid(),'status','failed','http_status',429,
    'error','El proveedor alcanzó el límite de consultas.');
  if not public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
     (claim->>'claim_token')::uuid,event) then raise exception 'No se guardó un error real del proveedor'; end if;
  event:=event || jsonb_build_object('event_id',gen_random_uuid());
  foreach event in array array[
    event || '{"url":"http://empresa.com.ar/empleo"}',
    event || '{"url":"https://localhost/empleo"}',
    event || '{"url":"https://127.0.0.1/empleo"}',
    event || '{"url":"https://usuario:secreto@empresa.com.ar/empleo"}',
    event || '{"url":"https://empresa.com.ar/empleo?access_token=private"}',
    event || '{"url":"https://empresa.com.ar/empleo?%61pi_key=private"}',
    event || '{"url":"https://empresa.com.ar/empleo#access_token=private"}',
    event || '{"result_urls":["https://empresa.com.ar/?token=private"]}',
    event || '{"metadata":{"access_token":"private"}}',
    event || '{"metadata":{"unrestricted_response_body":"private"}}',
    event || '{"metadata":{"reason":{"Authorization":"private"}}}',
    event || '{"provider":{"name":"tavily"}}',
    event || '{"credits":"1"}',
    event || '{"started_at":"not-a-date"}',
    event || '{"error":"Bearer TEST_PRIVATE_TOKEN"}'
  ] loop
    if public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
       (claim->>'claim_token')::uuid,event) then raise exception 'Se guardaron secretos o URL no segura'; end if;
  end loop;
  foreach invalid_event in array array['null'::jsonb, '[]'::jsonb, '{}'::jsonb] loop
    if public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
       (claim->>'claim_token')::uuid,invalid_event) then raise exception 'Se aceptó un evento sin estructura'; end if;
  end loop;
  -- Full budget is unique events, not HTTP start/final transitions.
  for i in 1..126 loop
    event:=jsonb_build_object('event_id',gen_random_uuid(),'kind','public_page','provider','public_https',
      'url','https://empresa.com.ar/empleos/chofer','status','blocked','started_at',now(),
      'error','La fuente exige intervención humana.');
    if not public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
       (claim->>'claim_token')::uuid,event) then raise exception 'El presupuesto se agotó antes de 128'; end if;
  end loop;
  if (select count(*) from public.web_research_events) <> 128 then raise exception 'Presupuesto inesperado'; end if;
  event:=event || jsonb_build_object('event_id',gen_random_uuid());
  if public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
     (claim->>'claim_token')::uuid,event) then raise exception 'Se excedió el presupuesto de historial'; end if;
  begin
    insert into public.web_research_events(id,user_id,search_id,run_id,kind,provider,status,started_at)
    values(gen_random_uuid(),'11111111-1111-1111-1111-111111111111',(claim->>'id')::uuid,
      (claim->>'run_id')::uuid,'tavily_query','tavily','started',now());
    raise exception 'Service_role pudo omitir RPC y presupuesto';
  exception when insufficient_privilege then null; end;
  if not public.complete_search_run((claim->>'id')::uuid,(claim->>'claim_token')::uuid,
     (claim->>'run_id')::uuid,'completed',now()+interval '1 day',0,'Prueba sin HTTP externo') then
    raise exception 'No se finalizó la ejecución de prueba';
  end if;
  if public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
     (claim->>'claim_token')::uuid,event) then raise exception 'Se agregó evidencia después del cierre'; end if;
end; $$;
reset role;

do $$
declare claim jsonb; event jsonb;
begin
  -- A matching token alone is insufficient once its lease has expired.
  claim:=public.claim_search_now('cccccccc-cccc-cccc-cccc-cccccccccccc',
    '11111111-1111-1111-1111-111111111111','expired-lease-test',300);
  update public.job_searches set lease_expires_at=clock_timestamp()-interval '1 second'
    where id=(claim->>'id')::uuid;
  event:=jsonb_build_object('event_id',gen_random_uuid(),'kind','analysis','provider','groq',
    'status','failed','error','No se afirma ejecución sin lease vigente.');
  if public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
     (claim->>'claim_token')::uuid,event) then raise exception 'Se aceptó evidencia con lease vencida'; end if;
end; $$;

insert into public.job_searches(id,user_id,name,roles,cities,next_run_at)
values ('dddddddd-dddd-dddd-dddd-dddddddddddd','22222222-2222-2222-2222-222222222222',
  'Investigación B',array['Chofer'],array['Neuquén'],now()+interval '1 day');
set local role service_role;
do $$
declare claim jsonb; event jsonb;
begin
  claim:=public.claim_search_now('dddddddd-dddd-dddd-dddd-dddddddddddd',
    '22222222-2222-2222-2222-222222222222','cross-owner-test',300);
  event:=jsonb_build_object('event_id',(select id from public.web_research_events limit 1),
    'kind','analysis','provider','groq','status','failed','error','No se reasigna evidencia ajena.');
  if public.record_web_research_event((claim->>'id')::uuid,(claim->>'run_id')::uuid,
     (claim->>'claim_token')::uuid,event) then raise exception 'Se reasignó evidencia de otra cuenta'; end if;
end; $$;
reset role;

set local role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
do $$ begin
  if (select count(*) from public.web_research_events) <> 128 then raise exception 'El dueño no pudo leer historial'; end if;
  begin
    insert into public.web_research_events(id,user_id,search_id,run_id,kind,provider,status,started_at)
    values(gen_random_uuid(),'11111111-1111-1111-1111-111111111111',
      'cccccccc-cccc-cccc-cccc-cccccccccccc',gen_random_uuid(),'tavily_query','tavily','started',now());
    raise exception 'Cliente pudo fabricar evidencia';
  exception when insufficient_privilege then null; end;
  begin
    update public.web_research_events set status='failed';
    raise exception 'Cliente pudo cambiar evidencia';
  exception when insufficient_privilege then null; end;
  begin
    delete from public.web_research_events;
    raise exception 'Cliente pudo borrar evidencia';
  exception when insufficient_privilege then null; end;
  begin
    perform public.record_web_research_event(gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'{}');
    raise exception 'Cliente pudo ejecutar RPC de evidencia';
  exception when insufficient_privilege then null; end;
end; $$;
select set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',true);
do $$ begin
  if exists(select 1 from public.web_research_events) then raise exception 'Otra cuenta pudo ver las consultas'; end if;
end; $$;
reset role;
set local role anon;
do $$ begin
  begin
    perform 1 from public.web_research_events;
    raise exception 'Anon pudo leer historial';
  exception when insufficient_privilege then null; end;
end; $$;
reset role;
rollback;
