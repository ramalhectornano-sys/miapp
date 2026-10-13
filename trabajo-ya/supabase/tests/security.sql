-- Ejecutar como postgres. Todo queda dentro de una transacción que se revierte.
-- Verifica RLS, privilegios de columnas, aislamiento relacional y funciones servidor.
begin;
insert into auth.users(id,raw_user_meta_data) values
  ('11111111-1111-1111-1111-111111111111','{"full_name":"Usuario A"}'),
  ('22222222-2222-2222-2222-222222222222','{"full_name":"Usuario B"}');
insert into public.resume_versions(id,user_id,name,original_filename,object_path,mime_type,size_bytes) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','11111111-1111-1111-1111-111111111111','CV A','cv-a.pdf','11111111-1111-1111-1111-111111111111/cv-a.pdf','application/pdf',100),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb','22222222-2222-2222-2222-222222222222','CV B','cv-b.pdf','22222222-2222-2222-2222-222222222222/cv-b.pdf','application/pdf',100);
insert into public.job_searches(id,user_id,name,roles,cities,next_run_at,preferred_resume_id) values
  ('cccccccc-cccc-cccc-cccc-cccccccccccc','11111111-1111-1111-1111-111111111111','Búsqueda A',array['Chofer'],array['Rincón de los Sauces'],now()-interval '1 minute','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');
insert into public.jobs(id,user_id,source,fingerprint,company,title,recipient_email,recipient_verified_at,source_authorized) values
  ('dddddddd-dddd-dddd-dddd-dddddddddddd','11111111-1111-1111-1111-111111111111','authorized-feed','test-job-1','Empresa A','Chofer','rrhh@example.com',now(),true),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2','11111111-1111-1111-1111-111111111111','authorized-feed','test-job-2','Empresa B','Chofer','rrhh2@example.com',now(),true),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd3','11111111-1111-1111-1111-111111111111','authorized-feed','test-job-3','Empresa C','Chofer','rrhh3@example.com',null,true);
insert into public.email_connections(id,user_id,provider,email,scopes) values
  ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee','11111111-1111-1111-1111-111111111111','google','usuario-a@example.com',array['https://www.googleapis.com/auth/gmail.send']);
insert into public.applications(id,user_id,job_id,search_id,resume_id,email_connection_id,company,job_title,recipient_email,recipient_verified_at,subject,body) values
  ('ffffffff-ffff-ffff-ffff-ffffffffffff','11111111-1111-1111-1111-111111111111','dddddddd-dddd-dddd-dddd-dddddddddddd','cccccccc-cccc-cccc-cccc-cccccccccccc','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee','Empresa A','Chofer','rrhh@example.com',now(),'Postulación','Mensaje confirmado por usuario'),
  ('ffffffff-ffff-ffff-ffff-fffffffffff2','11111111-1111-1111-1111-111111111111','dddddddd-dddd-dddd-dddd-ddddddddddd2','cccccccc-cccc-cccc-cccc-cccccccccccc','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee','Empresa B','Chofer','rrhh2@example.com',now(),'Postulación','Mensaje confirmado por usuario'),
  ('ffffffff-ffff-ffff-ffff-fffffffffff3','11111111-1111-1111-1111-111111111111','dddddddd-dddd-dddd-dddd-ddddddddddd3','cccccccc-cccc-cccc-cccc-cccccccccccc','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee','Empresa C','Chofer','rrhh3@example.com',now(),'Postulación','Mensaje confirmado por usuario');
set constraints all immediate;

