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
    'purchase_orders', 'vendors', 'vendor_documents',
    'vendor_approvals', 'vendor_evaluations', 'vendor_rfqs',
    'vendor_contracts', 'vendor_payments', 'vendor_blacklist',
    'dprs', 'variation_orders', 'risks',
    'photos', 'manpower_master', 'manpower_deployment',
    'manpower_attendance', 'manpower_payroll', 'manpower_leave',
    'manpower_documents', 'manpower_training', 'manpower_safety',
    'subcontractor_manpower', 'manpower_advance_deduction',
    'manpower_transfer_history', 'assets', 'asset_categories', 'asset_locations',
    'asset_allocations', 'asset_transfers', 'asset_maintenance',
    'asset_breakdowns', 'asset_fuel_logs', 'asset_inspections',
    'asset_documents', 'asset_disposals', 'asset_notifications',
    'budget_boq_items', 'budget_resources', 'budget_resource_recipes',
    'budget_cost_ledger', 'budget_b2b_packages', 'budget_contracts',
    'budget_overheads', 'budget_milestones', 'budget_approvals',
    'ai_doc_answer_history', 'activity', 'audit_log'
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
-- Asset Management normalized relational schema.
-- These tables provide a scalable SQL structure for production asset
-- operations while the JSONB collection tables above keep the current
-- single-page app sync backward-compatible.
-- ---------------------------------------------------------------------
create table if not exists public.asset_categories_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  name text not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (user_id, id),
  unique (user_id, name)
);

create table if not exists public.asset_locations_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  name text not null,
  location_type text,
  project_id text,
  parent_location_id text,
  created_at timestamptz not null default now(),
  primary key (user_id, id)
);

create table if not exists public.assets_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  qr_code text,
  barcode text,
  asset_name text not null,
  category_id text,
  asset_type text,
  brand text,
  model text,
  serial_number text,
  registration_number text,
  purchase_date date,
  purchase_cost numeric(14,2) default 0,
  supplier_name text,
  warranty_until date,
  ownership_type text check (ownership_type in ('owned','rented','leased','subcontractor-owned')),
  current_condition text,
  current_status text check (current_status in ('available','allocated','under maintenance','breakdown','lost','disposed')),
  current_location_id text,
  assigned_project_id text,
  assigned_department text,
  assigned_user_id uuid references public.profiles (id),
  assigned_user_name text,
  operator_name text,
  asset_photo text,
  document_summary text,
  depreciation_method text,
  depreciation_rate numeric(6,2) default 0,
  resale_value numeric(14,2) default 0,
  created_by uuid references public.profiles (id),
  updated_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, id),
  foreign key (user_id, category_id) references public.asset_categories_rel (user_id, id),
  foreign key (user_id, current_location_id) references public.asset_locations_rel (user_id, id)
);

