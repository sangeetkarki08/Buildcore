-- =====================================================================
--  BuildCore — Supabase schema
--  Full migration of the app's in-memory State to Postgres.
--
--  Design
--  ------
--  The app keeps every collection as an array of plain objects whose
--  shape lives only in the front-end. To migrate without data loss and
--  with a single, uniform sync path, every collection table stores the
--  original object verbatim in a `data jsonb` column. Commonly-queried
--  fields are exposed as GENERATED columns so you still get typed,
--  indexable, SQL-friendly access for reporting / external CRUD.
--
--  Tenancy: one workspace per authenticated user. Every row carries
--  `user_id = auth.uid()` and Row Level Security isolates users.
--
--  Apply this file in the Supabase SQL editor (or `supabase db push`).
-- =====================================================================

-- ---------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------
create extension if not exists "pgcrypto";   -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- Profiles — mirrors auth.users with the role chosen at sign-up
-- ---------------------------------------------------------------------
create table if not exists public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text,
  full_name   text,
  role        text default 'ceo',
  created_at  timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles read own"   on public.profiles;
drop policy if exists "profiles upsert own"  on public.profiles;
drop policy if exists "profiles update own"  on public.profiles;

create policy "profiles read own"  on public.profiles
  for select using (auth.uid() = id);
create policy "profiles upsert own" on public.profiles
  for insert with check (auth.uid() = id);
create policy "profiles update own" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

-- Create a profile row automatically on sign-up, pulling name/role from
-- the metadata passed to supabase.auth.signUp({ options: { data }}).
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name, role)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.email),
    coalesce(new.raw_user_meta_data ->> 'role', 'ceo')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------
-- Generic helper: a collection table + RLS + updated_at trigger.
--   * user_id  — owner (defaults to the caller)
--   * id       — the record's natural id (text); generated for logs
--   * data     — the original front-end object, untouched
-- ---------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

do $$
declare
  tbl text;
  collection_tables text[] := array[
    'projects', 'tenders', 'materials', 'ncrs', 'ra_bills',
    'purchase_orders', 'dprs', 'variation_orders', 'risks',
    'photos', 'assets', 'asset_categories', 'asset_locations',
    'asset_allocations', 'asset_transfers', 'asset_maintenance',
    'asset_breakdowns', 'asset_fuel_logs', 'asset_inspections',
    'asset_documents', 'asset_disposals', 'asset_notifications',
    'activity', 'audit_log'
  ];
begin
  foreach tbl in array collection_tables loop
    execute format($f$
      create table if not exists public.%I (
        user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
        id          text not null default gen_random_uuid()::text,
        data        jsonb not null,
        created_at  timestamptz not null default now(),
        updated_at  timestamptz not null default now(),
        primary key (user_id, id)
      );
      alter table public.%I enable row level security;

      drop policy if exists "owner all" on public.%I;
      create policy "owner all" on public.%I
        for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

      drop trigger if exists set_updated_at on public.%I;
      create trigger set_updated_at before update on public.%I
        for each row execute function public.touch_updated_at();
    $f$, tbl, tbl, tbl, tbl, tbl, tbl);
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- Typed, queryable views over the JSONB for the core business entities.
-- These give external tools / dashboards real columns without the app
-- having to maintain a second write path.
-- ---------------------------------------------------------------------
create or replace view public.v_projects as
select user_id, id,
       data ->> 'name'                  as name,
       data ->> 'client'                as client,
       data ->> 'loc'                   as location,
       (data ->> 'value')::numeric      as value,
       (data ->> 'progress')::numeric   as progress,
       (data ->> 'margin')::numeric     as margin,
       data ->> 'end'                   as end_label,
       data ->> 'status'                as status,
       (data ->> 'team')::int           as team,
       (data ->> 'issues')::int         as issues,
       updated_at
from public.projects;

