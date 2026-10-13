-- Persist the primary CV in the account rather than in one app session.
alter table public.profiles add column preferred_resume_id uuid;
alter table public.profiles add constraint profile_preferred_resume_owner
  foreign key (user_id, preferred_resume_id)
  references public.resume_versions(user_id, id)
  on delete set null (preferred_resume_id);

-- Register the uploaded object and select it as primary in one transaction.
-- The caller keeps its own RLS permissions; this function cannot read or write
-- another account's CV, and object ownership/size/type constraints still apply.
create function public.register_resume_version(
  p_id uuid, p_name text, p_original_filename text, p_object_path text,
  p_mime_type text, p_size_bytes bigint
) returns setof public.resume_versions
language plpgsql security invoker set search_path = '' as $$
declare
  owner_id uuid := auth.uid();
  registered public.resume_versions;
begin
  if owner_id is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;
  insert into public.resume_versions(
    id, user_id, name, original_filename, object_path, mime_type, size_bytes
  ) values (
    p_id, owner_id, p_name, p_original_filename, p_object_path, p_mime_type, p_size_bytes
  ) returning * into registered;
  insert into public.profiles(user_id, preferred_resume_id)
  values (owner_id, p_id)
  on conflict (user_id) do update set preferred_resume_id = excluded.preferred_resume_id;
  return next registered;
end;
$$;
revoke all on function public.register_resume_version(uuid,text,text,text,text,bigint)
  from public, anon;
grant execute on function public.register_resume_version(uuid,text,text,text,text,bigint)
  to authenticated;