create table if not exists public.asset_allocations_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  project_id text,
  site_location text,
  work_package text,
  department text,
  store text,
  workshop text,
  engineer text,
  operator text,
  subcontractor text,
  allocation_date date,
  expected_return_date date,
  actual_return_date date,
  handover_condition text,
  receiving_condition text,
  remarks text,
  approval_status text,
  approved_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_transfers_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  from_location_id text,
  to_location_id text,
  request_date date,
  approved_by uuid references public.profiles (id),
  dispatch_date date,
  received_date date,
  condition_before text,
  condition_after text,
  photos text,
  supporting_documents text,
  status text,
  remarks text,
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_maintenance_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  maintenance_type text,
  schedule_basis text,
  service_interval_value numeric(12,2),
  service_interval_unit text,
  request_date date,
  approved_by uuid references public.profiles (id),
  work_order_no text,
  spare_parts_used text,
  labour_used text,
  maintenance_cost numeric(14,2) default 0,
  service_provider text,
  workshop_details text,
  completion_report text,
  due_date date,
  next_due_date date,
  status text,
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_breakdowns_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  reported_by text,
  reported_at timestamptz,
  location text,
  problem_description text,
  asset_condition text,
  urgency_level text,
  assigned_mechanic_team text,
  repair_cost numeric(14,2) default 0,
  downtime_hours numeric(10,2) default 0,
  cause_of_breakdown text,
  corrective_action text,
  repaired_date date,
  reuse_approved_by uuid references public.profiles (id),
  status text,
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_fuel_logs_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  log_date date,
  running_hour numeric(10,2),
  kilometer_reading numeric(12,2),
  fuel_issued numeric(12,2),
  fuel_consumption numeric(12,2),
  operator_name text,
  work_location text,
  work_description text,
  idle_hour numeric(10,2),
  productive_hour numeric(10,2),
  fuel_efficiency text,
  abnormal_consumption boolean default false,
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_inspections_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  inspection_type text,
  inspection_date date,
  checklist jsonb default '{}'::jsonb,
  defect_report text,
  photo_evidence text,
  inspector_signature text,
  approval_status text,
  approved_by uuid references public.profiles (id),
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_documents_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  document_type text,
  title text,
  file_name text,
  file_url text,
  issue_date date,
  expiry_date date,
  status text,
  uploaded_by uuid references public.profiles (id),
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_depreciation_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  book_value numeric(14,2),
  annual_depreciation numeric(14,2),
  accumulated_depreciation numeric(14,2),
  repair_maintenance_cost numeric(14,2),
  total_ownership_cost numeric(14,2),
  disposal_value numeric(14,2),
  as_of_date date,
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_disposals_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text not null,
  disposal_request_date date,
  reason text,
  current_condition text,
  approval_status text,
  approved_by uuid references public.profiles (id),
  valuation numeric(14,2),
  sale_scrap_value numeric(14,2),
  disposal_date date,
  buyer_vendor_details text,
  supporting_documents text,
  final_status text,
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_notifications_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  asset_id text,
  notification_type text,
  title text,
  due_date date,
  status text default 'Open',
  created_at timestamptz not null default now(),
  primary key (user_id, id),
  foreign key (user_id, asset_id) references public.assets_rel (user_id, id) on delete cascade
);

create table if not exists public.asset_audit_logs_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id bigserial,
  asset_id text,
  action text,
  actor_id uuid references public.profiles (id),
  old_value jsonb,
  new_value jsonb,
  remarks text,
  created_at timestamptz not null default now(),
  primary key (user_id, id)
);

-- ---------------------------------------------------------------------
-- Budget, cost control, back-to-back contract, overhead and milestone
-- relational schema.
-- ---------------------------------------------------------------------
create table if not exists public.budget_boq_items_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  project_id text,
  location text,
  work_package text,
  activity text,
  boq_code text,
  description text,
  unit text,
  quantity numeric(14,3),
  client_rate numeric(14,2),
  client_amount numeric(16,2),
  execution_mode text,
  internal_budget_rate numeric(14,2),
  actual_cost_rate numeric(14,2),
  executed_quantity numeric(14,3),
  responsible_party text,
  approval_status text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, id)
);

create table if not exists public.budget_resources_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  category text,
  resource_name text,
  unit text,
  budget_rate numeric(14,2),
  approved_rate numeric(14,2),
  current_market_rate numeric(14,2),
  actual_purchase_rate numeric(14,2),
  subcontract_rate numeric(14,2),
  revised_rate numeric(14,2),
  revision_history jsonb default '[]'::jsonb,
  primary key (user_id, id)
);

create table if not exists public.budget_resource_recipes_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  boq_item_id text not null,
  resource_id text,
  resource_category text,
  coefficient_per_unit numeric(14,6),
  resource_rate numeric(14,2),
  wastage_pct numeric(6,2),
  productivity text,
  equipment_hours numeric(12,3),
  labour_mandays numeric(12,3),
  material_consumption numeric(14,3),
  fuel_consumption numeric(14,3),
  fixed_asset_cost numeric(14,2),
  overhead_allocation numeric(14,2),
  profit_margin_pct numeric(6,2),
  contingency_pct numeric(6,2),
  cost_per_unit numeric(14,2),
  primary key (user_id, id),
  foreign key (user_id, boq_item_id) references public.budget_boq_items_rel (user_id, id) on delete cascade
);

create table if not exists public.budget_cost_ledger_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  project_id text,
  location text,
  activity text,
  boq_item_id text,
  resource_type text,
  cost_head text,
  work_package text,
  subcontractor text,
  vendor text,
  ledger_date date,
  quantity numeric(14,3),
  cost_amount numeric(16,2),
  approval_status text,
  source_module text,
  primary key (user_id, id)
);