set local role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
do $$
begin
  if (select count(*) from public.profiles) <> 1 then raise exception 'Fallo aislamiento profiles'; end if;
  if (select count(*) from public.resume_versions) <> 1 then raise exception 'Fallo aislamiento CV'; end if;
  update public.profiles set city='Neuquén' where user_id='11111111-1111-1111-1111-111111111111';
  update public.profiles set city='Intrusión' where user_id='22222222-2222-2222-2222-222222222222';
  if found then raise exception 'Usuario A pudo editar usuario B'; end if;
  begin
    insert into public.work_experiences(user_id,company,role)
    values ('22222222-2222-2222-2222-222222222222','Intrusión','Intrusión');
    raise exception 'RLS permitió insertar para otra cuenta';
  exception when insufficient_privilege then null; end;
  begin
    update public.applications set status='sent',provider_message_id='FALSO';
    raise exception 'Cliente pudo falsificar un envío';
  exception when insufficient_privilege then null; end;
  begin
    update public.resume_versions set extracted_text='Experiencia inventada';
    raise exception 'Cliente pudo falsificar extracción';
  exception when insufficient_privilege then null; end;
  begin
    insert into public.chat_messages(user_id,role,content)
    values ('11111111-1111-1111-1111-111111111111','assistant','Falso asistente');
    raise exception 'Cliente pudo falsificar asistente';
  exception when insufficient_privilege then null; end;
  begin
    perform public.claim_due_searches('cliente');
    raise exception 'Cliente pudo usar scheduler';
  exception when insufficient_privilege then null; end;
  begin
    perform public.get_email_secret('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee','11111111-1111-1111-1111-111111111111');
    raise exception 'Cliente pudo acceder tokens';
  exception when insufficient_privilege then null; end;
  begin
    insert into storage.objects(bucket_id,name) values ('resumes','22222222-2222-2222-2222-222222222222/intrusion.pdf');
    raise exception 'Cliente pudo subir un CV ajeno';
  exception when insufficient_privilege then null; end;
  insert into storage.objects(bucket_id,name) values ('resumes','11111111-1111-1111-1111-111111111111/propio.pdf');
end;
$$;
reset role;

do $$
begin
  begin
    update public.job_searches set preferred_resume_id='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    raise exception 'Clave foránea permitió CV de otra cuenta';
  exception when foreign_key_violation then null; end;
  begin
    update public.applications set status='sent' where id='ffffffff-ffff-ffff-ffff-ffffffffffff';
    raise exception 'Se aceptó envío sin confirmación';
  exception when check_violation then null; end;
  begin
    insert into public.jobs(user_id,source,fingerprint,company,title)
    values ('11111111-1111-1111-1111-111111111111','otra','test-job-1','Duplicado','Chofer');
    raise exception 'Dedup permitió duplicado';
  exception when unique_violation then null; end;
end;
$$;

