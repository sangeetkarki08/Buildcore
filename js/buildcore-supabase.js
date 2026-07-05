/* =====================================================================
 *  BuildCore — Supabase data layer
 *
 *  Bridges the app's in-memory `State` object to Postgres via Supabase.
 *  - Real e-mail/password auth (replaces the demo role login)
 *  - Per-user, RLS-isolated workspace
 *  - Whole-collection "replace" sync (simple + correct for one tenant)
 *  - localStorage stays as an offline cache (handled in buildcore.html)
 *
 *  Configuration is read from `window.BUILDCORE_SUPABASE`
 *  (see js/supabase-config.example.js). If it is absent or still has
 *  placeholder values, the layer disables itself and the app keeps
 *  running exactly as before (offline / localStorage only).
 *
 *  Everything is exposed on `window.BC`.
 * ===================================================================== */
(function () {
  'use strict';

  var cfg = window.BUILDCORE_SUPABASE || {};
  var configured =
    !!cfg.url &&
    !!cfg.anonKey &&
    cfg.url.indexOf('YOUR-PROJECT') === -1 &&
    cfg.anonKey.indexOf('YOUR-ANON-KEY') === -1;

  var sb = null;
  if (configured && window.supabase && window.supabase.createClient) {
    sb = window.supabase.createClient(cfg.url, cfg.anonKey, {
      auth: { persistSession: true, autoRefreshToken: true }
    });
  }

  // State-key -> { table, id }. `id` is the field on each object used as
  // the row primary key; null means "no natural id, generate one".
  var MAP = {
    projects: { table: 'projects',          id: 'id'   },
    tenders:  { table: 'tenders',           id: 'id'   },
    materials:{ table: 'materials',         id: 'code' },
    ncrs:     { table: 'ncrs',              id: 'id'   },
    raBills:  { table: 'ra_bills',          id: 'id'   },
    pos:      { table: 'purchase_orders',   id: 'id'   },
    vendors:  { table: 'vendors',           id: 'id'   },
    vendorDocuments: { table: 'vendor_documents', id: 'id' },
    vendorApprovals: { table: 'vendor_approvals', id: 'id' },
    vendorEvaluations: { table: 'vendor_evaluations', id: 'id' },
    vendorRFQs: { table: 'vendor_rfqs', id: 'id' },
    vendorContracts: { table: 'vendor_contracts', id: 'id' },
    vendorPayments: { table: 'vendor_payments', id: 'id' },
    vendorBlacklist: { table: 'vendor_blacklist', id: 'id' },
    coaAccounts:         { table: 'coa_accounts',          id: 'id' },
    fiscalYears:         { table: 'fiscal_years',          id: 'id' },
    contractorMaster:    { table: 'contractor_master',     id: 'id' },
    contractorDocuments: { table: 'contractor_documents',  id: 'id' },
    ledgerEntries:       { table: 'ledger_entries',        id: 'id' },
    equipMonthlyPerformance: { table: 'equip_monthly_performance', id: 'id' },
    dprs:     { table: 'dprs',              id: 'id'   },
    vos:      { table: 'variation_orders',  id: 'id'   },
    risks:    { table: 'risks',             id: 'id'   },
    photos:   { table: 'photos',            id: 'id'   },
    manpowerMaster: { table: 'manpower_master', id: 'id' },
    manpowerDeployment: { table: 'manpower_deployment', id: 'id' },
    manpowerAttendance: { table: 'manpower_attendance', id: 'id' },
    manpowerPayroll: { table: 'manpower_payroll', id: 'id' },
    manpowerLeave: { table: 'manpower_leave', id: 'id' },
    manpowerDocuments: { table: 'manpower_documents', id: 'id' },
    manpowerTraining: { table: 'manpower_training', id: 'id' },
    manpowerSafety: { table: 'manpower_safety', id: 'id' },
    subcontractorManpower: { table: 'subcontractor_manpower', id: 'id' },
    manpowerAdvanceDeduction: { table: 'manpower_advance_deduction', id: 'id' },
    manpowerTransferHistory: { table: 'manpower_transfer_history', id: 'id' },
    assets:   { table: 'assets',            id: 'id'   },
    assetCategories:   { table: 'asset_categories',   id: 'id' },
    assetLocations:    { table: 'asset_locations',    id: 'id' },
    assetAllocations:  { table: 'asset_allocations',  id: 'id' },
    assetTransfers:    { table: 'asset_transfers',    id: 'id' },
    assetMaintenance:  { table: 'asset_maintenance',  id: 'id' },
    assetBreakdowns:   { table: 'asset_breakdowns',   id: 'id' },
    assetFuelLogs:     { table: 'asset_fuel_logs',    id: 'id' },
    assetInspections:  { table: 'asset_inspections',  id: 'id' },
    assetDocuments:    { table: 'asset_documents',    id: 'id' },
    assetDisposals:    { table: 'asset_disposals',    id: 'id' },
    assetNotifications:{ table: 'asset_notifications',id: 'id' },
    bccBoq:       { table: 'budget_boq_items',       id: 'id' },
    bccResources: { table: 'budget_resources',       id: 'id' },
    bccRecipes:   { table: 'budget_resource_recipes',id: 'id' },
    bccActuals:   { table: 'budget_cost_ledger',     id: 'id' },
    bccPackages:  { table: 'budget_b2b_packages',    id: 'id' },
    bccContracts: { table: 'budget_contracts',       id: 'id' },
    bccOverheads: { table: 'budget_overheads',       id: 'id' },
    bccMilestones:{ table: 'budget_milestones',      id: 'id' },
    bccApprovals: { table: 'budget_approvals',       id: 'id' },
    aiDocAnswerHistory:{ table: 'ai_doc_answer_history', id: 'id' },
    boq:      { table: 'boq_items',         id: 'id'   },
    labReports: { table: 'lab_reports', id: 'id' },
    labTestTypes: { table: 'lab_test_types', id: 'id' },
    clientSubmissions: { table: 'client_submissions', id: 'id' },
    documents: { table: 'documents', id: 'id' },
    projectPackages: { table: 'project_packages', id: 'id' },
    projectCalendars: { table: 'project_calendars', id: 'id' },
    wbsActivities: { table: 'wbs_activities', id: 'id' },
    projectLocations: { table: 'project_locations', id: 'id' },
    projectMilestones: { table: 'project_milestones', id: 'id' },
    approvalHistory: { table: 'approval_history', id: 'id' },
    measurements: { table: 'measurements', id: null },
    costRecords: { table: 'cost_records', id: null },
    items: { table: 'inventory_items', id: 'id' },
    stockMovements: { table: 'stock_movements', id: 'id' },
    subcontractors: { table: 'subcontractors', id: 'id' },
    toolIssues: { table: 'tool_issues', id: 'id' },
    sites: { table: 'stock_sites', id: 'id' },
    equipment: { table: 'equipment', id: 'id' },
    equipLogs: { table: 'equipment_logs', id: 'id' },
    operators: { table: 'equipment_operators', id: 'id' },
    maintenance: { table: 'equipment_maintenance', id: 'id' },
    eqSites: { table: 'equipment_sites', id: 'id' },
    crusherRecords: { table: 'crusher_records', id: 'id' },
    batchingRecords: { table: 'batching_records', id: 'id' },
    events: { table: 'events', id: 'id' },
    todos: { table: 'todos', id: 'id' },
    projectSites: { table: 'project_work_sites', id: 'id' },
    estItems: { table: 'estimation_items', id: 'id' },
    contracts: { table: 'contracts', id: 'id' },
    expenses: { table: 'expenses', id: 'id' },
    revenues: { table: 'revenues', id: 'id' },
    universalCodingSchema: { table: 'universal_coding_schema', id: 'id' },
    compatibilityMappings: { table: 'compatibility_mappings', id: 'id' },
    migrationLogs: { table: 'migration_logs', id: 'id' },
    approvalMatrix: { table: 'approval_matrix', id: null },
    periodLocks: { table: 'period_locks', id: 'id' },
    exportLogs: { table: 'export_logs', id: null },
    activity: { table: 'activity',          id: null   },
    audit:    { table: 'audit_log',         id: 'hash' }
  };

  function log() {
    try { console.log.apply(console, ['[BuildCore·Supabase]'].concat([].slice.call(arguments))); }
    catch (e) {}
  }

  // ---- auth ----------------------------------------------------------
  var auth = {
    async currentUser() {
      if (!sb) return null;
      var r = await sb.auth.getUser();
      return (r && r.data && r.data.user) || null;
    },
    async signIn(email, password) {
      if (!sb) throw new Error('Supabase not configured');
      var r = await sb.auth.signInWithPassword({ email: email, password: password });
      if (r.error) throw r.error;
      return r.data.user;
    },
    async signUp(email, password, meta) {
      if (!sb) throw new Error('Supabase not configured');
      var r = await sb.auth.signUp({
        email: email,
        password: password,
        options: { data: meta || {} }
      });
      if (r.error) throw r.error;
      return r.data.user;
    },
    async signOut() {
      if (sb) { try { await sb.auth.signOut(); } catch (e) {} }
    },
    async profile() {
      if (!sb) return null;
      var u = await this.currentUser();
      if (!u) return null;
      var r = await sb.from('profiles').select('*').eq('id', u.id).maybeSingle();
      return (r && r.data) || null;
    }
  };

  // ---- helpers -------------------------------------------------------
  function chunk(arr, n) {
    var out = [];
    for (var i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n));
    return out;
  }

  function genId() {
    try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (e) {}
    return 'r-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
  }

  function toRows(list, idField) {
    return (list || []).map(function (obj, i) {
      var o = obj;
      // activity carries a Date in memory — serialize to ISO for JSONB
      if (o && o.t instanceof Date) o = Object.assign({}, o, { t: o.t.toISOString() });
      var id = idField && o && o[idField] != null ? String(o[idField]) : genId();
      return { id: id, data: o };
    });
  }

  function rehydrate(stateKey, rows) {
    var list = rows.map(function (r) { return r.data; });
    if (stateKey === 'activity') {
      list = list.map(function (a) { return Object.assign({}, a, { t: new Date(a.t) }); });
    }
    return list;
  }

  // ---- load (Supabase -> State) -------------------------------------
  // Returns true if the remote workspace had any rows.
  async function pullInto(State) {
    if (!sb) return false;
    var hadData = false;

    await Promise.all(Object.keys(MAP).map(async function (key) {
      var m = MAP[key];
      try {
        var r = await sb.from(m.table).select('id,data');
        if (r.error) { log('load', m.table, 'failed:', r.error.message); return; }
        if (r.data && r.data.length) {
          State[key] = rehydrate(key, r.data);
          hadData = true;
        }
      } catch (e) { log('load', m.table, 'error', e && e.message); }
    }));

    try {
      var s = await sb.from('app_settings').select('automations,active_project,feature_flags,dpr_templates,tax_config').maybeSingle();
      if (s && s.data) {
        if (s.data.automations && Object.keys(s.data.automations).length) {
          State.automations = s.data.automations;
        }
        if (s.data.active_project) State.activeProject = s.data.active_project;
        if (s.data.feature_flags && Object.keys(s.data.feature_flags).length) {
          State.featureFlags = s.data.feature_flags;
        }
        if (s.data.dpr_templates && Object.keys(s.data.dpr_templates).length) {
          State.dprTemplates = s.data.dpr_templates;
        }
        if (s.data.tax_config && Object.keys(s.data.tax_config).length) {
          State.taxConfig = s.data.tax_config;
        }
        hadData = true;
      }
    } catch (e) { log('load app_settings error', e && e.message); }

    return hadData;
  }

  // ---- save (State -> Supabase) -------------------------------------
  async function syncCollection(key, State) {
    if (!sb) return;
    var m = MAP[key];
    var rows = toRows(State[key], m.id);
    try {
      // RLS scopes deletes to the caller's rows only.
      var del = await sb.from(m.table).delete().not('id', 'is', null);
      if (del.error) { log('clear', m.table, del.error.message); return; }
      var parts = chunk(rows, 500);
      for (var i = 0; i < parts.length; i++) {
        var ins = await sb.from(m.table).insert(parts[i]);
        if (ins.error) { log('insert', m.table, ins.error.message); return; }
      }
    } catch (e) { log('sync', m.table, 'error', e && e.message); }
  }

  async function syncSettings(State) {
    if (!sb) return;
    var u = await auth.currentUser();
    if (!u) return;
    try {
      var r = await sb.from('app_settings').upsert({
        user_id: u.id,
        automations: State.automations || {},
        active_project: State.activeProject || null,
        feature_flags: State.featureFlags || {},
        dpr_templates: State.dprTemplates || {},
        tax_config: State.taxConfig || {},
        updated_at: new Date().toISOString()
      }, { onConflict: 'user_id' });
      if (r.error) log('settings upsert', r.error.message);
    } catch (e) { log('settings error', e && e.message); }
  }

  var _pushTimer = null;
  var _pushing = false;
  function push(State) {
    if (!sb) return;
    if (_pushTimer) clearTimeout(_pushTimer);
    _pushTimer = setTimeout(async function () {
      if (_pushing) return;
      _pushing = true;
      try {
        var u = await auth.currentUser();
        if (!u) return;                       // not signed in -> skip remote
        for (var key in MAP) { if (MAP.hasOwnProperty(key)) await syncCollection(key, State); }
        await syncSettings(State);
        log('synced to Supabase');
      } finally { _pushing = false; }
    }, 900);
  }

  // Force a full, awaited push (used right after first sign-in to upload
  // the local seed when the remote workspace is still empty).
  async function pushNow(State) {
    if (!sb) return;
    var u = await auth.currentUser();
    if (!u) return;
    for (var key in MAP) { if (MAP.hasOwnProperty(key)) await syncCollection(key, State); }
    await syncSettings(State);
    log('initial seed uploaded');
  }

  async function firstSyncIfEmpty(State) {
    if (!sb) return;
    try {
      var r = await sb.from('projects').select('id', { count: 'exact', head: true });
      var empty = !r.error && (r.count === 0 || r.count == null);
      if (empty) await pushNow(State);
    } catch (e) { log('firstSync error', e && e.message); }
  }

  window.BC = {
    enabled: !!sb,
    configured: configured,
    client: sb,
    auth: auth,
    pullInto: pullInto,
    push: push,
    pushNow: pushNow,
    firstSyncIfEmpty: firstSyncIfEmpty
  };

  log(sb ? 'client ready' : 'not configured — running in offline (localStorage) mode');
})();