create table if not exists public.budget_b2b_packages_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  scenario text,
  package_name text,
  linked_boq_items text[],
  client_contract_value numeric(16,2),
  subcontract_value numeric(16,2),
  client_certified_amount numeric(16,2),
  subcontractor_certified_amount numeric(16,2),
  retention_pct numeric(6,2),
  advance_recovery_pct numeric(6,2),
  vat_pct numeric(6,2),
  tds_pct numeric(6,2),
  payment_terms text,
  performance_guarantee text,
  insurance text,
  ld_clause text,
  variation_clause text,
  claim_clause text,
  risk_ownership text,
  overhead_cost numeric(16,2),
  finance_cost numeric(16,2),
  final_projected_margin_pct numeric(8,2),
  status text,
  primary key (user_id, id)
);

create table if not exists public.budget_contracts_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  contract_mode text,
  title text,
  supplier_vendor text,
  contract_amount numeric(16,2),
  payment_milestones jsonb default '[]'::jsonb,
  retention_pct numeric(6,2),
  advance_pct numeric(6,2),
  deductions numeric(16,2),
  variation_amount numeric(16,2),
  claim_amount numeric(16,2),
  final_payable_amount numeric(16,2),
  status text,
  primary key (user_id, id)
);

create table if not exists public.budget_overheads_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  overhead_type text,
  overhead_head text,
  monthly_budget numeric(16,2),
  actual_monthly_cost numeric(16,2),
  forecast_months numeric(8,2),
  delay_months numeric(8,2),
  allocation_method text,
  delay_cost_impact numeric(16,2),
  approval_status text,
  primary key (user_id, id)
);

create table if not exists public.budget_milestones_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  milestone_title text,
  milestone_category text,
  project_id text,
  location text,
  boq_item_id text,
  work_package text,
  schedule_activity text,
  subcontractor_vendor text,
  planned_start date,
  planned_finish date,
  revised_start date,
  revised_finish date,
  actual_start date,
  actual_finish date,
  planned_progress_pct numeric(6,2),
  actual_progress_pct numeric(6,2),
  weightage_pct numeric(6,2),
  contractual_importance text,
  payment_linkage text,
  delay_status text,
  delay_days numeric(8,2),
  responsible_party text,
  required_documents text,
  approval_status text,
  remarks text,
  risk_level text,
  cost_impact numeric(16,2),
  overhead_impact numeric(16,2),
  ld_impact numeric(16,2),
  client_billing_impact numeric(16,2),
  subcontractor_payment_impact numeric(16,2),
  primary key (user_id, id)
);

create table if not exists public.budget_approvals_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  approval_type text,
  reference_id text,
  owner text,
  approval_status text,
  history text,
  old_value jsonb,
  new_value jsonb,
  created_at timestamptz not null default now(),
  primary key (user_id, id)
);

create table if not exists public.ai_doc_answer_history_rel (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  project_id text,
  question text,
  answer text,
  source_mode text,
  source_docs jsonb,
  document_id text,
  answer_status text,
  asked_by text,
  asked_at timestamptz,
  verified_by text,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, id)
);

do $$
declare tbl text;
begin
  foreach tbl in array array[
    'asset_categories_rel','asset_locations_rel','assets_rel','asset_allocations_rel',
    'asset_transfers_rel','asset_maintenance_rel','asset_breakdowns_rel','asset_fuel_logs_rel',
    'asset_inspections_rel','asset_documents_rel','asset_depreciation_rel','asset_disposals_rel',
    'asset_notifications_rel','asset_audit_logs_rel',
    'budget_boq_items_rel','budget_resources_rel','budget_resource_recipes_rel',
    'budget_cost_ledger_rel','budget_b2b_packages_rel','budget_contracts_rel',
    'budget_overheads_rel','budget_milestones_rel','budget_approvals_rel',
    'ai_doc_answer_history_rel'
  ] loop
    execute format('alter table public.%I enable row level security', tbl);
    execute format('drop policy if exists "owner all" on public.%I', tbl);
    execute format('create policy "owner all" on public.%I for all using (auth.uid() = user_id) with check (auth.uid() = user_id)', tbl);
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
