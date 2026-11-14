-- Application tables are server-only; browsers have no direct database access.
create table if not exists public.lazarus_jobs (
  id text primary key,
  data jsonb not null,
  revision bigint not null default 1,
  next_event_seq bigint not null default 0,
  created_at timestamptz not null default now(),
  check (data->>'id' = id)
);
create table if not exists public.lazarus_events (
  job_id text not null references public.lazarus_jobs(id),
  seq bigint not null,
  event_id uuid not null unique,
  payload jsonb not null,
  primary key (job_id, seq)
);
create table if not exists public.lazarus_keys (
  job_id text not null references public.lazarus_jobs(id),
  key_id text not null,
  envelope jsonb not null,
  primary key (job_id, key_id)
);
create table if not exists public.lazarus_artifacts (
  job_id text not null references public.lazarus_jobs(id),
  path text not null,
  object_key text not null,
  sha256 text not null,
  bytes bigint not null,
  primary key (job_id, path)
);
alter table public.lazarus_jobs enable row level security;
alter table public.lazarus_events enable row level security;
alter table public.lazarus_keys enable row level security;
alter table public.lazarus_artifacts enable row level security;
revoke all on public.lazarus_jobs, public.lazarus_events, public.lazarus_keys, public.lazarus_artifacts from public, anon, authenticated;
grant all on public.lazarus_jobs, public.lazarus_events, public.lazarus_keys, public.lazarus_artifacts to service_role;

-- Compare-and-swap prevents lost updates. A stale revision is a retryable conflict.
create or replace function public.lazarus_save(p_id text, p_data jsonb, p_revision bigint)
returns bigint language plpgsql security invoker set search_path = '' as $$
declare result bigint;
begin
  if p_revision = 0 then
    insert into public.lazarus_jobs(id, data) values (p_id, p_data)
      on conflict do nothing returning revision into result;
  else
    update public.lazarus_jobs set data=p_data, revision=revision+1
      where id=p_id and revision=p_revision returning revision into result;
  end if;
  if result is null then raise exception 'Revision conflict' using errcode='PT409'; end if;
  return result;
end $$;

-- A caller-supplied UUID makes an event retry safe after an ambiguous HTTP response.
create or replace function public.lazarus_append_event(p_id text, p_event_id uuid, p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare existing jsonb; sequence_id bigint;
begin
  perform 1 from public.lazarus_jobs where id=p_id for update;
  if not found then raise exception 'Archive not found' using errcode='P0002'; end if;
  select payload into existing from public.lazarus_events where job_id=p_id and event_id=p_event_id;
  if existing is not null then return existing; end if;
  update public.lazarus_jobs set next_event_seq=next_event_seq+1 where id=p_id
    returning next_event_seq-1 into sequence_id;
  existing := p_payload || jsonb_build_object('seq', sequence_id);
  insert into public.lazarus_events(job_id,seq,event_id,payload) values(p_id,sequence_id,p_event_id,existing);
  return existing;
end $$;
revoke all on function public.lazarus_save(text,jsonb,bigint) from public, anon, authenticated;
revoke all on function public.lazarus_append_event(text,uuid,jsonb) from public, anon, authenticated;
grant execute on function public.lazarus_save(text,jsonb,bigint) to service_role;
grant execute on function public.lazarus_append_event(text,uuid,jsonb) to service_role;

-- Other project policies must not accidentally expose Lazarus objects.
-- Restrictive policies combine with all permissive policies; service_role bypasses RLS.
drop policy if exists lazarus_server_only_objects on storage.objects;
create policy lazarus_server_only_objects on storage.objects as restrictive
  for all to anon, authenticated
  using (bucket_id <> 'lazarus-archives')
  with check (bucket_id <> 'lazarus-archives');
