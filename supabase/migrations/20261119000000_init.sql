-- Specta: accounts, saved TZ checks (chat + document state) and client share links.
-- Run once in the Supabase SQL editor (Dashboard → SQL → New query) or with `supabase db push`.
-- The backend talks to these tables with the secret key (server-side only) and always filters by user_id;
-- RLS is still enabled so the tables are safe if a browser ever talks to the Data API directly.

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  name text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.tz_sessions (
  id text primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  title text not null default '',
  filename text not null default '',
  score_before int,
  score int,
  status text not null default 'active',          -- active | done
  share_token text unique,                          -- public read-only report link
  state jsonb not null default '{}'::jsonb,         -- document, findings, questions, versions, debate, summary
  events jsonb not null default '[]'::jsonb,        -- chat event log (unified event schema)
  cost_usd numeric(10, 5) not null default 0,       -- Claude API spend for this check
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists tz_sessions_user_idx on public.tz_sessions (user_id, updated_at desc);

alter table public.profiles enable row level security;
alter table public.tz_sessions enable row level security;

drop policy if exists "own profile read" on public.profiles;
create policy "own profile read" on public.profiles for select to authenticated using ((select auth.uid()) = id);
drop policy if exists "own profile write" on public.profiles;
create policy "own profile write" on public.profiles for update to authenticated
  using ((select auth.uid()) = id) with check ((select auth.uid()) = id);

drop policy if exists "own sessions read" on public.tz_sessions;
create policy "own sessions read" on public.tz_sessions for select to authenticated using ((select auth.uid()) = user_id);
drop policy if exists "own sessions insert" on public.tz_sessions;
create policy "own sessions insert" on public.tz_sessions for insert to authenticated with check ((select auth.uid()) = user_id);
drop policy if exists "own sessions update" on public.tz_sessions;
create policy "own sessions update" on public.tz_sessions for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
drop policy if exists "own sessions delete" on public.tz_sessions;
create policy "own sessions delete" on public.tz_sessions for delete to authenticated using ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.tz_sessions to authenticated;
grant select, update on public.profiles to authenticated;
