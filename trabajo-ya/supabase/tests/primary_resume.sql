-- CV principal: persistencia, pertenencia y borrado sin perder la identidad.
begin;
insert into auth.users(id,raw_user_meta_data) values
  ('11111111-1111-1111-1111-111111111111','{"full_name":"Usuario A"}'),
  ('22222222-2222-2222-2222-222222222222','{"full_name":"Usuario B"}');
insert into public.resume_versions(id,user_id,name,original_filename,object_path,mime_type,size_bytes)
values ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb','22222222-2222-2222-2222-222222222222',
  'CV B','cv-b.pdf','22222222-2222-2222-2222-222222222222/cv-b.pdf','application/pdf',100);

set local role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
update public.profiles set city='Neuquén',headline='Chofer profesional',
  photo_path='11111111-1111-1111-1111-111111111111/foto.jpg';
select * from public.register_resume_version(
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','CV A','cv-a.pdf',
  '11111111-1111-1111-1111-111111111111/cv-a.pdf','application/pdf',100);
select * from public.register_resume_version(
  'cccccccc-cccc-cccc-cccc-cccccccccccc','CV A nuevo','cv-a-nuevo.pdf',
  '11111111-1111-1111-1111-111111111111/cv-a-nuevo.pdf','application/pdf',100);
do $$
begin
  if (select preferred_resume_id from public.profiles) <> 'cccccccc-cccc-cccc-cccc-cccccccccccc'::uuid then
    raise exception 'El CV nuevo no quedó principal en la cuenta';
  end if;
  if not exists (select 1 from public.profiles where full_name='Usuario A'
    and city='Neuquén' and headline='Chofer profesional'
    and photo_path='11111111-1111-1111-1111-111111111111/foto.jpg') then
    raise exception 'Registrar CV borró datos del perfil';
  end if;
  begin
    update public.profiles set preferred_resume_id='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    raise exception 'Se eligió un CV ajeno';
  exception when foreign_key_violation then null; end;
  begin
    perform public.register_resume_version('dddddddd-dddd-dddd-dddd-dddddddddddd',
      'Objeto ajeno','otro.pdf','22222222-2222-2222-2222-222222222222/otro.pdf','application/pdf',100);
    raise exception 'Se registró una ruta de otra cuenta';
  exception when check_violation then null; end;
  if exists(select 1 from public.resume_versions where id='dddddddd-dddd-dddd-dddd-dddddddddddd') then
    raise exception 'El registro inválido no fue atómico';
  end if;
  update public.profiles set preferred_resume_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
end;
$$;
reset role;
-- Recuperar la cuenta desde otro contexto conserva la elección del CV anterior.
set local role authenticated;
select set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',true);
do $$ begin
  if exists(select 1 from public.profiles where preferred_resume_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') then
    raise exception 'Usuario B pudo leer la preferencia de A';
  end if;
end; $$;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
do $$ begin
  if (select preferred_resume_id from public.profiles) <> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'::uuid then
    raise exception 'No se conservó la elección del CV principal';
  end if;
end; $$;
delete from public.resume_versions where id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
do $$ begin
  if not exists(select 1 from public.profiles where user_id='11111111-1111-1111-1111-111111111111'
    and preferred_resume_id is null and full_name='Usuario A' and city='Neuquén') then
    raise exception 'Borrar CV principal borró el dueño o los datos del perfil';
  end if;
end; $$;
reset role;
set local role anon;
do $$ begin
  begin
    perform public.register_resume_version('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
      'Sin sesión','anon.pdf','anon/anon.pdf','application/pdf',100);
    raise exception 'Anon pudo registrar un CV';
  exception when insufficient_privilege then null; end;
end; $$;
reset role;
rollback;
