-- V4 fleet schema (Postgres). Replaces the in-memory store in infra/gateway/internal/fleet.
-- Telemetry and dataset storage are deliberately separate: no table here holds media.

create table if not exists devices (
  id text primary key,
  tier text not null check (tier in ('ALPHA','BETA','STABLE')),
  ring text not null check (ring in ('ALPHA','BETA','STABLE')),
  bench boolean not null default false,
  hardware text, firmware text, mcu text, model text,
  account_id text,
  public_key bytea,
  first_seen timestamptz not null default now(),
  last_seen timestamptz
);

create table if not exists heartbeats (
  device_id text references devices(id) on delete cascade,
  ts timestamptz not null,
  battery_pct int, charging boolean, safety text, brain text, link text,
  link_rtt_ms int, uptime_s int, soc_temp_c real, power_w real, mem_used_mb int,
  services_restarted int, safety_latency_p99_ms int
);
create index if not exists heartbeats_dev_ts on heartbeats (device_id, ts desc);

create table if not exists device_events (
  device_id text references devices(id) on delete cascade,
  ts timestamptz not null, kind text not null, summary text, attrs jsonb
);
create index if not exists events_dev_ts on device_events (device_id, ts desc);

-- ALPHA full logs only; beta/stable are trimmed to WARN+ before insert. Retention job prunes.
create table if not exists device_logs (
  device_id text references devices(id) on delete cascade,
  ts timestamptz not null, level text, service text, message text
);
create index if not exists logs_dev_ts on device_logs (device_id, ts desc);

create table if not exists releases (
  id text primary key, ring text not null, created_at timestamptz default now(),
  manifest bytea not null, rollout_percent int not null default 0, halted boolean not null default false
);

create table if not exists ota_status (
  device_id text references devices(id) on delete cascade,
  release_id text references releases(id),
  stage text, percent int, outcome text, updated_at timestamptz default now(),
  primary key (device_id, release_id)
);

create table if not exists feedback (
  id bigserial primary key, device_id text references devices(id) on delete set null,
  ts timestamptz default now(), text text, log_excerpt jsonb, app_version text
);

create table if not exists audit_log (
  id bigserial primary key, ts timestamptz default now(),
  actor text not null, action text not null, target text, result text
);

-- Dataset capture metadata (the data itself lives in the dataset object store, not here).
create table if not exists dataset_consents (
  id text primary key, granted_by text not null, granted_at timestamptz default now(),
  scope text not null, revoked_at timestamptz
);
create table if not exists dataset_sessions (
  id text primary key, device_id text references devices(id), consent_id text references dataset_consents(id) not null,
  streams text[] not null, started_at timestamptz, ended_at timestamptz, chunks int default 0
);
