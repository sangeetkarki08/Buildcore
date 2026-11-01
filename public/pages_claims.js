/* BuildCore 2.34 — Claims register.
   Ported from the Claims Register tool: for the project's contract (FIDIC 1999/2017, MDB, PPMO, custom) it keeps the
   Particular Conditions periods and time bars and works out each claim event's timeline: notice, detailed claim,
   determination, dissatisfaction, board, arbitration, with due dates, time-bar risk, strength, evidence, records,
   quantum, letters, payments against the contract clock, start-up deadlines, tender review and negotiation.
   Claim events are BuildCore events; letters go to the Correspondence register; bonds come from Bonds, guarantees &
   insurance; IPC dates come from billing. The library (books, clauses, periods) is in pages_crlib.js. */
"use strict";
(function () {
  const L = window.CRLIB;
  if (!L) return;
  const { ENT, CATS, COMMON_EV, REC_TYPES, BOOKS, BOOK_GROUPS, PROC, RV, RV_GROUPS, GOLDEN, ROUTE, NEG_KIND, NEG_ST, SU, SU_PRACTICE,
          PPA_LAW, SOURCES, DESIGN, EPC, bookLabel, tpl, famOf, pick } = L;

  /* ───────── helpers (as in the Claims Register) ───────── */
  const pad = (n) => String(n).padStart(2, "0");
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const isISO = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || "");
  const toUTC = (iso) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d); };
  const addDays = (iso, n) => { if (!isISO(iso)) return null; const d = new Date(toUTC(iso) + n * 864e5); return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`; };
  const diff = (a, b) => Math.round((toUTC(a) - toUTC(b)) / 864e5);
  const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const fmt = (iso) => isISO(iso) ? cellValue({ k: "date" }, { date: iso }) : "—";
  const num = (v) => (v === "" || v == null || isNaN(+v)) ? null : +v;
  const money = (n, cur) => (n == null || isNaN(n)) ? "—" : `${cur || ""} ${Math.round(n).toLocaleString((cur === "NPR" || cur === "INR" || !cur) ? "en-IN" : "en-US")}`.trim();
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
  const clone = (o) => JSON.parse(JSON.stringify(o));

  /* ───────── contract logic (same rules as the engine) ───────── */
  const bookOf = (p) => BOOKS[p && p.book] || BOOKS.custom;
  function periodsOf(p) { const out = {}; for (const x of bookOf(p).periods) { const o = p && p.po && p.po[x.k]; out[x.k] = (o === 0 || (o != null && o !== "")) ? +o : x.d; } return out; }
  function barOf(p, k) { const x = bookOf(p).periods.find((y) => y.k === k); const o = p && p.bo && p.bo[k]; return o == null ? !!(x && x.bar) : !!o; }
  function clausesOf(p) {
    const b = bookOf(p); const edits = p.ce || {};
    return [...b.clauses.map((c) => Object.assign({}, c, edits[c.r] || {}, { base: true, key: c.r })), ...(p.cc || []).map((c) => Object.assign({}, c, { key: "cc:" + c.id, custom: true, v: 1 }))];
  }
  const activeClauses = (p) => clausesOf(p).filter((c) => !c.off);
  const clauseByRef = (p, r) => clausesOf(p).find((c) => c.r === r || c.key === r);
  const eotGranted = (evs) => evs.reduce((t, e) => t + (+e.eotGranted || 0), 0);
  const originalCompletion = (p) => (isISO(p.commencement) && p.tfcDays) ? addDays(p.commencement, +p.tfcDays) : null;
  const currentCompletion = (p, evs) => { const o = originalCompletion(p); return o ? addDays(o, eotGranted(evs)) : null; };
  const routeOf = (p) => p.route || ((famOf(p.book) === "ppmo" || p.book === "mdb10" || p.ppa) ? "public" : "private");
  const isClosed = (ev) => ev.outcome === "agreed" || ev.outcome === "withdrawn";

  function rvItems(p) { const f = famOf(p.book); return RV.filter((it) => (it.ref[f] != null || (it.ppaAll && p.ppa)) && (!it.when || it.when(p.book)) && !(it.not || []).includes(p.book)); }
  function rvAuto(p, it) {
    const r = (p.rv || {})[it.id] || {};
    if (r.v == null || r.v === "") return "";
    if (it.type === "num") return it.rule ? it.rule(+r.v, famOf(p.book)) : "";
    const o = it.opts.find((x) => x[0] === r.v); return o ? o[2] : "";
  }
  const rvStatus = (p, it) => ((p.rv || {})[it.id] || {}).s || rvAuto(p, it);
  function rvCounts(p) { const items = rvItems(p); const c = { total: items.length, ok: 0, watch: 0, risk: 0, na: 0, none: 0 }; for (const it of items) c[rvStatus(p, it) || "none"]++; c.done = c.total - c.none; return c; }
  const rvRef = (p, it) => it.ref[famOf(p.book)] ?? it.ref.ppmo;
  const rvGc = (p, it) => pick(it.gc, famOf(p.book)) || pick(it.gc, "ppmo");
  function rvTenderText(p, it) {
    const r = (p.rv || {})[it.id] || {};
    if (r.pc) return r.pc;
    if (r.v == null || r.v === "") return "";
    if (it.type === "num") return it.unit.startsWith("%") ? `${r.v}${it.unit}` : `${r.v} ${it.unit}`;
    return (it.opts.find((o) => o[0] === r.v) || [])[1] || "";
  }
  function tenderDates(p) {
    const td = p.td || {}; const f = famOf(p.book); const out = [];
    const add = (id, l, d, ref, kind, n) => { if (isISO(d)) out.push({ id, l, d, ref, kind, n }); };
    add("prebid", "Pre-bid meeting", td.prebid, f === "ppmo" ? "PPR r.52" : "ITB", "act");
    add("clarify", "Last day for clarification requests", td.clarify, "ITB / BDS", "act");
    add("deadline", "Bid submission deadline", td.deadline, "Bid notice", "act");
    if (f !== "ppmo" && isISO(td.deadline)) add("base", "Base Date (28 days before the deadline)", addDays(td.deadline, -28), "1.1", "info", "Reference date for change in law and for what was foreseeable.");
    if (isISO(td.deadline) && +td.validity > 0) {
      const ve = addDays(td.deadline, +td.validity);
      add("validity", "Bid validity ends", ve, f === "ppmo" ? "PPA s.20" : "ITB", "act");
      add("bsec", "Bid security must stay valid until", addDays(ve, f === "ppmo" ? 30 : 28), f === "ppmo" ? "PPR r.53(2)" : "ITB", "info");
    }
    if (f === "ppmo" && isISO(td.loi)) add("complaint", "Complaint window closes", addDays(td.loi, 7), "PPA s.27, s.47", "info");
    return out.sort((a, b) => a.d < b.d ? -1 : 1);
  }
  function suItems(p) { const key = p.book === "ppmo_sq" ? "ppmo_sq" : famOf(p.book); return (SU[key] || SU.f17).filter((s) => (!s.design || DESIGN.includes(p.book)) && (!s.only || s.only.includes(p.book))); }
  const endOfNextMonth = (iso) => { const [y, m] = iso.split("-").map(Number); return new Date(Date.UTC(y, m + 1, 0)).toISOString().slice(0, 10); };
  function suBase(p, b) {
    switch (b) {
      case "loa": return p.loa; case "commence": return p.commencement; case "n81": return p.n81 || p.commencement;
      case "accessDate": return p.accessDate; case "dabDate": return p.dabDate; case "advDate": return p.advDate;
      case "loi": return (p.td || {}).loi; case "month1": return isISO(p.commencement) ? endOfNextMonth(p.commencement) : null;
    }
    return null;
  }
  function suSteps(p) {
    const today = todayISO(); const b = bookOf(p);
    return suItems(p).map((s) => {
      const base = s.base ? suBase(p, s.base) : null;
      const due = isISO(base) ? addDays(base, s.d || 0) : null;
      const done = (p.su || {})[s.id] || "";
      let st, daysLeft = null;
      if (s.kind === "info") st = due && due < today ? "done" : "info";
      else if (done) st = (due && done > due && s.who === "c") ? "late" : "done";
      else if (!s.base) st = "open";
      else if (!due) st = "wait";
      else { daysLeft = diff(due, today); st = daysLeft < 0 ? "over" : daysLeft <= 7 ? "soon" : "up"; }
      return Object.assign({}, s, { label: tpl(s.l, b), due, done, st, daysLeft });
    });
  }
  function buildSteps(p, ev, evs) {
    const b = bookOf(p), P = periodsOf(p), proc = PROC[b.proc] || PROC.p99, today = todayISO();
    const vals = { aware: ev.aware || ev.occurred, endEffects: ev.endEffects, notice: ev.notice, detailed: ev.detailed, final: ev.final, response: ev.response, nod1: ev.nod1, referral: ev.referral, boardDecision: ev.boardDecision, nod2: ev.nod2, arbitration: ev.arbitration, fmNotice: ev.fmNotice };
    const closed = isClosed(ev);
    let disputeActive = !!ev.dispute || (!!ev.response && !!ev.outcome && !closed);
    const dueById = {}, out = [];
    for (const s of proc) {
      if (s.cont && !ev.continuing) continue;
      if (s.onlyCat && ev.cat !== s.onlyCat) continue;
      if (s.k && s.k.some((k) => P[k] == null)) continue;
      let baseDate = vals[s.base], deemed = false;
      if (!baseDate && s.base === "response") {
        const rs = proc.find((x) => x.id === "response");
        if (rs && rs.deem && dueById.response && dueById.response < today && !closed) { baseDate = dueById.response; deemed = true; disputeActive = true; }
      }
      let due = null, capped = false;
      if (baseDate && s.k) due = addDays(baseDate, s.k.reduce((a, k) => a + (P[k] || 0), 0));
      if (s.cap) { const comp = currentCompletion(p, evs || st.evs); if (comp) { const c = addDays(comp, -(P[s.cap] || 0)); if (!due || c < due) { if (due || vals.aware) { due = due ? (c < due ? c : due) : c; capped = due === c; } } } }
      dueById[s.id] = due;
      if (s.onlyIfLate) { if (!(ev.notice && dueById.notice && ev.notice > dueById.notice)) continue; }
      const done = s.f ? vals[s.f] : null;
      const isBar = s.bar ? barOf(p, s.bar) : false;
      let stt, daysLeft = null;
      if (s.kind === "info") stt = "info";
      else if (s.disp && !disputeActive && !done) stt = "idle";
      else if (done) stt = (due && done > due && s.kind !== "earliest" && s.kind !== "open") ? (isBar ? "barred" : "late") : "done";
      else if (s.kind === "open") stt = "open";
      else if (!due) stt = "wait";
      else if (s.kind === "earliest") { daysLeft = diff(due, today); stt = daysLeft <= 0 ? "open" : "wait"; }
      else { daysLeft = diff(due, today); stt = daysLeft < 0 ? "over" : daysLeft <= 7 ? "soon" : "up"; }
      if (closed && !done && stt !== "info") stt = "idle";
      out.push(Object.assign({}, s, { label: tpl(s.l, b), note: s.nt ? tpl(s.nt, b) : "", due, done, st: stt, daysLeft, bar: isBar, deemed, capped,
        refText: s.k ? s.k.map((k) => (b.periods.find((x) => x.k === k) || {}).r).filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join(", ") : "" }));
    }
    return out;
  }
  const nextStep = (steps) => steps.find((s) => s.f && !s.done && ["over", "soon", "up", "open"].includes(s.st)) || null;
  function eventStatus(ev, b) {
    if (ev.outcome === "agreed") return "Agreed";
    if (ev.outcome === "withdrawn") return "Withdrawn";
    if (ev.arbitration) return "In arbitration";
    if (ev.nod2) return b.fam === "ppmo" ? "Referred to arbitration" : "NOD on decision";
    if (ev.boardDecision) return `${b.board} decided`;
    if (ev.referral) return `With ${b.board}`;
    if (ev.nod1) return "NOD given";
    if (ev.response) return ev.outcome === "rejected" ? "Rejected" : ev.outcome === "partial" ? "Partly agreed" : "Determined";
    if (ev.detailed) return "Claim submitted";
    if (ev.notice) return "Notice given";
    return "Watching";
  }
  const evidenceItems = (ev) => { const cat = CATS[ev.cat]; return [...COMMON_EV, ...(cat ? cat.ev.map((t, i) => [ev.cat + i, t]) : [])]; };
  function strength(p, ev, steps) {
    let s = 0; const gaps = [];
    if ((ev.refs || []).length) s += 15; else gaps.push("Link the event to a contract clause.");
    const n = steps.find((x) => x.id === "notice");
    if (n) {
      if (n.done && n.st === "done") s += 25;
      else if (n.done) gaps.push(n.bar ? "Notice went out late: the claim may be time-barred. Gather proof of earlier notice (letters, minutes, emails)." : "Notice went out late; expect the other side to argue reduced entitlement.");
      else if (n.due && n.daysLeft >= 0) { s += 8; gaps.push(`Give notice by ${fmt(n.due)} (${plural(n.daysLeft, "day")} left).`); }
      else if (n.due) gaps.push(`Notice is ${plural(-n.daysLeft, "day")} overdue. Send it now and look for earlier written notice.`);
      else gaps.push("Enter the date you became aware of the event.");
    }
    const d = steps.find((x) => x.id === "detailed");
    if (d) {
      if (d.done && d.st === "done") s += 15;
      else if (d.done) { s += 5; gaps.push("Detailed claim was late."); }
      else if (d.due && d.daysLeft >= 0) { s += 5; gaps.push(`Send the detailed claim by ${fmt(d.due)}.`); }
      else if (d.due) gaps.push(`Detailed claim is ${plural(-d.daysLeft, "day")} overdue.`);
    }
    const items = evidenceItems(ev); const got = items.filter(([k]) => (ev.evidence || {})[k]).length;
    s += Math.round(30 * got / items.length);
    if (got < items.length) gaps.push(`Evidence checklist: ${got} of ${items.length} items in hand.`);
    if ((ev.records || []).length >= 3) s += 5; else gaps.push("Log at least three contemporaneous records.");
    if ((ev.causation || "").trim().length > 40) s += 5; else gaps.push("Write the cause-and-effect link from event to delay and cost.");
    if (num(ev.eotClaimed) || num(ev.costClaimed)) s += 5; else gaps.push("Put a first figure on the time and cost.");
    s = Math.min(100, s);
    return { score: s, grade: s >= 75 ? "strong" : s >= 50 ? "fair" : "weak", gaps };
  }
  function qcCalc(p, ev) {
    const q = ev.qc || {};
    const d = num(q.days) ?? num(ev.eotClaimed) ?? 0;
    const pd = num(q.plantDays) ?? d;
    const site = (num(q.siteOH) || 0) * d;
    const plant = (num(q.plantDay) || 0) * pd;
    const labour = num(q.labour) || 0, direct = num(q.direct) || 0, other = num(q.other) || 0;
    const C = num(p.price) || 0, P = num(p.tfcDays) || 0;
    const ho = (q.hoMethod && q.hoMethod !== "none" && C && P) ? (num(q.hoPct) || 0) / 100 * (C / P) * d : 0;
    const entP = (ev.refs || []).some((r) => /[Pp]/.test(String((clauseByRef(p, r) || {}).e || "")));
    const profit = entP ? (num(q.profitPct) || 0) / 100 * (direct + other) : 0;
    const base = site + plant + labour + direct + other + ho + profit;
    const fin = (num(q.finRate) || 0) / 100 * base * (num(q.finDays) || 0) / 365;
    return { d, pd, site, plant, labour, direct, other, ho, profit, fin, total: base + fin, entP, C, P };
  }
  function payRows(p, list) {
    const b = bookOf(p), P = periodsOf(p), today = todayISO(), rate = num(p.financeRate) ?? 0;
    return list.map((x) => {
      const certDue = b.pay.certify && isISO(x.statement) && P.certify ? addDays(x.statement, P.certify) : null;
      const payBaseDate = b.pay.payBase === "certified" ? x.certified : x.statement;
      const payDue = isISO(payBaseDate) && P.pay != null ? addDays(payBaseDate, P.pay) : null;
      const termBaseDate = b.pay.termBase === "certified" ? x.certified : payDue;
      const termFrom = isISO(termBaseDate) && P.terminatePay != null ? addDays(termBaseDate, P.terminatePay) : null;
      let stt = "up", stText = "Awaiting certification", daysLate = 0;
      const amt = num(x.certAmount) ?? num(x.amount) ?? 0;
      if (x.paid) { daysLate = payDue ? Math.max(0, diff(x.paid, payDue)) : 0; stt = daysLate ? "late" : "done"; stText = daysLate ? `Paid ${daysLate} days late` : "Paid on time"; }
      else if (payDue && today > payDue) { daysLate = diff(today, payDue); stt = "over"; stText = `Payment ${daysLate} days overdue`; }
      else if (b.pay.certify && !x.certified && certDue && today > certDue) { stt = "cert-over"; stText = `Certificate ${diff(today, certDue)} days late`; }
      else if (payDue) { stt = diff(payDue, today) <= 7 ? "soon" : "up"; stText = `Due ${fmt(payDue)}`; }
      const fin = daysLate && rate ? amt * rate / 100 * daysLate / 365 : 0;
      return Object.assign({}, x, { certDue, payDue, termFrom, st: stt, stText, daysLate, fin });
    });
  }
  const ppaTier = (pct) => pct <= 5 ? "Gazetted 3rd class officer" : pct <= 10 ? "Gazetted 2nd class officer" : pct <= 15 ? "Gazetted 1st class officer" : "Head of department";

  /* letters drafted from the event (the Claims Register's wording) */
  function letterText(kind, p, ev) {
    const b = bookOf(p); const P = periodsOf(p);
    const steps = buildSteps(p, ev, st.evs);
    const due = (id) => (steps.find((s) => s.id === id) || {}).due;
    const refs = (ev.refs || []).map((r) => { const c = clauseByRef(p, r); return `${r}${c ? ` [${c.t}]` : ""}`; });
    const to = `${b.admin}${p.adminName ? ` — ${p.adminName}` : ""}`;
    const head = `To: ${to}\nContract: ${p.contractNo || "[contract no.]"} — ${p.name || ""}\nEmployer: ${p.employer || "[Employer]"}\nDate: ${fmt(todayISO())}\nOur ref.: ${ev.noticeRef || "[ref.]"}\n`;
    const sign = `\nFor and on behalf of ${p.contractor || "[Contractor]"}\n\n______________________\n[Name, designation]`;
    const recs = (ev.records || []).slice().sort((a, c) => (a.date || "") < (c.date || "") ? -1 : 1);
    if (kind === "notice") {
      if (p.book === "ppmo_sq") {
        const cut = due("detailed");
        return `APPLICATION FOR EXTENSION OF TIME\nGCC 6.3\n\n${head}\nSubject: ${ev.title || "[event]"}\n\n1. Cause of delay\n${ev.desc || "[Describe the facts: what, where, when, who instructed.]"}\nWe became aware of it on ${fmt(ev.aware || ev.occurred)}${ev.location ? ` at ${ev.location}` : ""}. It is one of the Employer’s liabilities under the Contract: ${refs.join("; ") || "[clause]"}.\n\n2. Request\nWe apply for an extension of the completion date by ${ev.eotClaimed ?? "[ ]"} days under GCC 6.3${cut ? `. This application is made before the cut-off of ${fmt(cut)}` : ""}.\n\n3. Supporting information\nRevised work schedule, site records and correspondence are attached. We will extend the performance security and insurance to cover the extended period.\n${ev.cat === "variation" ? "\n4. Variation order\nPlease issue a written variation order approved by the authority required under Public Procurement Act 2063 s.54.\n" : ""}\nWe reserve all our rights under the Contract and the Public Procurement Act 2063.\n${sign}`;
      }
      if (b.fam === "ppmo") {
        return `EARLY WARNING AND NOTICE OF COMPENSATION EVENT\n${b.claimRef}\n\n${head}\nSubject: ${ev.title || "[event]"}\n\n1. Event\n${ev.desc || "[Describe the facts: what, where, when, who instructed.]"}\nWe became aware of it on ${fmt(ev.aware || ev.occurred)}${ev.location ? ` at ${ev.location}` : ""}.\n\n2. Contractual basis\nWe consider this a Compensation Event under ${refs.join("; ") || "[GCC 43.1(x)]"} that will increase our cost and/or delay completion. We request an extension of the Intended Completion Date under GCC 27.\n\n3. Next steps\nWe will submit our forecast of the cost and time effect with full supporting information under GCC 43.3 and 27.2${due("detailed") ? ` by ${fmt(due("detailed"))}` : ""}. Please record the conditions with us so the facts are agreed now.\n${ev.cat === "variation" ? "\n4. Variation order\nPlease issue a written variation order approved by the authority required under Public Procurement Act 2063 s.54 before we proceed with the changed work.\n" : ""}\nWe reserve all our rights under the Contract and the Public Procurement Act 2063.\n${sign}`;
      }
      const is17 = b.proc === "p17"; const green = b.proc === "pgreen";
      const subj = is17 ? "NOTICE OF CLAIM\nThis is a Notice under Sub-Clause 1.3 and Sub-Clause 20.2.1 [Notice of Claim]" : green ? "NOTICE OF CLAIM\nUnder Clause 13 of the Conditions of Contract" : `NOTICE OF CLAIM\nSub-Clause ${b.claimRef} [Contractor’s Claims]`;
      return `${subj}\n\n${head}\nSubject: ${ev.title || "[event]"}\n\n1. Event or circumstance\n${ev.desc || "[Describe the facts: what, where, when, who instructed.]"}\nThe Contractor became aware of it on ${fmt(ev.aware || ev.occurred)}${ev.location ? ` at ${ev.location}` : ""}.\n\n2. Entitlement\nThe Contractor considers it is entitled to an extension of the Time for Completion and/or additional payment under ${refs.length ? "Sub-Clause(s) " + refs.join("; ") : "[Sub-Clause(s)]"}${is17 ? ", Sub-Clause 8.5" : b.proc === "p99" ? ", Sub-Clause 8.4" : ""} and ${is17 ? "Sub-Clause 20.2" : green ? "Clause 13" : "Sub-Clause " + b.claimRef}.\n\n3. Records\nThe Contractor is keeping contemporaneous records of this event${is17 ? " under Sub-Clause 20.2.3" : ""} and invites the ${b.admin} to inspect them.\n\n4. Next steps\nA fully detailed claim will follow within ${P.detailed} days of the date of awareness${due("detailed") ? ` (by ${fmt(due("detailed"))})` : ""}${ev.continuing ? ", with interim claims every month while the effect continues" : ""}.\n${ev.cat === "weather" && P.fmNotice ? `\nThis letter is also notice of the event under Sub-Clause ${(b.periods.find((x) => x.k === "fmNotice") || {}).r} within ${P.fmNotice} days.\n` : ""}\nThe Contractor reserves all its rights under the Contract.\n${sign}`;
    }
    if (kind === "claim") {
      const sg = strength(p, ev, steps);
      return `FULLY DETAILED CLAIM — OUTLINE\n${ev.title || "[event]"}\n${p.name || ""} · ${p.contractNo || ""} · ${bookLabel(p.book)}\n\n1. Executive summary\n   Event: ${ev.title || ""}\n   Time claimed: ${ev.eotClaimed ?? "[ ]"} days. Cost claimed: ${money(num(ev.costClaimed), p.currency)}.\n\n2. Contractual entitlement\n${(ev.refs || []).map((r) => { const c = clauseByRef(p, r); return `   ${r} ${(c || {}).t || ""}: ${c ? String(c.e).split("").map((t) => ENT[t] || t).join(", ") : ""}`; }).join("\n") || "   [clauses]"}\n\n3. Notices and compliance with ${b.claimRef}\n   Aware: ${fmt(ev.aware || ev.occurred)}\n   Notice: ${fmt(ev.notice)} ${ev.noticeRef ? `(${ev.noticeRef})` : ""} — due ${fmt(due("notice"))}\n   Detailed claim: due ${fmt(due("detailed"))}\n\n4. Facts and chronology\n${ev.desc ? "   " + ev.desc.replace(/\n/g, "\n   ") : "   [facts]"}\n${recs.map((r) => `   ${fmt(r.date)} — ${r.type || "Record"}: ${r.desc || ""} ${r.ref ? `[${r.ref}]` : ""}`).join("\n")}\n\n5. Causation\n   ${(ev.causation || "[How the event caused delay to critical activities and extra cost]").replace(/\n/g, "\n   ")}\n\n6. Time: delay analysis\n   Method: [time-impact analysis against the accepted baseline programme]\n   Critical path affected: [activities]\n   Concurrent delays considered: [ ]\n   Extension claimed: ${ev.eotClaimed ?? "[ ]"} days\n\n7. Money: quantum\n   Heads: direct labour, plant (working and idle), materials, site overheads for the prolonged period, head-office overheads, financing${(ev.refs || []).some((r) => String((clauseByRef(p, r) || {}).e).includes("P")) ? ", profit" : ""}\n   Basis: actual cost records, cost code [ ]\n   Total: ${money(num(ev.costClaimed), p.currency)}\n\n8. Mitigation\n   ${(ev.mitigation || "[steps taken]").replace(/\n/g, "\n   ")}\n\n9. Appendices — records index\n${recs.length ? recs.map((r, i) => `   A${i + 1}. ${fmt(r.date)} ${r.type || ""} ${r.ref ? `[${r.ref}]` : ""} — ${r.desc || ""}`).join("\n") : "   [No records logged yet]"}\n\nStrength check before sending: ${sg.score}/100.${sg.gaps.length ? "\nGaps:\n" + sg.gaps.map((g) => "   - " + g).join("\n") : ""}`;
    }
    if (kind === "nod") {
      const is17 = b.proc === "p17";
      const which = ev.boardDecision ? `the ${b.board} decision dated ${fmt(ev.boardDecision)}` : `the ${b.admin}’s ${is17 ? "determination" : "response"} dated ${fmt(ev.response)}`;
      const ref = ev.boardDecision ? (is17 ? "Sub-Clause 21.4.4" : "Sub-Clause 20.4") : (is17 ? `Sub-Clause ${b.detRef}.5` : "Sub-Clause 20.4");
      return `NOTICE OF DISSATISFACTION\nThis is a Notice under ${ref}\n\n${head}\nSubject: ${ev.title || "[event]"}\n\nThe Contractor is dissatisfied with ${which} in respect of its claim for ${ev.eotClaimed ?? "[ ]"} days’ extension of time and ${money(num(ev.costClaimed), p.currency)}.\n\nReasons:\n1. [Ground 1]\n2. [Ground 2]\n\nThe Contractor ${ev.boardDecision ? "intends to refer the Dispute to arbitration after the amicable settlement period" : `will refer the Dispute to the ${b.board}${is17 ? " within 42 days of this Notice" : ""}`}.\n\nThe Contractor reserves all its rights.\n${sign}`;
    }
    return `NOTICE OF DISPUTE AND REFERRAL\n${b.board} · GCC 25\n\n${head}\nSubject: ${ev.title || "[event]"}\n\nThe ${b.admin}’s decision dated ${fmt(ev.response)} on this claim was ${ev.outcome === "partial" ? "only partly in our favour" : "not in our favour"}. We consider the decision wrongly taken.\n\nWe propose to meet within the amicable settlement period. If the dispute is not settled, we will refer it to the ${b.board} within ${P.referAdj ?? 30} days of the decision under GCC 25.1, and then to arbitration under the Arbitration Act 2055 if needed.\n\nClaim: ${ev.eotClaimed ?? "[ ]"} days and ${money(num(ev.costClaimed), p.currency)}.\n\nWe reserve all our rights.\n${sign}`;
  }
  function negLetter(p) {
    const b = bookOf(p); const route = routeOf(p); const list = (p.neg || []).filter((n) => n.status !== "withdrawn");
    const head = `To: ${p.employer || "[Employer]"}\n${p.contractNo ? `Bid / contract: ${p.contractNo}\n` : ""}Project: ${p.name || ""}\nConditions: ${bookLabel(p.book)} — ${b.title}\nDate: ${fmt(todayISO())}\n`;
    const stl = (n) => (NEG_ST.find((x) => x[0] === (n.status || "draft")) || NEG_ST[0])[1];
    if (route === "public") return `REQUEST FOR CLARIFICATION OF THE BIDDING DOCUMENTS\n\n${head}\nWe ask for clarification of the following points${isISO((p.td || {}).clarify) ? `, within the period for clarification requests ending ${fmt(p.td.clarify)}` : ""}:\n\n${list.map((n, i) => `${i + 1}. ${n.ref || "[clause]"}\n   ${n.issue || "[issue]"}\n   We request: ${n.ask || "[request]"}`).join("\n\n")}\n\nWe ask that the answers, and any amendment to the bidding documents, be issued to all bidders as an addendum before the bid deadline.\n\nFor and on behalf of ${p.contractor || "[Bidder]"}\n\n______________________\n[Name, designation]`;
    return `SCHEDULE OF PROPOSED AMENDMENTS TO THE PARTICULAR CONDITIONS\n\n${head}\nThe following amendments are proposed for agreement before the Contract Agreement is signed. Agreed items will be written into the Particular Conditions.\n\n${list.map((n, i) => `${i + 1}. Clause ${n.ref || "[ ]"}\n   Tender wording / issue: ${n.issue || "[ ]"}\n   Proposed amendment: ${n.ask || "[ ]"}\n   Status: ${stl(n)}${n.reply ? ` — ${n.reply}` : ""}`).join("\n\n")}\n\nFor and on behalf of ${p.contractor || "[Contractor]"}\n\n______________________\n[Name, designation]`;
  }

  /* ───────── state, saving and small widgets ───────── */
  const st = { pid: null, d: null, p: null, evs: [], tab: "overview", root: null, body: null, ro: true, filter: { q: "", cat: "", st: "open" }, libBook: null, drawer: null };
  async function reload() { st.d = await api("cr.get", { project_id: st.pid }); st.p = st.d.contract; st.evs = st.d.claims; st.ro = !st.d.can_edit; }
  async function saveP() { if (st.ro) return; await run("cr.contract_save", { project_id: st.pid, data: st.p, audit: 0 }); }
  async function saveEv(ev, auditIt) { if (st.ro) return; await run("cr.claim_save", { project_id: st.pid, event_id: ev.id, data: ev, audit: auditIt ? 1 : 0 }); }
  /* re-draw without losing the field the user is in */
  function keepFocus(fn) {
    const a = document.activeElement; const id = a && a.id; const s = a && a.selectionStart;
    fn();
    if (id) { const el = document.getElementById(id); if (el) { el.focus(); try { if (s != null) el.setSelectionRange(s, s); } catch (e) { /* ignore */ } } }
  }
  /* an input bound to obj[key]; after a change: save, then redraw */
  function inp(obj, key, o) {
    o = o || {};
    const type = o.type || "text";
    const id = o.id || ("cr-" + key);
    let el;
    if (type === "textarea") el = h("textarea", { id, rows: o.rows || 3, placeholder: o.ph || null, disabled: st.ro }, obj[key] ?? "");
    else if (type === "select") el = h("select", { id, disabled: st.ro }, o.blank !== false ? h("option", { value: "" }, o.blank || "—") : null, o.options.map(([v, l]) => h("option", { value: v, selected: String(obj[key] ?? "") === String(v) }, l)));
    else if (type === "check") el = h("input", { type: "checkbox", id, checked: !!obj[key], disabled: st.ro });
    else el = h("input", { type, id, value: obj[key] ?? "", step: type === "number" ? "any" : null, min: type === "number" ? (o.min ?? null) : null, placeholder: o.ph || null, disabled: st.ro });
    el.addEventListener("change", async () => {
      let v = type === "check" ? el.checked : el.value;
      if (type === "number") v = v === "" ? null : +v;
      if (type === "check" && o.asDate) v = v ? todayISO() : "";
      if (v === "" || v == null) { if (o.keepBlank) obj[key] = ""; else delete obj[key]; } else obj[key] = v;
      if (o.after) o.after(v);
      try { await (o.save || saveP)(); } catch (e) { return; }
      (o.redraw || redraw)();
    });
    if (type === "check") return h("label", { class: "f check" + (o.wide ? " wide" : "") }, el, " ", o.label);
    return o.label ? h("label", { class: "f" + (o.wide ? " wide" : "") }, h("span", {}, o.label), el, o.hint ? h("small", { class: "fhint" }, o.hint) : null) : el;
  }
  const BADGE = { over: "b-over", soon: "b-soon", up: "b-up", done: "b-done", late: "b-late", barred: "b-barred", wait: "b-wait", idle: "b-idle", info: "b-info", open: "b-open", "cert-over": "b-over", other: "b-other", ok: "b-done", watch: "b-soon", risk: "b-over", na: "b-idle", none: "b-wait" };
  const badge = (cls, text) => h("span", { class: "crb " + (BADGE[cls] || cls) }, text);
  function stepBadge(step, b) {
    if (!step) return badge("done", "No action due");
    const other = step.who === "a" || step.who === "b";
    const map = { over: other ? `${step.who === "a" ? b.admin : b.board} ${-step.daysLeft} d late` : `${-step.daysLeft} d overdue`, soon: `${step.daysLeft} d left`, up: `${step.daysLeft} d left`, open: "Open" };
    return badge(other && step.st === "over" ? "other" : step.st, map[step.st] || step.st);
  }
  function stepStatusText(s, b) {
    const who = s.who === "a" ? b.admin : s.who === "b" ? b.board : null;
    switch (s.st) {
      case "over": return who ? `${who} is ${plural(-s.daysLeft, "day")} late` : `${plural(-s.daysLeft, "day")} overdue`;
      case "soon": case "up": return `${plural(s.daysLeft, "day")} left`;
      case "wait": return s.kind === "earliest" && s.due ? `From ${fmt(s.due)}` : "Starts after the previous step";
      case "done": return `Done ${fmt(s.done)}`;
      case "late": return `Done ${fmt(s.done)}, ${plural(diff(s.done, s.due), "day")} late`;
      case "barred": return `Done ${fmt(s.done)}, ${plural(diff(s.done, s.due), "day")} late: time-bar risk`;
      case "idle": return "Only if you dispute the outcome";
      case "info": return s.due ? fmt(s.due) : "After the previous step";
      case "open": return s.kind === "earliest" ? (s.due ? `Open from ${fmt(s.due)}` : "Open") : "No fixed deadline";
      default: return "";
    }
  }
  const meter = (sg) => h("span", { class: "crm " + sg.grade, title: "Claim strength " + sg.score + "/100" }, h("span", { class: "bar" }, h("i", { style: "width:" + sg.score + "%" })), h("b", {}, sg.score));
  const ents = (e) => h("span", {}, String(e || "").split("").map((t) => h("span", { class: "crent " + t }, ENT[t] || t)));
  const chip = (t) => h("span", { class: "crchip" }, t);
  const verify = () => h("span", { class: "crverify", title: "From secondary sources or numbering varies between versions: confirm in your copy" }, "check");
  const panel = (title, ...kids) => h("div", { class: "panel" }, title ? h("h2", {}, title) : null, kids);
  const clock = (cells) => h("div", { class: "tiles" }, cells.filter(Boolean).map(([k, v, s, cls]) => h("div", { class: "tile " + (cls || ""), style: "cursor:default" }, h("b", {}, v), h("span", {}, k), s ? h("small", {}, s) : null)));
  const svgNode = (html) => { const d = h("div", { class: "tablewrap" }); d.innerHTML = html; return d; };

  if (!document.getElementById("cr-style")) {
    document.head.append(h("style", { id: "cr-style" }, `
      .crb { display:inline-block; white-space:nowrap; padding:1px 8px; border-radius:10px; font-size:12px; font-weight:600; border:1px solid transparent; }
      .b-over, .b-barred { background: var(--red-wash); color: var(--red); border-color: var(--red); }
      .b-soon, .b-late { background: var(--amber-wash); color: #8a5a00; border-color: var(--amber); }
      .b-up, .b-open, .b-info { background: var(--blue-wash); color: var(--blue-deep); }
      .b-done { background: var(--green-wash); color: var(--green); }
      .b-wait, .b-idle { background: var(--line-soft, #eee); color: var(--muted); }
      .b-other { background: #f3e8ff; color: #6b21a8; border-color: #c4a1e8; }
      .crm { display:inline-flex; align-items:center; gap:6px; } .crm .bar { width:70px; height:6px; background: var(--line); border-radius:3px; overflow:hidden; display:inline-block; }
      .crm .bar i { display:block; height:100%; } .crm.strong i { background: var(--green); } .crm.fair i { background: var(--amber); } .crm.weak i { background: var(--red); }
      .crm.big .bar { width:180px; height:10px; } .crm.big b { font-size:22px; }
      .crent { display:inline-block; font-size:11px; padding:0 6px; border-radius:8px; margin:1px 3px 1px 0; background: var(--blue-wash); color: var(--blue-deep); }
      .crent.N { background: var(--red-wash); color: var(--red); } .crent.P, .crent.p { background: var(--green-wash); color: var(--green); }
      .crchip { display:inline-block; font: 12px ui-monospace, Consolas, monospace; border:1px solid var(--line); border-radius:5px; padding:0 5px; margin-right:4px; }
      .crverify { display:inline-block; font-size:10px; text-transform:uppercase; color:#8a5a00; border:1px dashed var(--amber); border-radius:4px; padding:0 4px; margin-left:4px; }
      .crtb { display:inline-block; font-size:10px; text-transform:uppercase; color: var(--red); border:1px solid var(--red); border-radius:4px; padding:0 4px; margin-left:6px; }
      .crstep { display:grid; grid-template-columns: 14px 1fr auto; gap:10px; padding:9px 0; border-top:1px solid var(--line); align-items:start; }
      .crstep .mk { width:12px; height:12px; border-radius:50%; margin-top:4px; background: var(--line); }
      .crstep.st-done .mk { background: var(--green); } .crstep.st-over .mk, .crstep.st-barred .mk { background: var(--red); } .crstep.st-soon .mk, .crstep.st-late .mk { background: var(--amber); }
      .crstep.st-up .mk, .crstep.st-open .mk { background: var(--blue); } .crstep.st-idle { opacity:.6; }
      .crstep .hd { font-weight:600; } .crstep .meta { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:3px; font-size:12.5px; }
      .crstep .note { color: var(--muted); font-size:12.5px; margin-top:3px; } .crstep .ins { display:flex; flex-direction:column; gap:4px; min-width:150px; }
      .crrv { display:grid; grid-template-columns: 1fr 260px; gap:14px; padding:12px 0; border-top:1px solid var(--line); }
      .crrv.st-risk { box-shadow: inset 3px 0 0 var(--red); padding-left:10px; } .crrv.st-watch { box-shadow: inset 3px 0 0 var(--amber); padding-left:10px; } .crrv.st-ok { box-shadow: inset 3px 0 0 var(--green); padding-left:10px; }
      .crrv .gc { color: var(--muted); font-size:13px; margin:4px 0; } .crrv .ask { font-size:13px; margin:4px 0; }
      .crradar .it { display:grid; grid-template-columns: 110px 1fr auto; gap:10px; padding:8px 4px; border-top:1px solid var(--line); cursor:pointer; align-items:center; }
      .crradar .it:hover { background: var(--blue-wash); } .crradar .t { font-weight:600; } .crradar .s { color: var(--muted); font-size:12.5px; }
      .crtrack { height:8px; background: var(--line); border-radius:4px; overflow:hidden; margin:4px 0 14px; } .crtrack i { display:block; height:100%; background: var(--blue); }
      .crflow { display:flex; flex-wrap:wrap; gap:8px; margin:8px 0; } .crflow .node { border:1px solid var(--line); border-radius:8px; padding:8px 10px; min-width:150px; max-width:210px; font-size:12.5px; }
      .crflow .node.bar { border-left:4px solid var(--red); } .crflow .node.disp { border-style:dashed; } .crflow .who { font-size:11px; color: var(--muted); text-transform:uppercase; }
      svg.crtl text { font-size:11px; fill: var(--ink); } svg.crtl .ax { fill: var(--muted); } svg.crtl .grid { stroke: var(--line); }
      svg.crtl .rowbg { fill: var(--blue-wash); opacity:.35; } svg.crtl .orig, svg.crtl .bar { fill: var(--blue); } svg.crtl .ext { fill: var(--amber); }
      svg.crtl .over, svg.crtl .bar.risk { fill: var(--red); } svg.crtl .bar.closed { fill: var(--green); } svg.crtl .today { stroke: var(--red); stroke-dasharray: 4 3; }
      svg.crtl .mk-ok { fill: var(--green); } svg.crtl .mk-late { fill: var(--red); } svg.crtl .mk-det { fill:#fff; stroke: var(--ink); stroke-width:1.5; } svg.crtl .mk-due { fill: var(--amber); }
      svg.crtl g.ev { cursor:pointer; }
      .crdrawer .modal { max-width: 980px; }
    `));
  }

  /* ───────── page ───────── */
  const TABS = [["overview", "Overview"], ["events", "Claim events"], ["payments", "Payments"], ["timeline", "Timeline"], ["startup", "Start-up"],
                ["tender", "Tender review"], ["neg", "Negotiation"], ["contract", "Contract & conditions"], ["library", "Clause library"], ["portfolio", "All contracts"]];
  function redraw() {
    if (!st.body) return;
    keepFocus(() => {
      st.body.innerHTML = "";
      try { st.body.append(VIEWS[st.tab]()); } catch (e) { st.body.append(h("p", { class: "red" }, e.message)); }
      st.bar.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tab === st.tab));
    });
    if (st.drawer) st.drawer.refresh();
  }
  function goTab(t) {
    st.tab = t;
    history.replaceState(null, "", "#/cr?tab=" + t);
    if (t === "portfolio") return portfolioTab();
    redraw();
  }
  function contractHead(p) {
    const b = bookOf(p);
    return h("div", { class: "bar", style: "align-items:baseline;flex-wrap:wrap;margin-bottom:6px" },
      h("b", {}, p.name || st.d.project.name), p.stage === "tender" ? badge("soon", "Before award") : badge("done", "After award"),
      h("span", { class: "hint" }, bookLabel(p.book) + " · " + b.title + (p.contractNo ? " · " + p.contractNo : "") + (p.employer ? " · Employer: " + p.employer : "") + (p.adminName ? " · " + b.admin + ": " + p.adminName : "")));
  }

  PAGES.cr = async (root, params) => {
    st.root = root;
    st.tab = TABS.some(([k]) => k === params.tab) ? params.tab : "";
    st.drawer = null;
    if (!S.project || st.tab === "portfolio") {
      st.tab = "portfolio";
      st.pid = S.project ? Number(S.project) : null;
      return portfolioTab();
    }
    st.pid = Number(S.project);
    await reload();
    if (!st.p) return setupScreen(root);
    if (!st.tab) st.tab = st.p.stage === "tender" ? "tender" : "overview";
    shell();
    if (params.ev) openEvent(Number(params.ev));
  };

  function shell() {
    const root = st.root;
    root.innerHTML = "";
    st.bar = h("div", { class: "tabs" }, TABS.map(([k, l]) => h("button", { type: "button", "data-tab": k, onclick: () => goTab(k) }, l)));
    st.body = h("div");
    root.append(pageHead("Claims register", st.d.project.code + " " + st.d.project.name + " · deadlines, notices and claims under the contract's own conditions",
      !st.ro ? h("button", { class: "btn primary", onclick: () => newEvent() }, "Log a claim event") : null), st.bar, st.body);
    redraw();
  }

  /* first visit on a project: set up the contract */
  function setupScreen(root) {
    root.innerHTML = "";
    const pr = st.d.project;
    const v = { name: pr.name, contractNo: "", book: "red17", stage: "execution", employer: pr.client || "", commencement: pr.ntp_date || pr.start_date || "",
                tfcDays: pr.tfc_days || (pr.start_date && pr.completion_date ? diff(pr.completion_date, pr.start_date) : ""), price: pr.contract_value || "", currency: "NPR" };
    const groups = BOOK_GROUPS.map(([g, ids]) => h("optgroup", { label: g }, ids.map((id) => h("option", { value: id, selected: id === v.book }, bookLabel(id) + " · " + BOOKS[id].title))));
    const book = h("select", {}, groups);
    const use = h("small", { class: "fhint" }, BOOKS[v.book].use);
    book.onchange = () => { use.textContent = BOOKS[book.value].use; };
    const f = form([{ k: "name", label: "Contract name", wide: true }, { k: "contractNo", label: "Contract no." }, { k: "employer", label: "Employer" },
      { k: "stage", label: "Stage", type: "select", noBlank: true, options: [["execution", "After award (execution)"], ["tender", "Before award (tender and negotiation)"]] },
      { k: "commencement", label: "Commencement / Start Date", type: "date" }, { k: "tfcDays", label: "Time for Completion (days)", type: "number" },
      { k: "price", label: "Accepted Contract Amount", type: "number" }, { k: "currency", label: "Currency" }], v);
    root.append(pageHead("Claims register", pr.code + " " + pr.name),
      panel("Set up the contract for this project",
        h("p", { class: "hint" }, "The form of contract and its Particular Conditions drive every deadline in the register. Pick the conditions of contract; the periods, time bars and claim clauses of that form are filled in, and you can change them to match your contract afterwards."),
        h("label", { class: "f wide" }, h("span", {}, "Conditions of contract"), book, use), f,
        st.ro ? h("p", { class: "hint" }, "Setting up needs the Commercial edit right.") : h("button", { class: "btn primary", onclick: async () => {
          const x = f.values();
          const b = BOOKS[book.value];
          st.p = { name: x.name || pr.name, contractNo: x.contractNo, book: book.value, stage: x.stage || "execution", employer: x.employer, commencement: isISO(x.commencement) ? x.commencement : "",
                   tfcDays: num(x.tfcDays), price: num(x.price), currency: x.currency || "NPR", ppa: b.fam === "ppmo", po: {}, bo: {}, ce: {}, cc: [], payments: [], rv: {}, neg: [], td: {}, su: {}, sp: {} };
          await run("cr.contract_save", { project_id: st.pid, data: st.p }, "Contract set up");
          st.tab = st.p.stage === "tender" ? "tender" : "contract";
          await reload(); shell();
        } }, "Set up the contract")));
  }

  /* ───────── Overview ───────── */
  function viewOverview() {
    const p = st.p;
    if (p.stage === "tender") return viewTenderOverview();
    const b = bookOf(p), today = todayISO(), evs = st.evs;
    const open = evs.filter((e) => !isClosed(e));
    const oc = originalCompletion(p), cc = currentCompletion(p, evs), eot = eotGranted(evs);
    let elapsed = 0, lateDays = 0;
    if (isISO(p.commencement) && cc) { const tot = diff(cc, p.commencement) || 1; elapsed = Math.max(0, Math.min(1, diff(today, p.commencement) / tot)); lateDays = Math.max(0, diff(today, cc)); }
    const daysToGo = cc ? diff(cc, today) : null;
    const items = [];
    for (const e of open) { const sts = buildSteps(p, e, evs); for (const s of sts) { if (s.f && !s.done && ["over", "soon", "up"].includes(s.st)) {
      items.push({ due: s.due, title: (e.no ? e.no + " " : "") + (e.title || "Untitled event"), sub: [s.label, s.refText, s.bar ? "Time bar" : ""].filter(Boolean).join(" · "), badge: stepBadge(s, b), go: () => openEvent(e.id) }); break; } } }
    if (isISO(p.loa)) for (const s of suSteps(p)) if (!s.done && ["over", "soon", "up"].includes(s.st))
      items.push({ due: s.due, title: s.label, sub: "Start-up · " + (s.ref || ""), badge: badge(s.who === "c" ? s.st : (s.st === "over" ? "other" : s.st), s.st === "over" ? `${-s.daysLeft} d ${s.who === "c" ? "overdue" : "late"}` : `${s.daysLeft} d left`), go: () => goTab("startup") });
    for (const l of st.d.open_letters) { const left = diff(l.reply_by, today); if (left <= 14) items.push({ due: l.reply_by, title: l.subject, sub: (l.direction === "in" ? "Reply to " : "Answer awaited on ") + (l.our_no || ""), badge: badge(left < 0 ? "over" : left <= 7 ? "soon" : "up", left < 0 ? `${-left} d overdue` : `${left} d left`), go: () => { location.hash = "#/ca/letters?id=" + l.id; } }); }
    items.sort((a, c) => (a.due || "9") < (c.due || "9") ? -1 : 1);
    const barred = evs.filter((e) => { const n = buildSteps(p, e, evs).find((s) => s.id === "notice"); return n && (n.st === "barred" || (n.st === "over" && n.bar)); });
    const sum = (k) => evs.reduce((a, e) => a + (+e[k] || 0), 0);
    const counts = {}; evs.forEach((e) => { const s = eventStatus(e, b); counts[s] = (counts[s] || 0) + 1; });
    const sec = st.d.securities.filter((x) => isISO(x.expiry_date)).map((x) => Object.assign({}, x, { left: diff(x.expiry_date, today) })).filter((x) => x.left <= 60);
    const payIssues = payRows(p, allPayments()).filter((r) => r.st === "over" || r.st === "cert-over");
    const flags = rvItems(p).filter((it) => rvStatus(p, it) === "risk");
    return h("div", {}, contractHead(p),
      clock([["Commencement", fmt(p.commencement), p.tfcDays ? p.tfcDays + " days to complete" : "Set Time for Completion"], ["Original completion", fmt(oc), "From the contract"],
        ["EOT granted", "+" + eot + " d", plural(evs.filter((e) => +e.eotGranted).length, "event")],
        ["Current completion", fmt(cc), daysToGo == null ? "—" : daysToGo >= 0 ? daysToGo + " days to go" : -daysToGo + " days past", lateDays ? "bad" : ""]]),
      cc ? h("div", { class: "crtrack", title: Math.round(elapsed * 100) + "% of the current Time for Completion elapsed" }, h("i", { style: "width:" + elapsed * 100 + "%" })) : null,
      barred.length ? h("div", { class: "panel", style: "border-left:4px solid var(--red)" }, h("b", { class: "red" }, "Time-bar risk on " + plural(barred.length, "event") + ": "),
        barred.map((e, i) => [i ? ", " : "", h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); openEvent(e.id); } }, e.title || "Untitled")]),
        ". Notice is overdue or went out late under a clause your contract treats as a time bar.") : null,
      h("div", { class: "grid2", style: "display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:14px" },
        panel("Deadline radar", items.length ? h("div", { class: "crradar" }, items.slice(0, 12).map((x) => h("div", { class: "it", onclick: x.go }, h("span", {}, fmt(x.due)), h("div", {}, h("div", { class: "t" }, x.title), h("div", { class: "s" }, x.sub)), x.badge)))
          : h("p", { class: "hint" }, evs.length ? "No open deadlines. Every logged step is done or waiting on an earlier step." : "No events yet. Log anything that could cost you time or money — late drawings, bad ground, blocked access — the day you learn of it."),
          items.length > 12 ? h("p", { class: "hint" }, (items.length - 12) + " more in Claim events and Start-up.") : null),
        h("div", {},
          panel("Claims position", kv([["Events logged", evs.length + " (" + open.length + " open)"], ["EOT claimed / granted", sum("eotClaimed") + " / " + sum("eotGranted") + " d"],
            ["Cost claimed", money(sum("costClaimed"), p.currency)], ["Cost agreed", money(sum("costGranted"), p.currency)]]),
            Object.keys(counts).length ? h("div", { class: "chips" }, Object.entries(counts).map(([k, n]) => h("span", { class: "chip" }, k, h("i", {}, n)))) : null),
          sec.length || payIssues.length ? panel("Money and securities",
            payIssues.map((r) => h("div", {}, (r.no || "Statement") + ": " + r.stText + (r.fin ? " · financing " + money(r.fin, p.currency) : ""))),
            sec.map((x) => h("div", {}, h("a", { href: "#/ca/securities" }, (x.kind || "Security") + " " + (x.number || "")), " ", badge(x.left < 0 ? "over" : x.left <= 30 ? "soon" : "up", x.left < 0 ? `expired ${-x.left} d ago` : `expires in ${x.left} d`)))) : null,
          p.ppa ? ppaPanel() : null,
          flags.length ? panel("Risks accepted at signing", h("p", { class: "hint" }, "Red-flag terms from the tender review. Watch these clauses: they cut your entitlement."),
            flags.slice(0, 6).map((it) => h("div", { style: "margin:6px 0" }, h("b", {}, it.t + " "), chip(rvRef(p, it)), h("div", { class: "hint" }, rvTenderText(p, it)))),
            h("button", { class: "btn small", onclick: () => goTab("tender") }, "Open tender review")) : null)));
  }
  function ppaPanel() {
    const p = st.p; const price = +p.price || 0;
    const varSum = st.evs.filter((e) => e.cat === "variation").reduce((a, e) => a + (+(e.costGranted || e.costClaimed) || 0), 0);
    const pct = price ? varSum / price * 100 : null;
    const months = (+p.tfcDays || 0) / 30.44;
    const cc = currentCompletion(p, st.evs); const late = cc ? Math.max(0, diff(todayISO(), cc)) : 0;
    const ldRate = num(p.ldPct) ?? 0.05, ldCap = num(p.ldCapPct) ?? 10;
    const ld = price ? Math.min(price * ldRate / 100 * late, price * ldCap / 100) : null;
    return panel("Nepal PPA checks", kv([["Variations so far", pct == null ? "—" : pct.toFixed(1) + "%"], ["Approval needed", pct == null ? "Enter the contract amount" : ppaTier(pct)],
      ["Price adjustment (s.55)", p.tfcDays ? (months > 15 ? "Eligible" : "Not eligible") : "—"], ["LD exposure today", late ? money(ld, p.currency) : "None"]]),
      h("p", { class: "hint" }, `Variation % counts the agreed (or claimed) value of events in the Variations category against the original contract amount; approval tiers follow PPA s.54 as amended in 2083. LD uses ${ldRate}% per day, cap ${ldCap}%.`));
  }
  function viewTenderOverview() {
    const p = st.p; const c = rvCounts(p); const flags = rvItems(p).filter((it) => rvStatus(p, it) === "risk");
    const dates = tenderDates(p).filter((x) => diff(x.d, todayISO()) >= 0);
    const neg = p.neg || []; const cnt = (s) => neg.filter((n) => n.status === s).length;
    return h("div", {}, contractHead(p),
      clock([["Checked", c.done + "/" + c.total, "terms reviewed"], ["Red flags", c.risk, c.watch + " more to watch", c.risk ? "bad" : ""], ["Negotiation", neg.length, (cnt("agreed") + cnt("partial")) + " agreed · " + cnt("rejected") + " rejected"],
        ["Bid deadline", fmt((p.td || {}).deadline), isISO((p.td || {}).deadline) ? (diff(p.td.deadline, todayISO()) >= 0 ? diff(p.td.deadline, todayISO()) + " days to go" : "passed") : "Enter under Tender review"]]),
      panel("Red flags in this tender", flags.length ? flags.map((it) => h("div", { style: "margin:6px 0" }, h("b", {}, it.t + " "), chip(rvRef(p, it)), h("div", {}, rvTenderText(p, it)), h("div", { class: "hint" }, it.ask)))
        : h("p", { class: "hint" }, c.done ? "No red flags so far." : "Nothing checked yet. Open Tender review and work through the terms."), h("button", { class: "btn small", onclick: () => goTab("tender") }, "Review terms")),
      panel("Coming up", dates.length ? dates.map((x) => h("div", {}, fmt(x.d) + " · " + x.l + " ", tdBadge(x))) : h("p", { class: "hint" }, "No tender dates entered.")),
      panel("When you win the contract", h("p", { class: "hint" }, "Record the Letter of Acceptance. The register moves to execution, copies the agreed terms into Contract & conditions and starts the start-up deadlines."),
        !st.ro ? h("button", { class: "btn primary", onclick: showAward }, "Contract awarded") : null));
  }

  /* ───────── Claim events ───────── */
  function viewEvents() {
    const p = st.p, b = bookOf(p), f = st.filter;
    let evs = st.evs.map((e) => { const s = buildSteps(p, e, st.evs); return { e, nx: nextStep(s), str: strength(p, e, s) }; });
    if (f.st === "open") evs = evs.filter((x) => !isClosed(x.e)); else if (f.st === "closed") evs = evs.filter((x) => isClosed(x.e));
    if (f.cat) evs = evs.filter((x) => x.e.cat === f.cat);
    if (f.q) { const q = f.q.toLowerCase(); evs = evs.filter((x) => `${x.e.no || ""} ${x.e.title} ${(x.e.refs || []).join(" ")} ${x.e.desc || ""}`.toLowerCase().includes(q)); }
    evs.sort((a, c) => (a.nx && a.nx.due || "9999") < (c.nx && c.nx.due || "9999") ? -1 : (a.nx && a.nx.due || "9999") > (c.nx && c.nx.due || "9999") ? 1 : 0);
    const used = [...new Set(st.evs.map((e) => e.cat).filter(Boolean))];
    const qbox = h("input", { type: "search", value: f.q, placeholder: "Search events, clauses", style: "max-width:260px", oninput: () => { f.q = qbox.value; clearTimeout(qbox._t); qbox._t = setTimeout(redraw, 250); }, id: "cr-fq" });
    const cat = h("select", { style: "width:auto", onchange: () => { f.cat = cat.value; redraw(); } }, h("option", { value: "" }, "All categories"), used.map((c) => h("option", { value: c, selected: f.cat === c }, (CATS[c] || {}).n || c)));
    const sts = h("select", { style: "width:auto", onchange: () => { f.st = sts.value; redraw(); } }, [["open", "Open"], ["closed", "Closed"], ["all", "All"]].map(([k, l]) => h("option", { value: k, selected: f.st === k }, l)));
    const rows = evs.map(({ e, nx, str }) => Object.assign({}, e, { _nx: nx, _str: str }));
    const other = st.d.events;
    return h("div", {},
      h("p", { class: "hint" }, "Every event that could give you time or money under " + bookLabel(p.book) + ", with its next deadline. Claim events are BuildCore events: they also show in Events & claims."),
      h("div", { class: "bar" }, qbox, cat, sts, h("div", { class: "grow" }), !st.ro ? h("button", { class: "btn primary", onclick: () => newEvent() }, "Log an event") : null),
      table([{ label: "Event", v: (e) => h("div", {}, h("b", {}, e.title || "Untitled event"), h("div", { class: "hint" }, (e.no || "") + " ", (e.refs || []).map(chip), (CATS[e.cat] || {}).n || "")) },
        { label: "Status", v: (e) => h("div", {}, eventStatus(e, b), h("div", { class: "hint" }, "aware " + fmt(e.aware || e.occurred))) },
        { label: "Next action", v: (e) => e._nx ? h("div", {}, e._nx.label, h("div", {}, fmt(e._nx.due), " ", stepBadge(e._nx, b))) : "—" },
        { label: "EOT (d)", fmt: "num", v: (e) => e.eotClaimed ?? "" }, { label: "EOT granted", fmt: "num", v: (e) => e.eotGranted ?? "" },
        { label: "Cost claimed", fmt: "money", v: (e) => num(e.costClaimed) }, { label: "Cost agreed", fmt: "money", v: (e) => num(e.costGranted) },
        { label: "Strength", v: (e) => meter(e._str) }], rows,
        { name: "claim_events", title: "Claim events", search: false, onRow: (e) => openEvent(e.id), empty: st.evs.length ? "No events match these filters." : "No claim events yet. Log an event the day you become aware of it: the notice clock starts then, whether or not you know the cost yet." }),
      other.length ? panel("Other events on this project (not followed here yet)",
        h("p", { class: "hint" }, "Delays, instructions and notices recorded in Events & claims or from DPRs. Follow one here to get its claim timeline; nothing in the event is lost."),
        table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "type", label: "Type" }, { k: "title", label: "Title" }, { k: "status", label: "Status" },
          { k: "delay_days", label: "Delay (d)", fmt: "num" }, { k: "cost_impact", label: "Cost", fmt: "money" },
          { label: "", v: (e) => !st.ro ? h("button", { class: "btn small", onclick: async (x) => { x.stopPropagation(); await run("cr.track", { event_id: e.id }, "Now followed in the claims register"); await reload(); redraw(); openEvent(e.id); } }, "Follow as claim") : "" }],
        other, { search: other.length > 8, export: false })) : null);
  }

  function newEvent(prefill) {
    const p = st.p; const cl = activeClauses(p);
    const title = h("input", { value: (prefill || {}).title || "", placeholder: "e.g. Shear zone at headrace Ch 1+240" });
    const aware = h("input", { type: "date", value: (prefill || {}).aware || todayISO() });
    const qq = h("input", { type: "search", placeholder: "Search: access, drawings, ground, payment…" });
    const box = h("div", { style: "max-height:340px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:4px 8px" });
    const groups = {}; cl.forEach((c) => (groups[c.c] = groups[c.c] || []).push(c));
    const ticks = [];
    Object.keys(CATS).filter((c) => groups[c]).forEach((c) => {
      box.append(h("div", { class: "hint", style: "font-weight:600;margin-top:8px", "data-grp": c }, CATS[c].n));
      groups[c].forEach((x) => {
        const cb = h("input", { type: "checkbox", value: x.r, checked: ((prefill || {}).refs || []).includes(x.r) });
        ticks.push([cb, x]);
        box.append(h("label", { style: "display:flex;gap:8px;padding:4px 0;align-items:flex-start", "data-s": (x.r + " " + x.t + " " + x.n + " " + CATS[c].n).toLowerCase() }, cb, chip(x.r), h("span", {}, h("b", {}, x.t), " ", ents(x.e), h("div", { class: "hint" }, x.n))));
      });
    });
    if (!cl.length) box.append(h("p", { class: "hint" }, "No clauses set up for this form yet. You can still log the event and link a clause later."));
    qq.oninput = () => { const t = qq.value.toLowerCase(); box.querySelectorAll("label[data-s]").forEach((l) => { l.style.display = !t || l.dataset.s.includes(t) ? "" : "none"; }); };
    modal("Log a claim event", h("div", {}, h("div", { class: "grid" }, h("label", { class: "f wide" }, h("span", {}, "What happened?"), title), h("label", { class: "f" }, h("span", {}, "You became aware on"), aware)),
      h("label", { class: "f wide" }, h("span", {}, "Find the clause"), qq), box, h("p", { class: "hint" }, "Pick every clause that could apply. You can change this later.")),
    [{ label: "Log event", cls: "primary", act: async () => {
      const refs = ticks.filter(([cb]) => cb.checked).map(([, x]) => x.r);
      const first = refs.length ? clauseByRef(p, refs[0]) : null;
      const a = isISO(aware.value) ? aware.value : todayISO();
      const ev = Object.assign({ title: title.value.trim() || (first || {}).t || "New event", refs, cat: (first || {}).c || "delay", aware: a, occurred: a, evidence: {}, records: [] }, (prefill || {}).extra || {});
      const r = await run("cr.claim_save", { project_id: st.pid, data: ev }, (x) => "Event " + x.no + " logged. The notice clock is running.");
      await reload(); if (st.tab !== "events" && st.tab !== "overview") st.tab = "events"; redraw(); openEvent(r.id);
    } }]);
    title.focus();
  }

  /* ───────── one claim event ───────── */
  function openEvent(id) {
    const ev0 = st.evs.find((e) => e.id === id);
    if (!ev0) { toast("That claim is not on this project.", "err"); return; }
    const body = h("div");
    const m = drawer("Claim event", body, [], { onClose: () => { st.drawer = null; history.replaceState(null, "", "#/cr?tab=" + st.tab); } });
    m.el.classList.add("crdrawer");
    history.replaceState(null, "", "#/cr?tab=" + st.tab + "&ev=" + id);
    const save = async () => { const ev = st.evs.find((e) => e.id === id); await saveEv(ev); };
    const refresh = () => {
      const ev = st.evs.find((e) => e.id === id);
      if (!ev) { m.close(); return; }
      const scroll = body.parentElement ? body.parentElement.scrollTop : 0;
      keepFocus(() => { body.innerHTML = ""; body.append(eventBody(ev, save, () => { redrawMain(); refresh(); }, m)); });
      if (body.parentElement) body.parentElement.scrollTop = scroll;
    };
    const redrawMain = () => { keepFocus(() => { st.body.innerHTML = ""; st.body.append(VIEWS[st.tab]()); }); };
    st.drawer = { refresh, id };
    refresh();
  }

  function eventBody(ev, save, after, m) {
    const p = st.p, b = bookOf(p);
    const steps = buildSteps(p, ev, st.evs); const nx = nextStep(steps); const sg = strength(p, ev, steps);
    const o = (extra) => Object.assign({ save, redraw: after }, extra);
    const E = (k, label, type, extra) => inp(ev, k, o(Object.assign({ id: "ef-" + k, label, type }, extra || {})));
    const letters = st.d.letters.filter((l) => l.event_id === ev.id);
    const refsBox = h("div");
    (ev.refs || []).forEach((r) => { const c = clauseByRef(p, r);
      refsBox.append(h("div", { style: "display:flex;gap:10px;justify-content:space-between;padding:6px 0;border-bottom:1px dashed var(--line)" },
        h("div", {}, chip(r), h("b", {}, (c || {}).t || "Not in the current form"), c && c.v === 0 ? verify() : null, c && c.n ? h("div", { class: "hint" }, c.n) : null, c ? h("div", {}, ents(c.e)) : null),
        !st.ro ? h("button", { class: "btn small", onclick: async () => { ev.refs = ev.refs.filter((x) => x !== r); await save(); after(); } }, "Remove") : null)); });
    const avail = activeClauses(p).filter((c) => !(ev.refs || []).includes(c.r));
    const addSel = h("select", { style: "max-width:420px", disabled: st.ro }, h("option", { value: "" }, "Add a clause…"), avail.map((c) => h("option", { value: c.r }, c.r + " · " + c.t)));
    addSel.onchange = async () => { if (!addSel.value) return; ev.refs = [...(ev.refs || []), addSel.value]; if (!ev.cat || ev.refs.length === 1) ev.cat = (clauseByRef(p, addSel.value) || {}).c || ev.cat; await save(); after(); };
    const refField = { notice: "noticeRef", detailed: "detailedRef", response: "responseRef" };
    const stepsBox = h("div", {}, steps.map((s) => h("div", { class: "crstep st-" + s.st }, h("span", { class: "mk" }),
      h("div", {}, h("div", { class: "hd" }, s.label, s.refText ? h("span", { class: "hint" }, "  " + s.refText) : null, s.bar ? h("span", { class: "crtb" }, "Time bar") : null, s.crit ? h("span", { class: "crtb", style: "color:#8a5a00;border-color:var(--amber)" }, "Critical") : null),
        h("div", { class: "meta" }, s.due && s.kind !== "info" ? h("span", {}, (s.kind === "earliest" ? "From " : "Due ") + fmt(s.due)) : null, badge(s.st, stepStatusText(s, b)),
          s.deemed ? h("span", {}, "Determination not given in time: treated as rejected.") : null, s.capped ? h("span", {}, "Brought forward by the completion-date cut-off.") : null),
        s.note ? h("div", { class: "note" }, s.note) : null),
      s.f ? h("div", { class: "ins" }, inp(ev, s.f, o({ id: "ef-" + s.f, type: "date" })),
        refField[s.id] ? inp(ev, refField[s.id], o({ id: "ef-" + refField[s.id], ph: "Letter ref." })) : null,
        s.id === "response" ? inp(ev, "outcome", o({ id: "ef-outcome", type: "select", blank: "Outcome…", options: [["agreed", "Agreed in full"], ["partial", "Partly agreed"], ["rejected", "Rejected"], ["withdrawn", "Withdrawn"]] })) : null) : h("span"))));
    const items = evidenceItems(ev); const got = items.filter(([k]) => (ev.evidence || {})[k]).length;
    ev.evidence = ev.evidence || {};
    const evid = h("div", {}, items.map(([k, t], i) => [i === COMMON_EV.length ? h("div", { class: "hint", style: "font-weight:600;margin-top:8px" }, "For " + ((CATS[ev.cat] || {}).n || "this category")) : null,
      h("div", {}, inp(ev.evidence, k, o({ id: "evd-" + k, type: "check", label: t })))]));
    ev.records = ev.records || [];
    const recs = h("div", {}, ev.records.length ? table([
      { label: "Date", v: (r) => inp(r, "date", o({ id: "rec-" + r.id + "-date", type: "date" })) },
      { label: "Type", v: (r) => inp(r, "type", o({ id: "rec-" + r.id + "-type", type: "select", blank: false, options: REC_TYPES.map((t) => [t, t]) })) },
      { label: "What it shows", v: (r) => inp(r, "desc", o({ id: "rec-" + r.id + "-desc", ph: "What it shows" })) },
      { label: "Ref. / file", v: (r) => inp(r, "ref", o({ id: "rec-" + r.id + "-ref", ph: "Ref." })) },
      { label: "", v: (r) => !st.ro ? h("button", { class: "btn small", onclick: async () => { ev.records = ev.records.filter((x) => x !== r); await save(); after(); } }, "Remove") : "" }], ev.records, { search: false, export: false }) : h("p", { class: "hint" }, "No records logged."),
      !st.ro ? h("button", { class: "btn small", onclick: async () => { ev.records.push({ id: uid(), date: todayISO(), type: "Letter", desc: "", ref: "" }); await save(); after(); } }, "Add record") : null);
    const r = qcCalc(p, ev); ev.qc = ev.qc || {}; const q = ev.qc; const cur = p.currency || "";
    const Q = (k, l, ph) => inp(q, k, o({ id: "qc-" + k, type: "number", label: l, ph: ph || null, min: 0 }));
    const hoOn = q.hoMethod && q.hoMethod !== "none";
    const qc = h("div", {}, h("p", { class: "hint" }, "Builds the money claim from time-related and direct costs. FIDIC “Cost” is expenditure reasonably incurred, including overheads, but not profit unless the clause gives it."),
      h("div", { class: "grid" }, Q("days", "Delay period (days)", ev.eotClaimed != null && ev.eotClaimed !== "" ? String(ev.eotClaimed) : ""), Q("siteOH", `Site overheads per day (${cur})`), Q("plantDay", `Idle plant per day (${cur})`),
        Q("plantDays", "Idle plant days", "same as delay"), Q("labour", `Idle labour, total (${cur})`), Q("direct", `Direct cost of extra work (${cur})`), Q("other", `Other costs (${cur})`),
        inp(q, "hoMethod", o({ id: "qc-hoMethod", type: "select", label: "Head-office overhead", blank: false, options: [["none", "Not claimed"], ["emden", "Emden formula"], ["hudson", "Hudson formula"]] })),
        hoOn ? Q("hoPct", q.hoMethod === "hudson" ? "Tender HO overhead and profit %" : "HO overhead and profit % (from accounts)") : null,
        r.entP ? Q("profitPct", "Profit % on direct and other costs") : null, Q("finRate", "Financing rate (% a year)"), Q("finDays", "Financing period (days)")),
      table([{ k: "l", label: "Head" }, { k: "v", label: "Amount", fmt: "money" }], [
        { l: `Site overheads (${fmtN(num(q.siteOH) || 0)} × ${r.d} d)`, v: r.site }, { l: `Idle plant (${fmtN(num(q.plantDay) || 0)} × ${r.pd} d)`, v: r.plant }, { l: "Idle labour", v: r.labour },
        { l: "Direct cost of extra work", v: r.direct }, { l: "Other costs", v: r.other },
        hoOn ? { l: `Head-office overhead (${q.hoMethod === "emden" ? "Emden" : "Hudson"}: ${num(q.hoPct) || 0}% × ${money(r.C, "")} ÷ ${r.P || "?"} d × ${r.d} d)${!r.C || !r.P ? " — enter the contract amount and Time for Completion" : ""}`, v: r.ho } : null,
        r.entP ? { l: `Profit (${num(q.profitPct) || 0}%)`, v: r.profit } : null, r.fin ? { l: `Financing (${num(q.finRate)}% × ${num(q.finDays)} d ÷ 365)`, v: r.fin } : null,
        { l: "Total", v: r.total }].filter(Boolean), { search: false, export: false }),
      !st.ro && r.total ? h("button", { class: "btn small", onclick: async () => { ev.costClaimed = Math.round(r.total); await save(); after(); toast("Cost claimed set to " + money(ev.costClaimed, cur), "ok"); } }, "Use as cost claimed") : null,
      hoOn ? h("p", { class: "hint" }, "Formula claims for head-office overhead are often challenged. Support them with audited accounts and evidence that the delay stopped you earning elsewhere.") : null);
    const kinds = [["notice", "Draft notice"], ["claim", "Draft claim outline"], b.fam === "fidic" ? ["nod", "Draft NOD"] : ["arb", "Draft dispute referral"]];
    return h("div", {},
      h("div", { class: "bar", style: "align-items:center;flex-wrap:wrap" }, h("b", {}, ev.no || ""), h("span", {}, eventStatus(ev, b)), nx ? [h("span", { class: "hint" }, "Next: " + nx.label + " by " + fmt(nx.due)), stepBadge(nx, b)] : null,
        h("div", { class: "grow" }), h("span", { class: "crm big " + sg.grade }, h("span", { class: "bar" }, h("i", { style: "width:" + sg.score + "%" })), h("b", {}, sg.score), " " + (sg.grade === "strong" ? "Strong" : sg.grade === "fair" ? "Fair" : "Weak"))),
      sg.gaps.length ? h("ul", { class: "hint", style: "margin:4px 0 10px 18px" }, sg.gaps.map((g) => h("li", {}, g))) : h("p", { class: "hint" }, "Notices on time, evidence in hand, cause and quantum written up."),
      panel("What happened", h("div", { class: "grid" }, E("title", "Title", "text", { wide: true }),
        E("cat", "Category", "select", { blank: false, options: Object.entries(CATS).map(([k, v]) => [k, v.n]) }), E("location", "Location / chainage"),
        E("occurred", "Event occurred", "date"), E("aware", "You became aware", "date"), E("continuing", "Effect is continuing", "check"), ev.continuing ? E("endEffects", "Effect ended", "date") : null,
        E("desc", "Description", "textarea", { wide: true, ph: "Facts only: what, where, when, who instructed, what you saw." }))),
      panel("Contractual entitlement", refsBox.childNodes.length ? refsBox : h("p", { class: "hint" }, "No clause linked yet."), h("div", { class: "bar" }, addSel)),
      panel("Claim timeline · " + bookLabel(p.book), stepsBox,
        E("dispute", "Escalate to dispute now (shows the dispute steps before an outcome is recorded)", "check")),
      panel("Quantum", h("div", { class: "grid" }, E("eotClaimed", "EOT claimed (days)", "number", { min: 0 }), E("eotGranted", "EOT granted (days)", "number", { min: 0 }),
        E("costClaimed", `Cost claimed (${cur})`, "number", { min: 0 }), E("costGranted", `Cost agreed (${cur})`, "number", { min: 0 })),
        h("p", { class: "hint" }, "Granted EOT moves the current completion date on the Overview and the delay days on the event."),
        h("details", { open: Object.keys(q).length ? true : null }, h("summary", {}, h("b", {}, "Quantum calculator")), qc)),
      panel("Cause, effect and mitigation", h("div", { class: "grid" }, E("causation", "Causation", "textarea", { wide: true, ph: "How the event delayed critical activities and caused cost. Link each step to a record." }),
        E("mitigation", "Mitigation", "textarea", { wide: true, ph: "What you did to reduce the delay and cost." }))),
      panel("Evidence checklist (" + got + " of " + items.length + ")", evid),
      panel("Contemporaneous records", h("p", { class: "hint" }, "Index every letter, diary page, photo set and measurement that proves this event. These become the appendix list in the claim. Attach the files themselves below."), recs),
      panel("Letters", letters.length ? table([{ k: "our_no", label: "Reg. no." }, { k: "date", label: "Date" }, { label: "", v: (l) => l.direction === "in" ? "In" : "Out" }, { k: "subject", label: "Subject" }, { k: "status", label: "Status" }],
        letters, { search: false, export: false, onRow: (l) => { m.close(); location.hash = "#/ca/letters?id=" + l.id; } }) : h("p", { class: "hint" }, "No letter in the Correspondence register is linked to this event yet."),
        h("div", { class: "bar" }, kinds.map(([k, l]) => h("button", { class: "btn small", onclick: () => showLetter(k, ev) }, l)), h("button", { class: "btn small", onclick: () => printClaim(ev) }, "Print claim report"))),
      panel("Files, comments and history", recordPanel("cr_claims", ev.id, { project_id: st.pid })),
      !st.ro ? panel("Remove", h("p", { class: "hint" }, ev.origin === "cr" ? "Stops following this claim. The event is deleted too unless a letter, variation or file points to it." : "Stops following this event as a claim. The event itself stays in Events & claims."),
        h("button", { class: "btn warn", onclick: async () => {
          if (!(await ask("Stop following this claim", "The claim timeline, evidence, records and quantum entered here are removed.", { danger: true, ok: "Remove" }))) return;
          const x = await run("cr.claim_delete", { event_id: ev.id }, "Removed from the claims register"); m.close(); await reload(); redraw();
          if (!x.event_removed && ev.origin === "cr") toast("The event stays in Events & claims because something points to it.", "ok");
        } }, "Remove from register")) : null);
  }

  function showLetter(kind, ev) {
    const p = st.p; const text = letterText(kind, p, ev);
    const ta = h("textarea", { rows: 22, style: "width:100%;font:13px ui-monospace,Consolas,monospace" }, text);
    const subj = { notice: "Notice: " + (ev.title || ""), claim: "Detailed claim: " + (ev.title || ""), nod: "Notice of Dissatisfaction: " + (ev.title || ""), arb: "Notice of dispute: " + (ev.title || "") }[kind];
    modal(subj, h("div", {}, h("p", { class: "hint" }, "Edit the draft, then save it in the Correspondence register (it gets the next outgoing number and is linked to this event), copy it, or print it. Record the date it was sent on the claim timeline."), ta), [
      { label: "Copy", keep: true, act: async () => { try { await navigator.clipboard.writeText(ta.value); toast("Copied", "ok"); } catch (e) { ta.select(); document.execCommand("copy"); toast("Copied", "ok"); } } },
      { label: "Print", keep: true, act: () => printFrame(subj, h("pre", {}, ta.value)) },
      !st.ro ? { label: "Save in Correspondence register", cls: "primary", act: async () => {
        const r = await run("ca.letter_save", { row: { project_id: st.pid, direction: "out", subject: subj.slice(0, 200), category: kind === "claim" ? "claim" : "notice", clause: (ev.refs || []).join("; "),
          body: ta.value, event_id: ev.id, to_name: bookOf(p).admin + (p.adminName ? " — " + p.adminName : ""), date: todayISO() } }, (x) => "Saved as " + (x.our_no || "a draft letter"));
        if (kind === "notice" && !ev.noticeRef && r && r.our_no) { ev.noticeRef = r.our_no; await saveEv(ev); }
        if (kind === "claim" && !ev.detailedRef && r && r.our_no) { ev.detailedRef = r.our_no; await saveEv(ev); }
        await reload(); redraw();
      } } : null]);
  }

  function printClaim(ev) {
    const p = st.p, b = bookOf(p); const steps = buildSteps(p, ev, st.evs); const sg = strength(p, ev, steps);
    const node = h("div", {}, h("h1", {}, (ev.no ? ev.no + " " : "") + (ev.title || "")),
      h("div", { class: "meta" }, [["Contract", (p.name || "") + " " + (p.contractNo || "")], ["Conditions", bookLabel(p.book)], ["Category", (CATS[ev.cat] || {}).n || ""], ["Status", eventStatus(ev, b)],
        ["Occurred", fmt(ev.occurred)], ["Aware", fmt(ev.aware)], ["EOT claimed / granted", (ev.eotClaimed ?? "—") + " / " + (ev.eotGranted ?? "—") + " d"],
        ["Cost claimed / agreed", money(num(ev.costClaimed), p.currency) + " / " + money(num(ev.costGranted), p.currency)], ["Strength", sg.score + "/100"]].map(([k, v]) => h("div", {}, h("b", {}, k + ": "), v))),
      h("h2", {}, "Clauses"), h("p", {}, (ev.refs || []).map((r) => r + " " + ((clauseByRef(p, r) || {}).t || "")).join("; ") || "—"),
      h("h2", {}, "Facts"), h("pre", {}, ev.desc || "—"), h("h2", {}, "Causation"), h("pre", {}, ev.causation || "—"), h("h2", {}, "Mitigation"), h("pre", {}, ev.mitigation || "—"),
      h("h2", {}, "Claim timeline"), h("table", {}, h("tr", {}, h("th", {}, "Step"), h("th", {}, "Clause"), h("th", {}, "Due"), h("th", {}, "Done"), h("th", {}, "Status")),
        steps.map((s) => h("tr", {}, h("td", {}, s.label), h("td", {}, s.refText), h("td", {}, fmt(s.due)), h("td", {}, fmt(s.done)), h("td", {}, stepStatusText(s, b))))),
      h("h2", {}, "Records"), h("table", {}, h("tr", {}, h("th", {}, "Date"), h("th", {}, "Type"), h("th", {}, "What it shows"), h("th", {}, "Ref.")),
        (ev.records || []).map((r) => h("tr", {}, h("td", {}, fmt(r.date)), h("td", {}, r.type || ""), h("td", {}, r.desc || ""), h("td", {}, r.ref || "")))),
      sg.gaps.length ? [h("h2", {}, "Gaps"), h("ul", {}, sg.gaps.map((g) => h("li", {}, g)))] : null);
    printFrame("Claim report", node);
  }

  /* ───────── Payments ───────── */
  const allPayments = () => [...(st.d.ipcs || []), ...(st.p.payments || [])];
  function viewPayments() {
    const p = st.p, b = bookOf(p), P = periodsOf(p);
    const pv = (k) => b.periods.find((x) => x.k === k);
    const terms = [b.pay.certify ? `certificate within ${P.certify} days of the Statement (${(pv("certify") || {}).r})` : null, `payment within ${P.pay} days ${b.pay.payBase === "certified" ? "of certification" : "of the Statement"} (${(pv("pay") || {}).r})`,
      P.terminatePay ? `termination right ${P.terminatePay} days after ${b.pay.termBase === "certified" ? "certification" : "the due date"} if still unpaid (${(pv("terminatePay") || {}).r})` : null].filter(Boolean);
    const rows = payRows(p, allPayments());
    p.payments = p.payments || [];
    const P2 = (r, k, type) => r.fromBuildcore ? (type === "date" ? fmt(r[k]) : fmtMoney(r[k])) : inp(p.payments.find((x) => x.id === r.id), k, { id: "pay-" + r.id + "-" + k, type });
    return h("div", {},
      h("p", { class: "hint" }, "Each interim statement against the contract's payment clock. IPCs submitted in BuildCore billing appear by themselves; add statements kept outside BuildCore by hand. Late payment is a claim in its own right and can justify suspension."),
      h("div", { class: "panel" }, h("b", {}, bookLabel(p.book) + ": "), terms.join("; ") + ". Edit the periods under Contract & conditions.",
        h("div", { class: "grid", style: "margin-top:8px" }, inp(p, "financeRate", { type: "number", label: "Financing rate for late payment (% a year)", ph: "e.g. 9.5", hint: "FIDIC: 3 points above the central bank discount rate, compounded monthly. This gives a simple-interest estimate." }))),
      table([{ label: "No.", v: (r) => r.fromBuildcore ? h("a", { href: "#/fc/ipc" }, r.no) : inp(p.payments.find((x) => x.id === r.id), "no", { id: "pay-" + r.id + "-no" }) },
        { label: "Statement received", v: (r) => P2(r, "statement", "date") }, { label: "Amount", v: (r) => P2(r, "amount", "number") },
        b.pay.certify ? { label: "Certified", v: (r) => h("div", {}, P2(r, "certified", "date"), h("div", { class: "hint" }, "by " + fmt(r.certDue))) } : null,
        { label: "Certified amount", v: (r) => P2(r, "certAmount", "number") }, { label: "Paid", v: (r) => P2(r, "paid", "date") },
        { label: "Pay by", v: (r) => fmt(r.payDue) },
        { label: "Status", v: (r) => h("div", {}, badge(r.st, r.stText), r.st === "over" && r.termFrom && todayISO() >= r.termFrom ? h("div", { class: "red hint" }, "Termination right may be open") : null) },
        { label: "Financing est.", fmt: "money", v: (r) => r.fin || null },
        { label: "", v: (r) => h("span", {}, ["over", "late", "cert-over"].includes(r.st) && !st.ro ? h("button", { class: "btn small", onclick: () => newEvent({ title: `Late payment: ${r.no || "statement"}`, aware: r.payDue || todayISO(), refs: activeClauses(p).filter((c) => c.c === "payment").slice(0, 1).map((c) => c.r), extra: { cat: "payment", payRef: r.id } }) }, "Log claim") : null,
          !r.fromBuildcore && !st.ro ? h("button", { class: "btn small", onclick: async () => { p.payments = p.payments.filter((x) => x.id !== r.id); await saveP(); redraw(); } }, "Delete") : null) }].filter(Boolean),
      rows, { search: false, export: false, empty: "No statements yet. Submit IPCs in billing, or add statements here." }),
      !st.ro ? h("button", { class: "btn", onclick: async () => { p.payments.push({ id: uid(), no: String(p.payments.length + 1), statement: todayISO() }); await saveP(); redraw(); } }, "Add statement kept outside BuildCore") : null);
  }

  /* ───────── Timeline ───────── */
  function viewTimeline() {
    const p = st.p, today = todayISO();
    const evs = st.evs.slice().sort((a, c) => (a.occurred || a.aware || "").localeCompare(c.occurred || c.aware || ""));
    const oc = originalCompletion(p), cc = currentCompletion(p, st.evs);
    const rows = evs.map((e) => { const s = buildSteps(p, e, st.evs); return { e, nx: nextStep(s), n: s.find((x) => x.id === "notice"), s0: e.occurred || e.aware, end: e.endEffects || (e.continuing && !isClosed(e) ? today : null) }; });
    const ds = [p.commencement, oc, cc, today];
    rows.forEach((r) => ds.push(r.s0, r.end, r.e.notice, r.e.detailed, r.nx && r.nx.due));
    const dates = ds.filter(isISO).sort();
    if (dates.length < 2 && !evs.length) return h("div", {}, contractHead(p), h("p", { class: "hint" }, "Enter the Commencement Date and log claim events to see them on the timeline."));
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const start = dates[0].slice(0, 8) + "01";
    const [ey, em] = dates[dates.length - 1].split("-").map(Number);
    const end = new Date(Date.UTC(ey, em + 1, 0)).toISOString().slice(0, 10);
    const total = Math.max(30, diff(end, start)); const months = Math.round(total / 30.44);
    const LW = 250, pxDay = Math.max(0.9, Math.min(8, 980 / total)), CW = Math.round(total * pxDay);
    const W = LW + CW + 24, RH = 30, top = 44, H = top + RH * (rows.length + 1) + 22;
    const X = (d) => LW + Math.round(diff(d, start) * pxDay);
    let ticks = "", d = start, i = 0;
    while (d <= end && i < 600) {
      const x = X(d); const [yy, mm] = d.split("-").map(Number);
      ticks += `<line class="grid" x1="${x}" y1="${top - 6}" x2="${x}" y2="${H - 18}"/>` + ((months <= 18 || mm % 3 === 1) ? `<text class="ax" x="${x + 3}" y="${top - 12}">${MON[mm - 1]}${mm === 1 || i === 0 ? " " + yy : ""}</text>` : "");
      d = new Date(Date.UTC(yy, mm, 1)).toISOString().slice(0, 10); i++;
    }
    let contract = `<rect class="rowbg" x="0" y="${top}" width="${W}" height="${RH}"/><text x="10" y="${top + 19}" font-weight="600">Contract period</text>`;
    if (isISO(p.commencement) && oc) {
      contract += `<rect class="orig" x="${X(p.commencement)}" y="${top + 8}" width="${Math.max(2, X(oc) - X(p.commencement))}" height="14" rx="2"><title>${fmt(p.commencement)} to ${fmt(oc)}, original Time for Completion</title></rect>`;
      if (cc && cc > oc) contract += `<rect class="ext" x="${X(oc)}" y="${top + 8}" width="${Math.max(2, X(cc) - X(oc))}" height="14" rx="2"><title>Extension of time to ${fmt(cc)}</title></rect>`;
      if (today > (cc || oc)) contract += `<rect class="over" x="${X(cc || oc)}" y="${top + 8}" width="${Math.max(2, X(today) - X(cc || oc))}" height="14" rx="2" opacity=".55"><title>Past the completion date</title></rect>`;
    }
    const body = rows.map((r, idx) => {
      const y = top + RH * (idx + 1);
      const risk = r.n && (r.n.st === "barred" || (r.n.st === "over" && r.n.bar));
      const cls = isClosed(r.e) ? "closed" : risk ? "risk" : "";
      const x0 = isISO(r.s0) ? X(r.s0) : null; const x1 = isISO(r.end) ? X(r.end) : (x0 != null ? x0 + 4 : null);
      const title = r.e.title || "Untitled event"; const short = title.length > 34 ? title.slice(0, 33) + "…" : title;
      let g = `<g class="ev" data-id="${r.e.id}"><rect class="${idx % 2 ? "rowbg" : ""}" x="0" y="${y}" width="${W}" height="${RH}" ${idx % 2 ? "" : 'fill="transparent"'}/><text x="10" y="${y + 19}">${esc(short)}</text>`;
      if (x0 != null) g += `<rect class="bar ${cls}" x="${x0}" y="${y + 9}" width="${Math.max(4, x1 - x0)}" height="12" rx="2"><title>${esc(title)}: ${fmt(r.s0)}${r.end ? " to " + fmt(r.end) : ""}</title></rect>`;
      if (isISO(r.e.notice)) { const x = X(r.e.notice); const ok = r.n && r.n.st === "done"; g += `<path class="${ok ? "mk-ok" : "mk-late"}" d="M${x} ${y + 6} l6 9 l-6 9 l-6 -9 z"><title>Notice ${fmt(r.e.notice)}${ok ? "" : " (late)"}</title></path>`; }
      if (isISO(r.e.detailed)) g += `<circle class="mk-det" cx="${X(r.e.detailed)}" cy="${y + 15}" r="5"><title>Detailed claim ${fmt(r.e.detailed)}</title></circle>`;
      if (r.nx && isISO(r.nx.due)) { const x = X(r.nx.due); g += `<path class="mk-due" d="M${x - 6} ${y + 2} h12 l-6 8 z"><title>Next: ${esc(r.nx.label)} by ${fmt(r.nx.due)}</title></path>`; }
      return g + "</g>";
    }).join("");
    const tx = X(today);
    const wrap = svgNode(`<svg class="crtl" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${ticks}${contract}${body}<line class="today" x1="${tx}" y1="${top - 6}" x2="${tx}" y2="${H - 18}"/><text class="ax" x="${tx + 4}" y="${H - 6}" style="fill:var(--red)">Today</text></svg>`);
    wrap.addEventListener("click", (e) => { const g = e.target.closest("g.ev"); if (g) openEvent(Number(g.dataset.id)); });
    return h("div", {}, contractHead(p), h("p", { class: "hint" }, "The contract period with extensions, and each claim event from when it occurred to the end of its effect, with notices and the next deadline. Click an event to open it."),
      wrap, h("p", { class: "hint" }, "Blue: original period, open event · Amber: extension of time · Red: time-bar risk or overrun · Green: closed event · ◆ notice · ○ detailed claim · ▼ next deadline"));
  }

  /* ───────── Start-up ───────── */
  function suStatusText(s) {
    switch (s.st) {
      case "over": return s.who === "c" ? `${plural(-s.daysLeft, "day")} overdue` : `${plural(-s.daysLeft, "day")} late`;
      case "soon": case "up": return `${plural(s.daysLeft, "day")} left`;
      case "done": return s.done ? `Done ${fmt(s.done)}` : "Passed";
      case "late": return `Done ${fmt(s.done)}, ${plural(diff(s.done, s.due), "day")} late`;
      case "info": return s.due ? fmt(s.due) : "Needs the dates above";
      case "open": return "No fixed date";
      case "wait": return "Needs the dates above";
    }
    return "";
  }
  function viewStartup() {
    const p = st.p, b = bookOf(p), f = famOf(p.book), steps = suSteps(p);
    p.su = p.su || {}; p.sp = p.sp || {}; p.td = p.td || {};
    const D = (k, l) => inp(p, k, { type: "date", label: l });
    const doneCount = SU_PRACTICE.filter(([k]) => p.sp[k]).length;
    return h("div", {}, contractHead(p),
      h("p", { class: "hint" }, "Deadlines that run from the Letter of Acceptance and the Commencement Date under " + bookLabel(p.book) + ", and the records to set up before the first claim event."),
      p.stage === "tender" ? h("div", { class: "panel" }, "This contract is still at the tender stage. Use Contract awarded on Tender review when you receive the Letter of Acceptance.")
        : !isISO(p.loa) ? h("div", { class: "panel" }, "Enter the Letter of Acceptance date to put these deadlines on the Overview radar. For a contract already well under way, record the dates each step was done, or leave this page as a reference.") : null,
      panel("Key dates", h("div", { class: "grid" }, f === "ppmo" ? inp(p.td, "loi", { id: "td-loi", type: "date", label: "Notice of intent to award" }) : null,
        D("loa", f === "ppmo" ? "Acceptance notice (Letter of Acceptance)" : "Letter of Acceptance received"), f !== "ppmo" && f !== "green" ? D("n81", "Notice of Commencement received (8.1)") : null,
        D("commencement", f === "ppmo" ? "Start Date" : "Commencement Date"), D("accessDate", f === "ppmo" ? "Site Possession Date (SCC)" : "Site access date (Contract Data)"),
        steps.some((s) => s.base === "dabDate") ? D("dabDate", "DAB appointment date (Appendix)") : null, f === "ppmo" ? D("advDate", "First advance received") : null)),
      panel("Start-up deadlines", steps.map((s) => h("div", { class: "crstep st-" + s.st }, h("span", { class: "mk" }),
        h("div", {}, h("div", { class: "hd" }, s.label, h("span", { class: "hint" }, "  " + (s.ref || "")), s.v === 0 ? verify() : null),
          h("div", { class: "meta" }, s.due && s.kind !== "info" ? h("span", {}, "Due " + fmt(s.due)) : null, badge(s.st === "over" && s.who !== "c" ? "info" : s.st, suStatusText(s)),
            h("span", { class: "hint" }, s.who === "c" ? "You" : s.who === "a" ? b.admin : s.who === "emp" ? "Employer" : "Either party")), s.n ? h("div", { class: "note" }, s.n) : null),
        s.kind === "info" ? h("span") : h("div", { class: "ins" }, inp(p.su, s.id, { id: "su-" + s.id, type: "date" }))))),
      panel("Set up your records (" + doneCount + " of " + SU_PRACTICE.length + ")", h("p", { class: "hint" }, "Claims are won on records made at the time. Set these up before work starts."),
        SU_PRACTICE.map(([k, t]) => h("div", {}, inp(p.sp, k, { id: "sp-" + k, type: "check", label: t })))));
  }

  /* ───────── Tender review, negotiation and award ───────── */
  const RVL = { ok: "Acceptable", watch: "Watch", risk: "Red flag", na: "Not applicable", none: "Not checked" };
  function tdBadge(x) {
    const left = diff(x.d, todayISO());
    if (x.kind === "info") return badge(left < 0 ? "idle" : "up", left < 0 ? "passed" : left === 0 ? "today" : `in ${left} d`);
    return badge(left < 0 ? "idle" : left <= 3 ? "over" : left <= 7 ? "soon" : "up", left < 0 ? "passed" : left === 0 ? "today" : `${left} d left`);
  }
  function negFromRv(p, it) { return { id: uid(), rv: it.id, ref: rvRef(p, it), issue: rvTenderText(p, it) ? `${it.t}: ${rvTenderText(p, it)}` : it.t, ask: it.ask, kind: routeOf(p) === "public" ? "clar" : "amend", status: "draft" }; }
  function viewTender() {
    const p = st.p, f = famOf(p.book), items = rvItems(p), c = rvCounts(p);
    p.rv = p.rv || {}; p.td = p.td || {}; p.neg = p.neg || [];
    const negOpen = p.neg.filter((n) => !["agreed", "partial", "rejected", "withdrawn"].includes(n.status)).length;
    const route = routeOf(p);
    const pbWarn = f === "ppmo" && isISO(p.td.prebid) && isISO(p.td.deadline) && diff(p.td.deadline, p.td.prebid) < 10;
    const T = (k, l, type) => inp(p.td, k, { id: "td-" + k, type: type || "date", label: l, ph: type === "number" ? "e.g. 90" : null });
    const row = (it) => {
      const r = p.rv[it.id] = p.rv[it.id] || {}; const s = rvStatus(p, it) || "none"; const auto = rvAuto(p, it);
      const inNeg = p.neg.some((n) => n.rv === it.id);
      return h("div", { class: "crrv st-" + s },
        h("div", {}, h("div", {}, h("b", {}, it.t + " "), chip(rvRef(p, it)), (it.v0 || []).includes(f) ? verify() : null, it.gp && f !== "ppmo" ? h("span", { class: "crent", title: "FIDIC Golden Principle " + it.gp + ": " + GOLDEN[it.gp - 1] }, "GP" + it.gp) : null),
          h("p", { class: "gc" }, "General Conditions: " + rvGc(p, it)), it.epc && EPC.includes(p.book) ? h("p", { class: "gc", style: "color:#8a5a00" }, it.epc) : null,
          s === "risk" || s === "watch" ? h("p", { class: "ask" }, h("b", {}, "Position to take: "), it.ask) : null,
          inp(r, "pc", { id: "rv-" + it.id + "-pc", ph: "What this tender says: clause and wording" })),
        h("div", {}, it.type === "num" ? inp(r, "v", { id: "rv-" + it.id + "-v", type: "number", label: "In this tender (" + it.unit + ")" })
          : inp(r, "v", { id: "rv-" + it.id + "-v", type: "select", label: "In this tender", blank: "Not checked yet", options: it.opts.map((x) => [x[0], x[1]]) }),
          h("div", { class: "bar" }, badge(s, RVL[s]), inp(r, "s", { id: "rv-" + it.id + "-s", type: "select", blank: auto ? `Auto (${RVL[auto]})` : "Auto", options: ["ok", "watch", "risk", "na"].map((k) => [k, RVL[k]]) })),
          (s === "risk" || s === "watch") ? (inNeg ? h("span", { class: "hint" }, "In the negotiation log") : !st.ro ? h("button", { class: "btn small", onclick: async () => { p.neg.push(negFromRv(p, it)); await saveP(); redraw(); toast("Added to negotiation", "ok"); } }, "Add to negotiation") : null) : null));
    };
    return h("div", {}, contractHead(p),
      h("div", { class: "bar" }, h("p", { class: "hint grow" }, "Check each term in the tender or draft contract against the " + bookLabel(p.book) + " General Conditions. Red flags move risk to you: for each, decide whether to accept it, price it, ask for clarification or negotiate."),
        !st.ro ? h("button", { class: "btn", onclick: async () => { let n = 0; for (const it of items) if (rvStatus(p, it) === "risk" && !p.neg.some((x) => x.rv === it.id)) { p.neg.push(negFromRv(p, it)); n++; } await saveP(); redraw(); toast(n ? n + " red flags added to negotiation" : "No new red flags to add", "ok"); } }, "Add red flags to negotiation") : null,
        p.stage === "tender" && !st.ro ? h("button", { class: "btn primary", onclick: showAward }, "Contract awarded") : null),
      clock([["Checked", c.done + "/" + c.total, "terms reviewed"], ["Red flags", c.risk, "shift risk to you", c.risk ? "bad" : ""], ["Watch", c.watch, "price or clarify", c.watch ? "warn" : ""], ["Negotiation", negOpen, "open points"]]),
      h("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px" },
        panel("Tender dates", h("div", { class: "grid" }, T("prebid", "Pre-bid meeting"), T("clarify", "Clarification requests close"), T("deadline", "Bid submission deadline"), T("validity", "Bid validity (days)", "number"), f === "ppmo" ? T("loi", "Notice of intent to award") : null),
          pbWarn ? h("p", { class: "red hint" }, "PPR r.52 expects the pre-bid meeting at least 10 days before the deadline (15 for international bids).") : null,
          tenderDates(p).map((x) => h("div", { style: "margin:4px 0" }, fmt(x.d) + " · " + x.l + " ", h("span", { class: "hint" }, x.ref + " "), tdBadge(x), x.n ? h("div", { class: "hint" }, x.n) : null))),
        panel("How terms can change", inp({ route: route }, "route", { type: "select", label: "Procurement route", blank: false, options: Object.entries(ROUTE).map(([k, v]) => [k, v.l]), after: (x) => { p.route = x; }, id: "pf-route" }),
          h("p", {}, ROUTE[route].n),
          f !== "ppmo" ? h("details", {}, h("summary", {}, "FIDIC Golden Principles for Particular Conditions"), h("ol", {}, GOLDEN.map((g) => h("li", {}, g))), h("p", { class: "hint" }, "FIDIC published these in 2019 and recommends them to anyone drafting Particular Conditions. Tags like GP3 mark terms where an amendment would cut across one. Use them as arguments in negotiation; they are not contract terms.")) : null)),
      RV_GROUPS.map(([g, gl]) => { const its = items.filter((i) => i.g === g); return its.length ? panel(gl, its.map(row)) : null; }),
      h("p", { class: "hint" }, "Thresholds behind the automatic flags are common market practice, not rules. Override any assessment with the selector beside it. Not legal advice."));
  }
  function viewNeg() {
    const p = st.p, route = routeOf(p); p.neg = p.neg || []; const list = p.neg;
    const cnt = (s) => list.filter((n) => (n.status || "draft") === s).length;
    return h("div", {}, contractHead(p),
      h("div", { class: "bar" }, h("p", { class: "hint grow" }, "Each point you raise before signing: what the tender says, what you asked for and what the Employer answered. An agreed change only counts once it is in an addendum or the signed Particular Conditions."),
        h("button", { class: "btn", disabled: !list.length, onclick: () => { const t = negLetter(p); const ta = h("textarea", { rows: 22, style: "width:100%;font:13px ui-monospace,Consolas,monospace" }, t);
          modal(route === "public" ? "Clarification request" : "Amendment schedule", ta, [{ label: "Copy", keep: true, act: async () => { try { await navigator.clipboard.writeText(ta.value); } catch (e) { ta.select(); document.execCommand("copy"); } toast("Copied", "ok"); } }, { label: "Print", keep: true, act: () => printFrame("Negotiation", h("pre", {}, ta.value)) }]); } },
          route === "public" ? "Draft clarification request" : "Draft amendment schedule"),
        !st.ro ? h("button", { class: "btn primary", onclick: async () => { list.push({ id: uid(), kind: route === "public" ? "clar" : "amend", status: "draft" }); await saveP(); redraw(); } }, "Add point") : null),
      h("div", { class: "panel" }, h("b", {}, ROUTE[route].l + ". "), ROUTE[route].n),
      list.length ? h("div", { class: "chips" }, NEG_ST.filter(([k]) => cnt(k)).map(([k, l]) => h("span", { class: "chip" }, l, h("i", {}, cnt(k))))) : null,
      list.length ? list.map((n) => panel(null, h("div", { class: "grid" }, inp(n, "ref", { id: "neg-" + n.id + "-ref", label: "Clause" }), inp(n, "kind", { id: "neg-" + n.id + "-kind", type: "select", label: "Kind", blank: false, options: NEG_KIND }),
        inp(n, "status", { id: "neg-" + n.id + "-status", type: "select", label: "Status", blank: false, options: NEG_ST }), inp(n, "sent", { id: "neg-" + n.id + "-sent", type: "date", label: "Sent" }),
        inp(n, "issue", { id: "neg-" + n.id + "-issue", type: "textarea", label: "Issue in the tender", wide: true, rows: 2 }), inp(n, "ask", { id: "neg-" + n.id + "-ask", type: "textarea", label: "What we ask for", wide: true, rows: 2 }),
        inp(n, "reply", { id: "neg-" + n.id + "-reply", label: "Employer’s answer, addendum or minutes ref.", wide: true })),
        n.kind === "dev" && route === "public" ? h("p", { class: "red hint" }, "A deviation attached to a public bid can make it non-responsive. Raise it as a clarification before the deadline instead.") : null,
        !st.ro ? h("button", { class: "btn small", onclick: async () => { p.neg = p.neg.filter((x) => x !== n); await saveP(); redraw(); } }, "Remove") : null))
        : h("p", { class: "hint" }, "No points yet. Flag terms in Tender review and add them here with one click, or add your own points."));
  }
  function showAward() {
    const p = st.p, f = famOf(p.book);
    const maps = rvItems(p).filter((it) => it.map && (p.rv || {})[it.id] && p.rv[it.id].v != null && p.rv[it.id].v !== "");
    const v = { loa: p.loa || todayISO(), comm: p.commencement || "", tfc: ((p.rv || {}).tfc || {}).v ?? p.tfcDays ?? "", price: p.price ?? "", apply: 1 };
    const fm = form([{ k: "loa", label: f === "ppmo" ? "Acceptance notice date" : "Letter of Acceptance received", type: "date" }, { k: "comm", label: (f === "ppmo" ? "Start Date" : "Commencement Date") + " (if known)", type: "date" },
      { k: "tfc", label: "Time for Completion (days)", type: "number" }, { k: "price", label: "Accepted Contract Amount", type: "number" },
      maps.length ? { k: "apply", label: "Copy agreed terms into Contract & conditions: " + maps.map((it) => it.t + ": " + rvTenderText(Object.assign({}, p, { rv: { [it.id]: { v: p.rv[it.id].v } } }), it)).join(" · "), type: "check", wide: true } : null].filter(Boolean), v);
    modal("Contract awarded", h("div", {}, h("p", { class: "hint" }, "Moves this contract to execution and starts the start-up deadlines. If negotiation changed any term, update its value in Tender review first so the agreed figure is copied."), fm), [{ label: "Start execution", cls: "primary", act: async () => {
      const x = fm.values();
      p.stage = "execution";
      if (isISO(x.loa)) p.loa = x.loa; if (isISO(x.comm)) p.commencement = x.comm;
      if (num(x.tfc) != null) p.tfcDays = num(x.tfc); if (num(x.price) != null) p.price = num(x.price);
      if (Number(x.apply)) {
        const P0 = {}; bookOf(p).periods.forEach((y) => { P0[y.k] = y.d; });
        for (const it of rvItems(p)) {
          const val = ((p.rv || {})[it.id] || {}).v; if (!it.map || val == null || val === "" || it.map === "tfcDays") continue;
          if (it.map.startsWith("po.")) { const k = it.map.slice(3); p.po = p.po || {}; if (+val === P0[k]) delete p.po[k]; else p.po[k] = +val; } else p[it.map] = +val;
        }
      }
      if (!p.baseDate && famOf(p.book) !== "ppmo" && isISO((p.td || {}).deadline)) p.baseDate = addDays(p.td.deadline, -28);
      await run("cr.contract_save", { project_id: st.pid, data: p }, "Moved to execution. Start-up deadlines are running.");
      goTab("startup");
    } }]);
  }

  /* ───────── Contract & conditions ───────── */
  function viewContract() {
    const p = st.p, b = bookOf(p);
    p.po = p.po || {}; p.bo = p.bo || {}; p.ce = p.ce || {}; p.cc = p.cc || [];
    const F = (k, l, type, extra) => inp(p, k, Object.assign({ id: "pf-" + k, type, label: l }, extra || {}));
    const book = h("select", { id: "pf-book", disabled: st.ro }, BOOK_GROUPS.map(([g, ids]) => h("optgroup", { label: g }, ids.map((id) => h("option", { value: id, selected: id === p.book }, bookLabel(id) + " · " + BOOKS[id].title)))));
    book.onchange = async () => {
      if (!(await ask("Change the form of contract", "Periods, time bars and clause edits that belong to the old form stop applying; every claim's deadlines are worked out again under " + bookLabel(book.value) + ".", { ok: "Change" }))) { book.value = p.book; return; }
      p.book = book.value; p.po = {}; p.bo = {}; p.ce = {}; if (BOOKS[p.book].fam === "ppmo") p.ppa = true;
      await run("cr.contract_save", { project_id: st.pid, data: p, audit: 1 }, "Form changed"); await reload(); redraw();
    };
    const cl = clausesOf(p);
    const clEdit = (c) => c.custom ? p.cc.find((x) => x.id === c.id) : (p.ce[c.key] = p.ce[c.key] || {});
    const clInp = (c, k, extra) => { const tgt = clEdit(c); if (!(k in tgt) && !c.custom) tgt[k] = c[k]; return inp(tgt, k, Object.assign({ id: "cl-" + String(c.key).replace(/[^\w]/g, "_") + "-" + k }, extra || {})); };
    return h("div", {},
      h("p", { class: "hint" }, "Contract Data and the Particular or Special Conditions drive every deadline in the register. Change a period here and all events recalculate."),
      panel("Contract Data", h("div", { class: "grid" }, F("name", "Contract name"), F("contractNo", "Contract no."), F("employer", "Employer"), F("contractor", "Contractor"), F("adminName", b.admin + " (name)"),
        F("location", "Project location"), F("baseDate", "Base Date", "date"), F("commencement", "Commencement Date", "date"), F("tfcDays", "Time for Completion (days)", "number", { min: 0 }),
        F("price", "Accepted Contract Amount", "number", { min: 0 }), F("currency", "Currency"), F("dnpDays", "Defects Notification / Liability period (days)", "number", { min: 0 }),
        F("ldPct", "Delay damages (% of price per day)", "number", { ph: "0.05" }), F("ldCapPct", "Delay damages cap (%)", "number", { ph: "10" })),
        h("p", { class: "hint" }, "Original completion: ", h("b", {}, fmt(originalCompletion(p))), ". Current completion with granted EOT: ", h("b", {}, fmt(currentCompletion(p, st.evs))), ".")),
      panel("Form of contract", h("div", { class: "grid" }, h("label", { class: "f wide" }, h("span", {}, "Conditions of contract"), book, h("small", { class: "fhint" }, b.use)),
        F("stage", "Stage", "select", { blank: false, options: [["tender", "Before award (tender and negotiation)"], ["execution", "After award (execution)"]] }),
        F("ppa", "Nepal Public Procurement Act 2063 applies (variation-authority, price-adjustment and LD checks)", "check")),
        h("p", { class: "hint" }, "Administrator: " + b.admin + " · Claims: " + b.claimRef + " · Determination: " + b.detRef + " · Disputes: " + b.board)),
      panel("Particular / Special Conditions: time periods", h("p", { class: "hint" }, "Enter your contract's figure where it differs from the general conditions. Tick time bar where missing the period loses the entitlement under your contract."),
        table([{ label: "Period", v: (x) => h("div", {}, h("b", {}, tpl(x.l, b)), x.n ? h("div", { class: "hint" }, x.n) : null, x.tool ? h("div", { class: "hint" }, "Tool reminder, not a contract period.") : null) },
          { label: "Clause", v: (x) => h("span", {}, x.r, x.v === 0 ? verify() : null) }, { label: "General", v: (x) => x.d + " d" },
          { label: "Your contract", v: (x) => inp(p.po, x.k, { id: "po-" + x.k, type: "number", ph: String(x.d), min: 0 }) }, { label: "Counted", v: (x) => tpl(x.f || "", b) },
          { label: "Time bar", v: (x) => { const el = h("input", { type: "checkbox", id: "bo-" + x.k, checked: barOf(p, x.k), disabled: st.ro }); el.onchange = async () => { p.bo[x.k] = el.checked; await saveP(); redraw(); }; return el; } }],
        b.periods, { search: false, export: false })),
      panel("Claim clauses in this contract", h("p", { class: "hint" }, "Untick a clause your Particular Conditions delete. Change its number, wording or entitlement to match your contract. Added clauses appear when you log events."),
        table([{ label: "Use", v: (c) => { const el = h("input", { type: "checkbox", id: "cl-" + String(c.key).replace(/[^\w]/g, "_") + "-use", checked: !c.off, disabled: st.ro }); el.onchange = async () => { clEdit(c).off = !el.checked; await saveP(); redraw(); }; return el; } },
          { label: "Clause", v: (c) => h("div", {}, clInp(c, "r"), c.v === 0 ? verify() : null) },
          { label: "Event", v: (c) => h("div", {}, clInp(c, "t"), clInp(c, "n", { type: "textarea", rows: 2 })) },
          { label: "Category", v: (c) => clInp(c, "c", { type: "select", blank: false, options: Object.entries(CATS).map(([k, v]) => [k, v.n]) }) },
          { label: "Entitlement", v: (c) => h("div", {}, ["T", "C", "P"].map((t) => { const el = h("input", { type: "checkbox", checked: String(c.e).includes(t), disabled: st.ro, id: "cl-" + String(c.key).replace(/[^\w]/g, "_") + "-e" + t });
              el.onchange = async () => { const tgt = clEdit(c); let e = String(c.e || "").replace(t, ""); if (el.checked) e = "TCP".split("").filter((y) => y === t || e.includes(y)).join("") + e.replace(/[TCP]/g, ""); tgt.e = e; await saveP(); redraw(); };
              return h("label", { style: "display:block;font-size:12px" }, el, " " + ENT[t]); }), ents(String(c.e || "").replace(/[TCP]/g, ""))) },
          { label: "", v: (c) => st.ro ? "" : c.custom ? h("button", { class: "btn small", onclick: async () => { p.cc = p.cc.filter((x) => x.id !== c.id); await saveP(); redraw(); } }, "Remove")
              : p.ce[c.key] && Object.keys(p.ce[c.key]).some((k) => p.ce[c.key][k] !== c[k] && !(k === "off" && !p.ce[c.key][k])) ? h("button", { class: "btn small", onclick: async () => { delete p.ce[c.key]; await saveP(); redraw(); } }, "Reset") : "" }],
        cl, { search: cl.length > 8, export: false, empty: "No clauses yet. Add the claim clauses from your contract." }),
        !st.ro ? h("button", { class: "btn small", onclick: async () => { p.cc.push({ id: uid(), r: "PC ", t: "New clause", c: "delay", e: "TC", n: "" }); await saveP(); redraw(); } }, "Add clause from Particular Conditions") : null),
      panel("Securities and guarantees", h("p", { class: "hint" }, "Kept in Commercial › Bonds, guarantees & insurance, so expiries also reach My work. Those expiring within 60 days show on the Overview."),
        st.d.securities.length ? table([{ k: "kind", label: "Type" }, { k: "number", label: "Number" }, { k: "issuer", label: "Issuer" }, { k: "amount", label: "Amount", fmt: "money" }, { label: "Expiry", v: (x) => fmt(x.expiry_date) }, { k: "status", label: "Status" }],
          st.d.securities, { search: false, export: false, onRow: () => { location.hash = "#/ca/securities"; } }) : h("p", { class: "hint" }, "None recorded for this project."),
        h("a", { class: "btn small", href: "#/ca/securities" }, "Open bonds, guarantees & insurance")),
      panel("Particular Conditions notes", inp(p, "pcNotes", { type: "textarea", rows: 5, id: "pf-pcNotes", ph: "Summarise amendments that matter for claims: deleted time bars, changed periods, extra Employer risks, caps on delay damages, governing law, arbitration seat and rules." })));
  }

  /* ───────── Clause library ───────── */
  function viewLibrary() {
    const id = st.libBook || (st.p && st.p.book) || "red17";
    const b = BOOKS[id]; const P = {}; b.periods.forEach((x) => { P[x.k] = x.d; });
    const proc = (PROC[b.proc] || PROC.p99).filter((s) => s.kind !== "info" && !s.onlyIfLate && !s.onlyCat && !s.cont);
    const byCat = {}; b.clauses.forEach((c) => (byCat[c.c] = byCat[c.c] || []).push(c));
    const pp = { book: id, ppa: b.fam === "ppmo" }; const its = rvItems(pp); const f = famOf(id);
    const base = { loa: famOf(id) === "ppmo" ? "the acceptance notice" : "the Letter of Acceptance", commence: "the Commencement / Start Date", n81: "the Notice of Commencement", accessDate: "the access date in the contract", dabDate: "the date in the Appendix", advDate: "the first advance", loi: "the notice of intent", month1: "the end of the first full month" };
    const catRows = []; Object.keys(CATS).filter((c) => byCat[c]).forEach((c) => { catRows.push({ _g: CATS[c].n }); byCat[c].forEach((x) => catRows.push(x)); });
    const rvRows = []; RV_GROUPS.forEach(([g, gl]) => { const gi = its.filter((i) => i.g === g); if (gi.length) { rvRows.push({ _g: gl }); gi.forEach((x) => rvRows.push(x)); } });
    const G = (fn) => (r) => r._g ? h("b", { class: "hint", style: "text-transform:uppercase" }, r._g) : fn(r);
    return h("div", {},
      h("p", { class: "hint" }, "For each form: the claims timeline, claim clauses and entitlements, the terms to check before signing, and the start-up deadlines after award. Entries marked check come from secondary sources or have numbering that varies between versions; confirm them in your copy."),
      h("div", { class: "chips" }, Object.keys(BOOKS).map((k) => h("span", { class: "chip" + (k === id ? " on" : ""), onclick: () => { st.libBook = k; redraw(); } }, bookLabel(k)))),
      panel(bookLabel(id) + " · " + b.title, h("p", { class: "hint" }, b.use), h("p", {}, "Administrator: ", h("b", {}, b.admin), " · Claims: " + b.claimRef + " · Determination: " + b.detRef + " · Disputes: ", h("b", {}, b.board)),
        h("h3", {}, "Claim timeline"),
        h("div", { class: "crflow" }, proc.map((s) => { const days = s.k ? s.k.reduce((a, k) => a + (P[k] || 0), 0) : null; const refs = s.k ? [...new Set(s.k.map((k) => (b.periods.find((x) => x.k === k) || {}).r).filter(Boolean))].join(", ") : "";
          return h("div", { class: "node" + (s.bar && (b.periods.find((x) => x.k === s.bar) || {}).bar ? " bar" : "") + (s.disp ? " disp" : "") },
            h("div", { class: "who" }, s.who === "c" ? "You" : s.who === "a" ? b.admin : s.who === "b" ? b.board : "Either party"), h("div", {}, tpl(s.l, b)),
            h("div", { class: "hint" }, days != null ? `${s.kind === "earliest" ? "after " : ""}+${days} d ${s.base === "aware" ? "from awareness" : ""}` : "no fixed limit", s.cap ? ` · ≥${P[s.cap]} d before completion` : ""), refs ? h("div", { class: "hint" }, refs) : null); })),
        h("p", { class: "hint" }, "Red edge: time bar in the general conditions. Dashed: only if you dispute the outcome."),
        h("h3", {}, "Periods"),
        table([{ label: "Period", v: (x) => h("div", {}, tpl(x.l, b), x.bar ? h("span", { class: "crtb" }, "Time bar") : null, x.n ? h("div", { class: "hint" }, x.n) : null) }, { label: "Clause", v: (x) => h("span", {}, x.r, x.v === 0 ? verify() : null) },
          { k: "d", label: "Days", fmt: "num" }, { label: "Counted", v: (x) => tpl(x.f || "", b) }], b.periods, { search: false, export: false }),
        h("h3", {}, "Claim clauses"),
        b.clauses.length ? table([{ label: "Clause", v: G((x) => h("span", {}, x.r, x.v === 0 ? verify() : null)) }, { label: "Event", v: (x) => x._g ? "" : h("div", {}, h("b", {}, x.t), h("div", { class: "hint" }, x.n)) },
          { label: "Entitlement", v: (x) => x._g ? "" : ents(x.e) }], catRows, { search: false, export: false }) : h("p", { class: "hint" }, "Add clauses for this form under Contract & conditions."),
        h("h3", {}, "Terms to check before you bid or sign"),
        table([{ label: "Term", v: G((it) => h("span", {}, h("b", {}, it.t), it.gp && f !== "ppmo" ? h("span", { class: "crent", title: GOLDEN[it.gp - 1] }, "GP" + it.gp) : null)) },
          { label: "Clause", v: (it) => it._g ? "" : h("span", {}, rvRef(pp, it), (it.v0 || []).includes(f) ? verify() : null) },
          { label: "General Conditions", v: (it) => it._g ? "" : h("div", {}, rvGc(pp, it), it.epc && EPC.includes(id) ? h("div", { style: "color:#8a5a00" }, it.epc) : null) },
          { label: "Position if the tender changes it", v: (it) => it._g ? "" : it.ask }], rvRows, { search: false, export: false }),
        h("h3", {}, "Start-up deadlines after award"),
        table([{ label: "Step", v: (s) => h("div", {}, h("b", {}, s.l), s.n ? h("div", { class: "hint" }, s.n) : null) }, { label: "Clause", v: (s) => h("span", {}, s.ref, s.v === 0 ? verify() : null) },
          { label: "Deadline", v: (s) => s.base ? `${s.d ? s.d + " days after " : "On or before "}${base[s.base] || ""}` : "No fixed date" }],
        (SU[id === "ppmo_sq" ? "ppmo_sq" : famOf(id)] || []).filter((s) => (!s.design || DESIGN.includes(id)) && (!s.only || s.only.includes(id))), { search: false, export: false })),
      b.fam === "ppmo" || (st.p && st.p.ppa) ? panel("Nepal Public Procurement Act 2063 and Regulations 2064", h("p", { class: "hint" }, "Statutory rules that sit over every PPMO contract. The Act was amended by the Second Amendment Act 2083 and the Regulations by the Fifteenth Amendment 2083; confirm the current text before relying on a figure."),
        kv(PPA_LAW)) : null,
      panel("Sources", h("ul", {}, SOURCES.map(([t, u]) => h("li", {}, t, h("span", { class: "hint" }, " · " + u)))), h("p", { class: "hint" }, "FIDIC conditions are copyright documents; this library paraphrases them. Use your licensed copy for the exact wording.")));
  }

  /* ───────── All contracts ───────── */
  async function portfolioTab() {
    const root = st.root;
    const d = await api("cr.portfolio", {});
    const today = todayISO();
    const dl = [];
    const rows = d.contracts.map((x) => {
      const p = x.contract || {}; const evs = x.claims; const b = bookOf(p); const mine = [];
      if (p.stage === "tender") { for (const t of tenderDates(p)) { const left = diff(t.d, today); if (t.kind === "act" && left >= 0) mine.push({ title: t.l, label: "Tender", due: t.d, left, st: left <= 7 ? "soon" : "up", ours: true, go: "tender" }); } }
      else {
        for (const e of evs) { if (isClosed(e)) continue; const nx = nextStep(buildSteps(p, e, evs)); if (nx && nx.due) mine.push({ title: (e.no ? e.no + " " : "") + (e.title || "Untitled event"), label: nx.label, ref: nx.refText, due: nx.due, left: nx.daysLeft, st: nx.st, ours: nx.who !== "a" && nx.who !== "b", bar: nx.bar, go: "events", ev: e.id }); }
        if (isISO(p.loa)) for (const s of suSteps(p)) if (!s.done && ["over", "soon", "up"].includes(s.st)) mine.push({ title: s.label, label: "Start-up", ref: s.ref, due: s.due, left: s.daysLeft, st: s.st, ours: s.who === "c", go: "startup" });
      }
      for (const l of x.open_letters) { const left = diff(l.reply_by, today); mine.push({ title: l.subject, label: l.direction === "in" ? "Reply to letter" : b.admin + "’s answer due", ref: l.our_no, due: l.reply_by, left, st: left < 0 ? "over" : left <= 7 ? "soon" : "up", ours: l.direction === "in", href: "#/ca/letters?id=" + l.id }); }
      for (const s of x.securities) if (isISO(s.expiry_date)) { const left = diff(s.expiry_date, today); if (left <= 60) mine.push({ title: (s.kind || "Security") + " expires", label: s.number || "Renew or extend", due: s.expiry_date, left, st: left < 0 ? "over" : left <= 30 ? "soon" : "up", ours: true, href: "#/ca/securities" }); }
      mine.forEach((m) => { m.pid = x.project.id; m.contract = x.project.code; dl.push(m); });
      mine.sort((a, c) => a.due < c.due ? -1 : 1);
      const sum = (k) => evs.reduce((a, e) => a + (+e[k] || 0), 0);
      return { pid: x.project.id, code: x.project.code, name: p.name || x.project.name, book: bookLabel(p.book), no: p.contractNo || "", stage: p.stage, cur: p.currency || "NPR",
               open: evs.filter((e) => !isClosed(e)).length, total: evs.length, next: mine.find((m) => m.left >= 0) || null, over: mine.filter((m) => m.st === "over" && m.ours).length,
               cc: sum("costClaimed"), cg: sum("costGranted"), tc: sum("eotClaimed"), tg: sum("eotGranted"), flags: p.stage === "tender" ? rvCounts(p).risk : 0, comp: p.stage === "tender" ? null : currentCompletion(p, evs) };
    });
    dl.sort((a, c) => a.due < c.due ? -1 : a.due > c.due ? 1 : 0);
    const soon = dl.filter((x) => x.st === "over" || x.left <= 30).slice(0, 30);
    const curs = [...new Set(rows.map((r) => r.cur))]; const one = curs.length === 1 ? curs[0] : null;
    const tsum = (k) => rows.reduce((a, r) => a + r[k], 0);
    const overAll = dl.filter((x) => x.st === "over" && x.ours).length;
    const open = (x) => { if (x.href) { if (String(S.project) !== String(x.pid)) setProject(x.pid, true); location.hash = x.href; return; }
      setProject(x.pid, true); location.hash = "#/cr?tab=" + (x.go || "overview") + (x.ev ? "&ev=" + x.ev : ""); };
    root.innerHTML = "";
    root.append(pageHead("Claims register", "All contracts: open claims, the next deadline and anything overdue, across the projects you can open",
      S.project ? h("button", { class: "btn", onclick: () => { location.hash = "#/cr?tab=overview"; } }, "Back to this project") : null));
    if (!S.project) root.append(h("p", { class: "hint" }, "Choose a project in the bar at the top to set up its contract and log claim events. Below are the contracts already set up."));
    root.append(clock([["Contracts", rows.length, rows.filter((r) => r.stage === "tender").length + " at tender stage"], ["Open claims", tsum("open"), tsum("total") + " logged"],
        ["Your overdue actions", overAll, "across all contracts", overAll ? "bad" : ""], ["Claimed", one ? money(tsum("cc"), one) : "Mixed currencies", one ? money(tsum("cg"), one) + " agreed" : ""]]),
      table([{ label: "Contract", v: (r) => h("div", {}, h("b", {}, r.code + " · " + r.name), h("div", { class: "hint" }, r.book + (r.no ? " · " + r.no : ""))) },
        { label: "Stage", v: (r) => r.stage === "tender" ? h("div", {}, badge("soon", "Tender"), r.flags ? h("div", { class: "red hint" }, plural(r.flags, "red flag")) : null) : badge("done", "Execution") },
        { label: "Open claims", k: "open", fmt: "num" }, { label: "Next deadline", v: (r) => r.next ? h("div", {}, r.next.title, h("div", { class: "hint" }, fmt(r.next.due) + " · " + r.next.label)) : "—" },
        { label: "Your overdue", v: (r) => r.over ? h("b", { class: "red" }, r.over) : "—" }, { label: "Claimed", v: (r) => h("div", {}, money(r.cc, r.cur), h("div", { class: "hint" }, r.tc + " days")) },
        { label: "Agreed", v: (r) => h("div", {}, money(r.cg, r.cur), h("div", { class: "hint" }, r.tg + " days")) }, { label: "Completion", v: (r) => r.comp ? fmt(r.comp) : "—" }],
      rows, { name: "claims_contracts", title: "Claims register, all contracts", onRow: (r) => { setProject(r.pid, true); location.hash = "#/cr?tab=overview"; }, empty: "No contract set up yet. Choose a project and open the Claims register to set one up." }),
      panel("Deadlines across all contracts", soon.length ? h("div", { class: "crradar" }, soon.map((x) => h("div", { class: "it", onclick: () => open(x) }, h("span", {}, fmt(x.due)),
        h("div", {}, h("div", { class: "t" }, x.title), h("div", { class: "s" }, [x.contract, x.label, x.ref, x.bar ? "Time bar" : ""].filter(Boolean).join(" · "))),
        x.st === "over" ? badge(x.ours ? "over" : "other", x.ours ? `${-x.left} d overdue` : `${-x.left} d late`) : badge(x.st === "soon" ? "soon" : "up", x.left === 0 ? "today" : `${x.left} d left`))))
        : h("p", { class: "hint" }, "Nothing due in the next 30 days.")));
  }

  /* What's new */
  const VER = "2.34.0";
  const seenGet = () => { try { return localStorage.getItem("bco_seen_" + VER); } catch (e) { return "1"; } };
  function whatsNew() {
    if (seenGet()) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    const lib = can("project", "view"), cr = can("commercial", "view");
    if (!lib && !cr) return;
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        lib ? h("li", {}, h("b", {}, "Document library "), "(Work, after Transmittals). Every file in BuildCore in one list, found by any word: title, number, tags, project, or the words inside PDFs, Word, Excel and e-mails. Add a whole folder at once; categories and revisions are detected from the names and duplicates are skipped.") : null,
        cr ? h("li", {}, h("b", {}, "Claims register "), "(Commercial, after Notices & time bars). Set up the project's contract under its own conditions (FIDIC 1999/2017, MDB, PPMO) and log claim events: notice, detailed claim, determination and dispute dates with time-bar warnings, evidence, records, quantum, letters, payments against the contract clock, start-up, tender review and negotiation.") : null),
      h("p", { class: "hint" }, "Claim events are your existing Events & claims; letters go to the Correspondence register. Nothing is posted and no balance changes.")),
    [lib ? { label: "Open the library", act: () => { location.hash = "#/dl"; } } : null, cr ? { label: "Open the claims register", cls: "primary", act: () => { location.hash = "#/cr"; } } : null], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 10500); } }, 900);

  const VIEWS = { overview: viewOverview, events: viewEvents, payments: viewPayments, timeline: viewTimeline, startup: viewStartup, tender: viewTender, neg: viewNeg,
                  contract: viewContract, library: viewLibrary, portfolio: () => h("div") };
})();