create or replace view public.v_tenders as
select user_id, id,
       data ->> 'name'              as name,
       data ->> 'client'            as client,
       (data ->> 'value')::numeric  as value,
       (data ->> 'dueIn')::int      as due_in,
       (data ->> 'prob')::int       as prob,
       data ->> 'stage'             as stage,
       updated_at
from public.tenders;

create or replace view public.v_materials as
select user_id, id                   as code,
       data ->> 'name'               as name,
       data ->> 'unit'               as unit,
       (data ->> 'stock')::numeric   as stock,
       (data ->> 'reorder')::numeric as reorder,
       (data ->> 'days')::int        as cover_days,
       (data ->> 'value')::numeric   as value,
       data ->> 'status'             as status,
       updated_at
from public.materials;

create or replace view public.v_ra_bills as
select user_id, id,
       data ->> 'proj'              as project_id,
       data ->> 'period'            as period,
       (data ->> 'gross')::numeric  as gross,
       (data ->> 'net')::numeric    as net,
       data ->> 'status'            as status,
       updated_at
from public.ra_bills;

create or replace view public.v_purchase_orders as
select user_id, id,
       data ->> 'vendor'            as vendor,
       data ->> 'items'             as items,
       (data ->> 'value')::numeric  as value,
       data ->> 'status'            as status,
       updated_at
from public.purchase_orders;

create or replace view public.v_assets as
select user_id, id,
       data ->> 'qr'                    as qr_code,
       data ->> 'name'                  as asset_name,
       data ->> 'category'              as category,
       data ->> 'type'                  as asset_type,
       data ->> 'brand'                 as brand,
       data ->> 'model'                 as model,
       data ->> 'serial'                as serial_number,
       data ->> 'regNo'                 as registration_number,
       data ->> 'ownership'             as ownership_type,
       data ->> 'condition'             as current_condition,
       data ->> 'status'                as current_status,
       data ->> 'location'              as current_location,
       data ->> 'projectId'             as project_id,
       data ->> 'department'            as department,
       data ->> 'assignedTo'            as assigned_user,
       data ->> 'operator'              as operator,
       nullif(data ->> 'purchaseCost','')::numeric as purchase_cost,
       data ->> 'purchaseDate'          as purchase_date,
       data ->> 'warrantyUntil'         as warranty_until,
       data ->> 'nextMaintenanceDue'    as next_maintenance_due,
       data ->> 'calibrationDue'        as calibration_due,
       data ->> 'insuranceExpiry'       as insurance_expiry,
       updated_at
from public.assets;

create or replace view public.v_asset_allocations as
select user_id, id, data ->> 'assetId' as asset_id, data ->> 'projectId' as project_id,
       data ->> 'location' as location, data ->> 'assignedTo' as assigned_to,
       data ->> 'issueDate' as allocation_date, data ->> 'expectedReturn' as expected_return,
       data ->> 'actualReturn' as actual_return, data ->> 'status' as approval_status,
       updated_at
from public.asset_allocations;

create or replace view public.v_asset_maintenance as
select user_id, id, data ->> 'assetId' as asset_id, data ->> 'type' as maintenance_type,
       data ->> 'dueDate' as due_date, data ->> 'workOrder' as work_order,
       data ->> 'provider' as service_provider, nullif(data ->> 'cost','')::numeric as cost,
       data ->> 'status' as status, updated_at
from public.asset_maintenance;

-- ---------------------------------------------------------------------
-- Scalar / object workspace settings (automations map, active project).
-- One row per user.
-- ---------------------------------------------------------------------
create table if not exists public.app_settings (
  user_id        uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  automations    jsonb not null default '{}'::jsonb,
  active_project text,
  updated_at     timestamptz not null default now()
);

alter table public.app_settings enable row level security;

drop policy if exists "owner all" on public.app_settings;
create policy "owner all" on public.app_settings
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop trigger if exists set_updated_at on public.app_settings;
create trigger set_updated_at before update on public.app_settings
  for each row execute function public.touch_updated_at();
