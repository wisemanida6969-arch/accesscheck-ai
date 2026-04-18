-- AccessCheck AI — Supabase Tables

create table if not exists accessibility_reports (
  id           uuid default gen_random_uuid() primary key,
  user_email   text not null,
  url          text not null,
  score        integer,
  total_issues integer,
  result_json  text,
  created_at   timestamptz default now()
);

create table if not exists subscriptions (
  id          uuid default gen_random_uuid() primary key,
  user_email  text not null unique,
  status      text not null default 'active',  -- active | cancelled
  paddle_id   text,
  created_at  timestamptz default now(),
  expires_at  timestamptz
);

-- Index for fast lookup
create index on accessibility_reports (user_email);
create index on subscriptions (user_email, status);
