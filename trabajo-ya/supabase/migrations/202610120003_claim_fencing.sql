-- El servidor puede comprobar su lease antes de insertar resultados o enviar.
-- Esta comprobación debe repetirse antes de cada efecto externo; no prolonga la lease.
create function public.assert_search_claim(p_search_id uuid, p_claim_token uuid)
returns boolean language sql security definer set search_path = '' as $$
  select exists (
    select 1 from public.job_searches
    where id = p_search_id and claim_token = p_claim_token and lease_expires_at > now()
  )
$$;
revoke all on function public.assert_search_claim(uuid,uuid) from public, anon, authenticated;
grant execute on function public.assert_search_claim(uuid,uuid) to service_role;

-- Una edición del usuario posterior al inicio conserva el next_run_at recalculado.
-- El timestamp inicial del claim y started_at coinciden por now() transaccional;
-- el backend debe recalcular next_run_at en el mismo PATCH que cambia horario.
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
    next_run_at = case when search_row.updated_at > run_row.started_at then search_row.next_run_at else p_next_run_at end,
    last_run_at = case when p_status = 'completed' then now() else search_row.last_run_at end,
    claim_token = null, lease_expires_at = null
    where id = p_search_id;
  return true;
end;
$$;
revoke all on function public.complete_search_run(uuid,uuid,uuid,text,timestamptz,integer,text) from public, anon, authenticated;
grant execute on function public.complete_search_run(uuid,uuid,uuid,text,timestamptz,integer,text) to service_role;
