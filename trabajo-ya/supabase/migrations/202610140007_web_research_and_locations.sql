-- Structured search geography and a private, lease-fenced record of research.
-- Existing searches remain city-only until the backend resolves their location.
create function public.valid_search_location(p_location jsonb) returns boolean
language plpgsql immutable set search_path = '' as $$
begin
  if p_location is null then return true; end if;
  if pg_catalog.jsonb_typeof(p_location) <> 'object' or
     pg_catalog.octet_length(p_location::text) > 8192 then return false; end if;
  if (p_location ? 'latitude') <> (p_location ? 'longitude') then return false; end if;
  if p_location ? 'latitude' then
    if pg_catalog.jsonb_typeof(p_location->'latitude') <> 'number' or
       pg_catalog.jsonb_typeof(p_location->'longitude') <> 'number' then return false; end if;
    if (p_location->>'latitude')::numeric not between -90 and 90 or
       (p_location->>'longitude')::numeric not between -180 and 180 then return false; end if;
  end if;
  return true;
exception when others then return false;
end;
$$;
revoke all on function public.valid_search_location(jsonb) from public, anon;
grant execute on function public.valid_search_location(jsonb) to authenticated, service_role;

alter table public.job_searches
  add column province text check (province is null or length(province) <= 120),
  add column country text not null default 'Argentina' check (length(btrim(country)) between 1 and 120),
  add column radius_km integer not null default 0 check (radius_km between 0 and 1000),
  add column research_mode text not null default 'general' check (research_mode in ('general', 'legacy')),
  add column location jsonb check (public.valid_search_location(location));

-- This is a log URL validator, not a DNS or page-permission verifier. The
-- backend separately validates destinations before every HTTP request.
create function public.safe_research_url(p_url text) returns boolean
language plpgsql immutable set search_path = '' as $$
declare authority text; host text; query_part text;
begin
  if p_url is null then return true; end if;
  if length(p_url) not between 1 and 2048 or p_url ~ '[[:space:][:cntrl:]]' or position('#' in p_url) > 0 or
     p_url !~ '^https://[A-Za-z0-9.-]+(:443)?([/?#]|$)' then return false; end if;
  authority := pg_catalog.substring(p_url, '^https://([^/?#]+)');
  if authority is null or position('@' in authority) > 0 then return false; end if;
  host := pg_catalog.regexp_replace(pg_catalog.lower(authority), ':443$', '');
  if host !~ '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$' or
     host ~ '(^|\.)(localhost|local|internal|onion|test|invalid|example)$' or
     host ~ '\.\.' then return false; end if;
  query_part := pg_catalog.substring(p_url, '\?([^#]*)');
  if query_part is not null and (query_part ~ '%' or
     query_part ~* '(^|&)([^=&]*(token|secret|password|authorization|api.?key)[^=&]*|code|state)=') then
    return false;
  end if;
  return p_url !~* '(gsk_|tvly-(dev-|prod-)?[a-z0-9_-]{12}|sb_secret_|Bearer[[:space:]]|access_token|refresh_token)';
exception when others then return false;
end;
$$;
revoke all on function public.safe_research_url(text) from public, anon, authenticated;
grant execute on function public.safe_research_url(text) to service_role;

create table public.web_research_events (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  search_id uuid not null,
  run_id uuid not null,
  kind text not null check (kind in ('tavily_query','public_page','geocode','analysis')),
  provider text not null check (length(provider) between 1 and 80),
  query text check (query is null or length(query) <= 1000),
  url text check (public.safe_research_url(url)),
  status text not null check (status in ('started','succeeded','failed','blocked')),
  started_at timestamptz not null,
  finished_at timestamptz,
  recorded_at timestamptz not null default clock_timestamp(),
  http_status integer check (http_status between 100 and 599),
  provider_request_id text check (provider_request_id is null or length(provider_request_id) <= 128),
  credits numeric check (credits between 0 and 10000),
  result_urls text[] not null default '{}' check (cardinality(result_urls) <= 20),
  source_hosts text[] not null default '{}' check (cardinality(source_hosts) <= 20),
  metadata jsonb not null default '{}' check (jsonb_typeof(metadata)='object' and octet_length(metadata::text) <= 4096),
  error text check (error is null or length(error) <= 1000),
  foreign key (user_id, search_id) references public.job_searches(user_id,id) on delete cascade,
  foreign key (user_id, search_id, run_id) references public.job_search_runs(user_id,search_id,id) on delete cascade,
  check ((status='started') = (finished_at is null)),
  check (finished_at is null or finished_at >= started_at)
);
create index web_research_by_search on public.web_research_events(user_id,search_id,started_at desc,id);
alter table public.web_research_events enable row level security;
create policy own_read on public.web_research_events for select to authenticated
  using (user_id=(select auth.uid()));