set local role service_role;
do $$
declare claim jsonb; claim2 jsonb; okay boolean;
begin
  select item into claim from public.claim_due_searches('worker-a') item limit 1;
  if claim is null then raise exception 'No se creó claim'; end if;
  select item into claim2 from public.claim_due_searches('worker-b') item limit 1;
  if claim2 is not null then raise exception 'Lease permitió doble ejecución'; end if;
  okay := public.complete_search_run((claim->>'id')::uuid,gen_random_uuid(),(claim->>'run_id')::uuid,'completed',now()+interval '1 day');
  if okay then raise exception 'Se aceptó claim incorrecto'; end if;
  okay := public.complete_search_run((claim->>'id')::uuid,(claim->>'claim_token')::uuid,(claim->>'run_id')::uuid,'blocked',now()+interval '1 day',0,'Fuente aún no conectada');
  if (select last_run_at from public.job_searches where id = (claim->>'id')::uuid) is not null then raise exception 'Tarea bloqueada mostrada como búsqueda completada'; end if;
  if not okay then raise exception 'No se pudo cerrar claim'; end if;
  okay := public.complete_search_run((claim->>'id')::uuid,(claim->>'claim_token')::uuid,(claim->>'run_id')::uuid,'completed',now()+interval '1 day');
  if okay then raise exception 'Se completó el mismo run dos veces'; end if;
  claim := public.claim_search_now('cccccccc-cccc-cccc-cccc-cccccccccccc','11111111-1111-1111-1111-111111111111','manual-worker');
  if claim is null or not public.assert_search_claim((claim->>'id')::uuid,(claim->>'claim_token')::uuid) then
    raise exception 'No se comprobó lease de ejecución manual';
  end if;
  if public.assert_search_claim((claim->>'id')::uuid,gen_random_uuid()) then raise exception 'Fence aceptó token ajeno'; end if;
  -- now() es estable dentro de esta prueba transaccional: simular un run iniciado
  -- en una transacción anterior permite comprobar una edición posterior real.
  update public.job_search_runs set started_at=now()-interval '1 second' where id=(claim->>'run_id')::uuid;
  update public.job_searches set next_run_at=now()+interval '2 days' where id=(claim->>'id')::uuid;
  okay := public.complete_search_run((claim->>'id')::uuid,(claim->>'claim_token')::uuid,(claim->>'run_id')::uuid,'completed',now()+interval '1 day');
  if not okay then raise exception 'No completó run editado'; end if;
  if (select next_run_at from public.job_searches where id=(claim->>'id')::uuid) <> now()+interval '2 days' then
    raise exception 'Sobreescribió el horario editado por el usuario';
  end if;
  if public.claim_application_send('ffffffff-ffff-ffff-ffff-ffffffffffff','11111111-1111-1111-1111-111111111111') is not null then
    raise exception 'Envió sin consentimiento';
  end if;
  perform public.store_email_secret('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee','11111111-1111-1111-1111-111111111111','TEST-CIPHERTEXT-ONLY');
  if public.get_email_secret('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee','22222222-2222-2222-2222-222222222222') is not null then
    raise exception 'RPC secret permitió usuario incorrecto';
  end if;
  perform public.store_oauth_state(repeat('a',64),'11111111-1111-1111-1111-111111111111','google','TEST-ENCRYPTED-VERIFIER','http://localhost/callback',array['gmail.send'],now()+interval '10 minutes');
  if public.consume_oauth_state(repeat('a',64),'google') is null then raise exception 'OAuth no se consumió'; end if;
  if public.consume_oauth_state(repeat('a',64),'google') is not null then raise exception 'OAuth permitió replay'; end if;
end;
$$;
insert into public.sending_consents(id,user_id,search_id,resume_id,email_connection_id,authorized_sources,daily_limit,authorization_text,expires_at) values
  ('abababab-abab-abab-abab-abababababab','11111111-1111-1111-1111-111111111111','cccccccc-cccc-cccc-cccc-cccccccccccc','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',array['authorized-feed'],1,'Autorizo los envíos automáticos de esta búsqueda',now()+interval '30 days');
update public.job_searches set auto_apply=true,consent_id='abababab-abab-abab-abab-abababababab';
do $$
begin
  if public.claim_application_send('ffffffff-ffff-ffff-ffff-ffffffffffff','11111111-1111-1111-1111-111111111111') is null then raise exception 'No reservó envío autorizado'; end if;
  if public.claim_application_send('ffffffff-ffff-ffff-ffff-ffffffffffff','11111111-1111-1111-1111-111111111111') is not null then raise exception 'Permitió duplicar intento'; end if;
  if public.claim_application_send('ffffffff-ffff-ffff-ffff-fffffffffff2','11111111-1111-1111-1111-111111111111') is not null then raise exception 'Ignoró límite diario'; end if;
  if public.claim_application_send('ffffffff-ffff-ffff-ffff-fffffffffff3','11111111-1111-1111-1111-111111111111',true,'Enviar esta postulación') is not null then raise exception 'Ignoró destinatario sin verificar'; end if;
end;
$$;
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',true);
do $$ begin
  if public.revoke_sending_consent('abababab-abab-abab-abab-abababababab') then raise exception 'Usuario B revocó consentimiento A'; end if;
end; $$;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
do $$ begin
  if not public.revoke_sending_consent('abababab-abab-abab-abab-abababababab') then raise exception 'No revocó consentimiento propio'; end if;
end; $$;
reset role;
do $$ begin
  if (select auto_apply from public.job_searches where id='cccccccc-cccc-cccc-cccc-cccccccccccc') then raise exception 'Revocación dejó auto_apply activo'; end if;
end; $$;
rollback;
