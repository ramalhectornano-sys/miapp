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