-- Clients can read their own research; they cannot fabricate queries or results.
-- Even service_role uses the constrained RPC instead of unrestricted writes.
revoke all on public.web_research_events from public, anon, authenticated, service_role;
grant select on public.web_research_events to authenticated, service_role;

create function public.record_web_research_event(
  p_search_id uuid, p_run_id uuid, p_claim_token uuid, p_event jsonb
) returns boolean
language plpgsql security definer set search_path = '' as $$
declare
  search_row public.job_searches%rowtype;
  run_row public.job_search_runs%rowtype;
  existing public.web_research_events%rowtype;
  event_id uuid; event_started timestamptz; event_finished timestamptz;
  event_urls text[]; event_hosts text[]; event_meta jsonb;
  event_status text; event_http integer; event_credits numeric;
  item text; field_name text;
begin
  if pg_catalog.jsonb_typeof(p_event) is distinct from 'object' or
     pg_catalog.octet_length(p_event::text) > 24576 then return false; end if;
  -- Never persist provider credentials, OAuth tokens or caller-supplied owners.
  for field_name in select pg_catalog.jsonb_object_keys(p_event) loop
    if field_name not in ('event_id','kind','provider','query','url','status','started_at',
      'finished_at','http_status','provider_request_id','credits','result_urls','source_hosts','metadata','error') then
      return false;
    end if;
  end loop;
  -- The recorder accepts bounded public facts, never arbitrary provider
  -- response bodies, headers, prompts or nested objects disguised as strings.
  for field_name in select pg_catalog.unnest(array['event_id','kind','provider','query','url','status',
    'started_at','finished_at','provider_request_id','error']) loop
    if p_event ? field_name and pg_catalog.jsonb_typeof(p_event->field_name) not in ('string','null') then
      return false;
    end if;
  end loop;
  for field_name in select pg_catalog.unnest(array['http_status','credits']) loop
    if p_event ? field_name and pg_catalog.jsonb_typeof(p_event->field_name) not in ('number','null') then
      return false;
    end if;
  end loop;
  if p_event::text ~* '(gsk_|tvly-(dev-|prod-)?[a-z0-9_-]{12}|sb_secret_|Bearer[[:space:]]|access_token|refresh_token|client_secret|api_key["[:space:]]*[:=])' then
    return false;
  end if;
  event_id := (p_event->>'event_id')::uuid;
  event_status := p_event->>'status';
  if event_id is null or event_status is null or event_status not in ('started','succeeded','failed','blocked') or
     coalesce(p_event->>'kind','') not in ('tavily_query','public_page','geocode','analysis') or
     coalesce(length(p_event->>'provider'),0) not between 1 and 80 or
     coalesce(length(p_event->>'query'),0) > 1000 or coalesce(length(p_event->>'error'),0) > 1000 or
     coalesce(length(p_event->>'provider_request_id'),0) > 128 or
     not public.safe_research_url(p_event->>'url') then return false; end if;
  event_urls := '{}'; event_hosts := '{}';
  if p_event ? 'result_urls' then
    if pg_catalog.jsonb_typeof(p_event->'result_urls') <> 'array' or
       pg_catalog.jsonb_array_length(p_event->'result_urls') > 20 then return false; end if;
    for item in select pg_catalog.jsonb_array_elements_text(p_event->'result_urls') loop
      if item is null or not public.safe_research_url(item) then return false; end if;
      event_urls := pg_catalog.array_append(event_urls,item);
    end loop;
  end if;
  if p_event ? 'source_hosts' then
    if pg_catalog.jsonb_typeof(p_event->'source_hosts') <> 'array' or
       pg_catalog.jsonb_array_length(p_event->'source_hosts') > 20 then return false; end if;
    for item in select pg_catalog.jsonb_array_elements_text(p_event->'source_hosts') loop
      if item is null or length(item) > 253 or
         item !~ '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$' or
         not public.safe_research_url('https://' || item) then return false; end if;
      event_hosts := pg_catalog.array_append(event_hosts,item);
    end loop;
  end if;
  event_meta := coalesce(p_event->'metadata','{}');
  if pg_catalog.jsonb_typeof(event_meta) <> 'object' or
     pg_catalog.octet_length(event_meta::text) > 4096 then return false; end if;
  for field_name in select pg_catalog.jsonb_object_keys(event_meta) loop
    if field_name not in ('query_kind','parent_url','content_sha256','reason','result_count','query_index',
      'location_id','role','city','province','country','radius_km','source_id','attempt','provider_method',
      'verification_status','allowed_by','from_cache','language','depth','http_calls','discovered_count',
      'eligible_count','pages_considered','pages_verified','geocoding_provider','model','latency_ms',
      'timeout_seconds','error_code') then return false; end if;
    if pg_catalog.jsonb_typeof(event_meta->field_name) not in ('string','number','boolean','null') or
       coalesce(length(event_meta->>field_name),0) > 1000 then return false; end if;
  end loop;
  if not public.safe_research_url(event_meta->>'parent_url') or
     (event_meta ? 'content_sha256' and coalesce(event_meta->>'content_sha256','') !~ '^[a-f0-9]{64}$') then
    return false;
  end if;
  event_http := (p_event->>'http_status')::integer;
  event_credits := (p_event->>'credits')::numeric;
  if (event_http is not null and event_http not between 100 and 599) or
     (event_credits is not null and event_credits not between 0 and 10000) then return false; end if;

  -- Locking the search serializes writers and the per-run record budget.
  select * into search_row from public.job_searches where id=p_search_id for update;
  if not found or search_row.claim_token is distinct from p_claim_token or
     search_row.lease_expires_at is null or search_row.lease_expires_at <= clock_timestamp() then return false; end if;
  select * into run_row from public.job_search_runs where id=p_run_id and search_id=p_search_id
    and user_id=search_row.user_id and claim_token=p_claim_token and status='running';
  if not found or search_row.updated_at > run_row.started_at then return false; end if;
  select * into existing from public.web_research_events where id=event_id for update;
  if found then
    if existing.search_id <> p_search_id or existing.run_id <> p_run_id or
       existing.user_id <> search_row.user_id or existing.status <> 'started' or event_status='started' or
       existing.kind is distinct from p_event->>'kind' or existing.provider is distinct from p_event->>'provider' or
       existing.query is distinct from p_event->>'query' or existing.url is distinct from p_event->>'url' then return false; end if;
    event_started := existing.started_at;
    event_finished := greatest(clock_timestamp(),event_started);
    update public.web_research_events set status=event_status, finished_at=event_finished,
      http_status=event_http,provider_request_id=p_event->>'provider_request_id',credits=event_credits,
      result_urls=event_urls,source_hosts=event_hosts,metadata=event_meta,error=p_event->>'error'
      where id=event_id;
    return true;
  end if;
  if (select count(*) from public.web_research_events where run_id=p_run_id) >= 128 then return false; end if;
  event_started := coalesce((p_event->>'started_at')::timestamptz,clock_timestamp());
  if event_started < run_row.started_at - interval '5 minutes' or
     event_started > clock_timestamp() + interval '30 seconds' then return false; end if;
  event_finished := case when event_status='started' then null else greatest(clock_timestamp(),event_started) end;
  insert into public.web_research_events(id,user_id,search_id,run_id,kind,provider,query,url,status,
    started_at,finished_at,http_status,provider_request_id,credits,result_urls,source_hosts,metadata,error)
  values (event_id,search_row.user_id,p_search_id,p_run_id,p_event->>'kind',p_event->>'provider',
    p_event->>'query',p_event->>'url',event_status,event_started,event_finished,event_http,
    p_event->>'provider_request_id',event_credits,event_urls,event_hosts,event_meta,p_event->>'error');
  return true;
exception when invalid_text_representation or numeric_value_out_of_range or datetime_field_overflow or
  invalid_datetime_format or check_violation or unique_violation or not_null_violation or
  invalid_parameter_value then return false;
end;
$$;
revoke all on function public.record_web_research_event(uuid,uuid,uuid,jsonb) from public, anon, authenticated;
grant execute on function public.record_web_research_event(uuid,uuid,uuid,jsonb) to service_role;
