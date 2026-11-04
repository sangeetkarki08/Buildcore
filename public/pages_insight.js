/* BuildCore 2.18 — one dashboard that tells you where to act.
   The old Overview had fifteen screens and a dashboard of counters. 2.18 puts the figures a director or
   project manager decides on into one screen, in the way Procore, Autodesk Construction Cloud and
   Primavera present a portfolio:
     · five headline figures with their trend (backlog, forecast profit, cash, overdue receipts, SPI / CPI)
     · "Decisions this week": what to act on, ranked by urgency and by the money at stake, each with its fix
     · portfolio health: every project placed by time (SPI) and cost (CPI), sized by contract value
     · twelve-month cash outlook against the minimum balance
     · a 5 x 5 risk heat map from the new risk register
     · one compact project table, and a one-page printable report.
   The Dashboard menu is cut to the screens people use every day; the rest move to "Tools & views".
   The previous dashboard stays as "Classic dashboard".
   2.48: "Needs attention" instead of "Decisions this week": repeated lines grouped with a count (they open to show each
   one), calm labels (Important / This week / Review / For info) instead of "ACT NOW", contract notices only for the
   employer's or neutral events, a "This month" panel (site, money, supply, machines, approvals, one row per project)
   and "To complete your figures" in place of bare "Not available". Server flag d.glance.on = off gives the 2.47 view. */
(function () {
  "use strict";
  const VER = "2.18.0";
  const LS = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSset = (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* ignore */ } };
  const NS = "http://www.w3.org/2000/svg";
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  const svgEl = (w, hgt, inner, cls) => { const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", "0 0 " + w + " " + hgt); s.setAttribute("class", cls || ""); s.innerHTML = inner; return s; };

  /* NPR in the way people say it: 4.52 Cr, 12.5 lakh */
  const money = (x, plain) => {
    if (x == null || x === "" || isNaN(x)) return "—";
    const v = Number(x), a = Math.abs(v), sg = v < 0 ? "−" : "";
    if (a >= 1e7) return sg + (a / 1e7).toFixed(a >= 1e9 ? 0 : 2) + " Cr";
    if (a >= 1e5) return sg + (a / 1e5).toFixed(1) + " lakh";
    return sg + Math.round(a).toLocaleString("en-IN") + (plain ? "" : "");
  };
  const ratio = (x) => (x == null ? "—" : Number(x).toFixed(2));
  const pct = (x, d) => (x == null ? "—" : Number(x).toFixed(d == null ? 1 : d) + "%");
  const lvl = (x, good, warn) => (x == null ? "" : x >= good ? "ok" : x >= warn ? "attention" : "critical");

  const ICON = {
    cash: '<path d="M3 7h18v10H3z"/><circle cx="12" cy="12" r="2.5"/><path d="M6 10v4M18 10v4"/>',
    cost: '<path d="M4 19h16"/><path d="M6 15l4-4 3 3 5-6"/><path d="M15 8h3v3"/>',
    time: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    contract: '<path d="M6 3h9l3 3v15H6z"/><path d="M9 12l2 2 4-4"/>',
    supply: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
    equipment: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
    risk: '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
    print: '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
  };
  const ico = (k) => { const s = svgEl(24, 24, ICON[k] || ICON.risk, "ins-ico"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.8"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round"); return s; };
  const KIND = { cash: "Cash", cost: "Cost", time: "Time", contract: "Contract", supply: "Supply", equipment: "Equipment", risk: "Risk" };
  const SEV_218 = { critical: "Act now", high: "This week", medium: "Soon", info: "FYI" };
  const SEV_248 = { critical: "Important", high: "This week", medium: "Review", info: "For info" };
  let SEV = SEV_218, GL = false;

  /* ───────────────────────── styles ───────────────────────── */
  const css = document.createElement("style");
  css.id = "bco-ui-218";
  css.textContent = `
.ins{--ok:var(--green,#2f855a);--warn:var(--amber,#b7791f);--bad:var(--red,#c53030);display:flex;flex-direction:column;gap:16px}
.ins-head{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap}.ins-head .grow{flex:1;min-width:220px}.ins-head h1{margin:0}
.ins-head .sub{margin:3px 0 0;color:var(--muted)}.ins-head .btn svg{width:16px;height:16px;vertical-align:-3px;margin-right:4px}
.ins-scope{display:inline-flex;gap:2px;background:var(--line-soft,rgba(0,0,0,.05));border-radius:999px;padding:3px}
.ins-scope button{border:0;background:none;padding:5px 12px;border-radius:999px;cursor:pointer;color:var(--muted);font:inherit;font-size:13px}
.ins-scope button.on{background:var(--panel);color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.12);font-weight:600}
.ins-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}
.ins-kpi{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-lg,14px);padding:14px 16px 12px;cursor:pointer;position:relative;overflow:hidden;box-shadow:var(--shadow);transition:transform .12s,box-shadow .12s}
.ins-kpi:hover{transform:translateY(-1px);box-shadow:var(--shadow-lg,0 10px 24px rgba(0,0,0,.1))}
.ins-kpi .lb{font-size:12.5px;color:var(--muted);display:flex;justify-content:space-between;align-items:flex-start;gap:6px;flex-wrap:wrap}
.ins-kpi .v{font-size:25px;font-weight:700;letter-spacing:-.01em;margin:4px 0 2px;white-space:nowrap;font-variant-numeric:tabular-nums;display:flex;align-items:baseline;gap:4px}.ins-kpi .v .sp{margin-left:auto;align-self:center;display:flex}
.ins-kpi .v small{font-size:13px;font-weight:600;color:var(--muted);margin-left:4px}
.ins-kpi .s{font-size:12.5px;color:var(--muted);min-height:17px}
.ins-kpi .spark{width:70px;height:26px;opacity:.9}
.ins-kpi.ok .v{color:var(--ink)}.ins-kpi.attention{box-shadow:inset 0 3px 0 var(--warn),var(--shadow)}.ins-kpi.critical{box-shadow:inset 0 3px 0 var(--bad),var(--shadow)}
.ins-kpi .v.neg{color:var(--bad)}
.ins-tag{font-size:11px;font-weight:700;padding:1px 7px;border-radius:999px;white-space:nowrap}
.ins-tag.ok{background:rgba(47,133,90,.12);color:var(--ok)}.ins-tag.attention{background:rgba(183,121,31,.14);color:var(--warn)}.ins-tag.critical{background:rgba(197,48,48,.12);color:var(--bad)}
.ins-grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);gap:16px}
.ins-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-lg,14px);padding:16px 18px;box-shadow:var(--shadow);min-width:0}
.ins-card h2{font-size:15.5px;margin:0;display:flex;align-items:center;gap:8px}.ins-card h2 .n{font-size:12px;color:var(--muted);font-weight:500}
.ins-card .hd{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}.ins-card .hd .grow{flex:1}
.ins-card .hd a{font-size:13px;text-decoration:none}
.ins-chips{display:flex;gap:6px;flex-wrap:wrap}.ins-chips button{border:1px solid var(--line);background:none;border-radius:999px;padding:2px 10px;font:inherit;font-size:12px;color:var(--muted);cursor:pointer}
.ins-chips button.on{border-color:var(--acc);color:var(--acc);background:rgba(var(--acc-rgb),.08);font-weight:600}
.ins-dec{list-style:none;margin:0;padding:0}
.ins-dec li{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:4px 12px;align-items:center;padding:10px 4px;border-top:1px solid var(--line-soft,var(--line));cursor:pointer;border-radius:8px}
.ins-dec li:first-child{border-top:0}.ins-dec li:hover{background:var(--hover)}
.ins-dec .ic{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;grid-row:span 2}.ins-dec .ic svg{width:17px;height:17px}
.ins-dec .critical .ic{background:rgba(197,48,48,.12);color:var(--bad)}.ins-dec .high .ic{background:rgba(183,121,31,.14);color:var(--warn)}
.ins-dec .medium .ic,.ins-dec .info .ic{background:rgba(var(--acc-rgb),.1);color:var(--acc)}
.ins-dec b{font-weight:600;font-size:14px;overflow:hidden;text-overflow:ellipsis}.ins-dec .why{color:var(--muted);font-size:12.5px;line-height:1.4;grid-column:2}
.ins-dec .amt{text-align:right;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}.ins-dec .act{grid-column:3;justify-self:end;font-size:12px;color:var(--acc);white-space:nowrap}
.ins-dec .sev{font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;font-weight:700;margin-right:6px}
.ins-dec .critical .sev{color:var(--bad)}.ins-dec .high .sev{color:var(--warn)}.ins-dec .medium .sev{color:var(--acc)}
.ins-empty{padding:18px 6px;color:var(--muted);display:flex;gap:10px;align-items:center}.ins-empty .ok{width:28px;height:28px;border-radius:50%;background:rgba(47,133,90,.14);color:var(--ok);display:grid;place-items:center;font-weight:700}
.ins-more{border:0;background:none;color:var(--acc);font:inherit;font-size:13px;cursor:pointer;padding:8px 4px 0}
.ins-quad{width:100%;height:auto;display:block}.ins-quad text{font:11px system-ui,sans-serif;fill:var(--muted)}.ins-quad .ql{font-size:10.5px;font-weight:600;opacity:.8}
.ins-quad .ax{stroke:var(--line);stroke-width:1}.ins-quad .mid{stroke:var(--muted);stroke-dasharray:4 4;opacity:.6}
.ins-quad circle{cursor:pointer;stroke:var(--panel);stroke-width:2;transition:opacity .12s}.ins-quad circle:hover{opacity:.8}
.ins-quad .lab{fill:var(--ink);font-weight:600;font-size:11px;pointer-events:none}
.ins-cash{width:100%;height:auto;display:block}.ins-cash text{font:11px system-ui,sans-serif;fill:var(--muted)}
.ins-cash .g{stroke:var(--line);stroke-width:1}.ins-cash .min{stroke:var(--bad);stroke-dasharray:5 4;stroke-width:1.3}
.ins-heat{display:grid;grid-template-columns:18px repeat(5,minmax(0,1fr));gap:4px;max-width:260px;align-items:center;font-size:11px;color:var(--muted)}
.ins-heat .c{aspect-ratio:1.5;border-radius:6px;display:grid;place-items:center;font-weight:700;font-size:13px;color:#fff;cursor:pointer;min-height:26px}
.ins-heat .c.z{color:rgba(255,255,255,.0)}.ins-heat .c:hover{outline:2px solid var(--ink);outline-offset:-2px}
.ins-heat .yl{writing-mode:vertical-rl;transform:rotate(180deg);text-align:center;grid-row:1/6}.ins-heat .xl{grid-column:2/7;text-align:center}
.ins-rk{display:grid;grid-template-columns:minmax(150px,190px) minmax(0,1fr);gap:18px;align-items:start}@media (max-width:620px){.ins-rk{grid-template-columns:minmax(0,1fr)}}
.ins-risks{list-style:none;padding:0;margin:10px 0 0}.ins-risks li{display:flex;gap:8px;align-items:center;padding:6px 0;border-top:1px solid var(--line-soft,var(--line));font-size:13px;cursor:pointer}
.ins-risks .sc{min-width:26px;text-align:center;border-radius:6px;color:#fff;font-weight:700;font-size:12px;padding:1px 0}.ins-risks .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ins-risks .e{color:var(--muted);white-space:nowrap}
.ins-ptable{width:100%;border-collapse:collapse;font-size:13.5px}.ins-ptable th{text-align:left;font-weight:600;color:var(--muted);font-size:12px;padding:6px 8px;border-bottom:1px solid var(--line)}
.ins-ptable td{padding:9px 8px;border-bottom:1px solid var(--line-soft,var(--line));vertical-align:middle}.ins-ptable tr:last-child td{border-bottom:0}
.ins-ptable tbody tr{cursor:pointer}.ins-ptable tbody tr:hover td{background:var(--hover)}.ins-ptable .n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ins-ptable .pb{width:150px}.ins-ptable .pb small{white-space:nowrap}.ins-ptable .pb .pbar{margin:0}.ins-ptable .pb small{color:var(--muted);font-size:11.5px}
.ins-dots{display:inline-flex;gap:4px}.ins-dots i{width:10px;height:10px;border-radius:3px;display:inline-block;background:var(--ok)}.ins-dots i.attention{background:var(--warn)}.ins-dots i.critical{background:var(--bad)}
.ins-trend{font-size:11.5px;font-weight:700;margin-left:4px}.ins-trend.up{color:var(--ok)}.ins-trend.dn{color:var(--bad)}
.v-ok{color:var(--ok)}.v-attention{color:var(--warn)}.v-critical{color:var(--bad);font-weight:700}
.ins-views{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.ins-views span{color:var(--muted);font-size:13px;margin-right:4px}
.ins-views a{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:5px 13px;text-decoration:none;font-size:13px;color:var(--ink)}
.ins-views a:hover{border-color:var(--acc);color:var(--acc)}
.ins-note{font-size:12px;color:var(--muted)}
.ins-legend{display:flex;gap:14px;font-size:12px;color:var(--muted);margin-top:4px;flex-wrap:wrap}.ins-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.ins-welcome{text-align:center;padding:36px 20px}.ins-welcome h2{justify-content:center;font-size:19px}.ins-welcome p{color:var(--muted);max-width:520px;margin:8px auto 16px}
.ins-skel{height:96px;border-radius:14px;background:linear-gradient(90deg,var(--line-soft,rgba(0,0,0,.05)) 25%,var(--hover) 50%,var(--line-soft,rgba(0,0,0,.05)) 75%);background-size:400% 100%;animation:insk 1.4s infinite}
@keyframes insk{0%{background-position:100% 0}100%{background-position:0 0}}
.rk-top{display:grid;grid-template-columns:minmax(260px,340px) minmax(0,1fr);gap:16px;align-items:start;margin-bottom:14px}
.rk-sc{display:inline-block;min-width:28px;text-align:center;border-radius:6px;color:#fff;font-weight:700;font-size:12px;padding:1px 4px}
.rk-sug{display:flex;flex-direction:column;gap:8px}.rk-sug div{display:flex;gap:10px;align-items:center;border:1px dashed var(--line);border-radius:10px;padding:8px 12px}
.rk-sug div b{flex:1;font-weight:600}.rk-sug small{color:var(--muted)}
.ins.gl .ins-dec .sev{text-transform:none;letter-spacing:0;font-size:11px;font-weight:600;padding:1px 8px;border-radius:999px;margin-right:8px;vertical-align:1px}
.ins.gl .ins-dec .critical .sev{background:rgba(197,48,48,.10)}.ins.gl .ins-dec .high .sev{background:rgba(183,121,31,.12)}.ins.gl .ins-dec .medium .sev,.ins.gl .ins-dec .info .sev{background:rgba(var(--acc-rgb),.08);color:var(--acc)}
.ins.gl .ins-dec .medium .ic,.ins.gl .ins-dec .info .ic{background:var(--line-soft,rgba(127,127,127,.1));color:var(--muted)}
.ins-dec .cnt{display:inline-block;min-width:20px;text-align:center;font-size:11px;font-weight:700;border-radius:999px;background:var(--line-soft,rgba(127,127,127,.14));color:var(--ink);padding:0 6px;margin-left:6px;vertical-align:1px}
.ins-dec .subs{grid-column:2/4;list-style:none;margin:6px 0 2px;padding:0 0 0 2px;border-left:2px solid var(--line)}
.ins-dec .subs li{display:flex;gap:10px;grid-template-columns:none;padding:5px 10px;border-top:0;font-size:12.5px;align-items:baseline}.ins-dec .subs li b{font-size:12.5px;font-weight:600}
.ins-dec .subs li .why{flex:1;color:var(--muted)}
.ins-tag.info{background:rgba(var(--acc-rgb),.1);color:var(--acc)}
.ins-kpi .s a{color:var(--acc);text-decoration:none;font-weight:600;white-space:nowrap}
.gl-month .hd .ins-scope button{font-size:12.5px;padding:4px 11px}
.gl-groups{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.gl-g{border:1px solid var(--line-soft,var(--line));border-radius:12px;padding:12px 14px;min-width:0}
.gl-g h3{margin:0 0 8px;font-size:12.5px;font-weight:600;color:var(--muted);display:flex;gap:8px;align-items:center}.gl-g h3 a{margin-left:auto;font-weight:500;text-decoration:none;color:var(--acc)}
.gl-big{font-size:21px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.01em;line-height:1.15}.gl-big small{font-size:12px;color:var(--muted);font-weight:600;margin-left:4px}
.gl-cap{font-size:12px;color:var(--muted);margin:1px 0 8px}
.gl-rows{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 10px;font-size:13px}.gl-rows span:nth-child(odd){color:var(--muted)}.gl-rows span:nth-child(even){text-align:right;font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap}
.gl-rows .bad{color:var(--bad)}.gl-rows .warn{color:var(--warn)}
.gl-bar{display:flex;height:8px;border-radius:999px;overflow:hidden;background:var(--line-soft,rgba(127,127,127,.12));margin:6px 0 4px}.gl-bar i{display:block;height:100%}
.gl-legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:11.5px;color:var(--muted)}.gl-legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px}
.gl-note{font-size:12px;color:var(--muted);margin-top:8px}
.gl-ptable td.n,.gl-ptable th.n{text-align:right}.gl-ptable td:last-child{white-space:nowrap}.ins.gl .ins-dec .why{white-space:normal}
.gl-setup{list-style:none;margin:0;padding:0}.gl-setup li{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:2px 10px;align-items:start;padding:9px 2px;border-top:1px solid var(--line-soft,var(--line))}
.gl-setup li:first-child{border-top:0}.gl-setup .k{width:20px;height:20px;border-radius:50%;border:2px solid var(--line);margin-top:1px}.gl-setup b{font-weight:600;font-size:13.5px}
.gl-setup .w{grid-column:2;color:var(--muted);font-size:12.5px;line-height:1.4}.gl-setup a{grid-row:span 2;grid-column:3;font-size:12.5px;text-decoration:none;white-space:nowrap}
@media (max-width:1180px){.gl-groups{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:620px){.gl-groups{grid-template-columns:minmax(0,1fr)}.ins-dec .subs{grid-column:1/3}}
@media (max-width:1180px){.ins-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:900px){.ins-grid,.rk-top{grid-template-columns:minmax(0,1fr)}.ins-ptable .hide-s{display:none}}
@media (max-width:620px){.ins-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.ins-kpi .v{font-size:20px}.ins-kpi .v .sp{display:none}.ins-dec li{grid-template-columns:30px minmax(0,1fr)}.ins-dec .amt,.ins-dec .act{grid-column:2;justify-self:start;text-align:left}.ins-ptable .hide-m{display:none}}
@media print{.ins-head .btn,.ins-scope,.ins-chips,.ins-more,.ins-views{display:none!important}}
`;
  document.head.append(css);

  /* ───────────────────────── small charts ───────────────────────── */
  function spark(values, color) {
    const v = values.filter((x) => x != null);
    if (v.length < 2) return null;
    const W = 86, H = 28, mn = Math.min(...v), mx = Math.max(...v), rg = mx - mn || 1;
    const pts = v.map((x, i) => ((i / (v.length - 1)) * (W - 4) + 2).toFixed(1) + "," + (H - 3 - ((x - mn) / rg) * (H - 6)).toFixed(1)).join(" ");
    const s = svgEl(W, H, `<polyline points="${pts}" fill="none" stroke="${color || "var(--acc)"}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`, "spark");
    return s;
  }
  const heatColor = (p, i) => { const s = p * i; return s >= 15 ? "#c53030" : s >= 10 ? "#dd6b20" : s >= 5 ? "#d69e2e" : "#38a169"; };
  const heatTone = (p, i, n) => (n ? heatColor(p, i) : "rgba(127,127,127,.12)");

  /* SPI x CPI: the four quarters every project controls office knows */
  function quadrant(rows, onPick) {
    const pts = rows.filter((r) => r.spi != null && r.cpi != null);
    const W = 460, H = 300, L = 40, R = 14, T = 14, B = 34;
    const lo = 0.6, hi = 1.4;
    const cl = (v) => Math.max(lo, Math.min(hi, v));
    const x = (v) => L + ((cl(v) - lo) / (hi - lo)) * (W - L - R);
    const y = (v) => T + (1 - (cl(v) - lo) / (hi - lo)) * (H - T - B);
    const maxCv = Math.max(1, ...pts.map((r) => r.contract_value || 1));
    let s = `<rect x="${x(1)}" y="${T}" width="${W - R - x(1)}" height="${y(1) - T}" fill="rgba(56,161,105,.08)"/>`
      + `<rect x="${L}" y="${y(1)}" width="${x(1) - L}" height="${H - B - y(1)}" fill="rgba(197,48,48,.08)"/>`
      + `<line class="ax" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/><line class="ax" x1="${L}" x2="${L}" y1="${T}" y2="${H - B}"/>`
      + `<line class="mid" x1="${x(1)}" x2="${x(1)}" y1="${T}" y2="${H - B}"/><line class="mid" x1="${L}" x2="${W - R}" y1="${y(1)}" y2="${y(1)}"/>`;
    [0.6, 0.8, 1, 1.2, 1.4].forEach((t) => { s += `<text x="${x(t)}" y="${H - B + 15}" text-anchor="middle">${t.toFixed(1)}</text><text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${t.toFixed(1)}</text>`; });
    s += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">Time (SPI) →  ahead of programme</text>`
      + `<text transform="translate(11 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Cost (CPI) →  under budget</text>`
      + `<text class="ql" x="${W - R - 6}" y="${T + 14}" text-anchor="end" style="fill:var(--ok)">Ahead &amp; under budget</text>`
      + `<text class="ql" x="${L + 6}" y="${T + 14}" style="fill:var(--warn)">Late, under budget</text>`
      + `<text class="ql" x="${W - R - 6}" y="${H - B - 8}" text-anchor="end" style="fill:var(--warn)">Ahead, over budget</text>`
      + `<text class="ql" x="${L + 6}" y="${H - B - 8}" style="fill:var(--bad)">Late &amp; over budget</text>`;
    pts.forEach((r, i) => {
      const rad = 7 + 16 * Math.sqrt((r.contract_value || maxCv * 0.2) / maxCv);
      const bad = r.spi < 0.95 && r.cpi < 0.95, good = r.spi >= 1 && r.cpi >= 1;
      const col = bad ? "#c53030" : good ? "#2f855a" : "#d69e2e";
      s += `<circle data-i="${i}" cx="${x(r.spi)}" cy="${y(r.cpi)}" r="${rad.toFixed(1)}" fill="${col}" fill-opacity=".78"><title>${esc(r.code + " " + r.name)}\nSPI ${ratio(r.spi)} · CPI ${ratio(r.cpi)}${r.contract_value ? "\nContract " + money(r.contract_value) : ""}</title></circle>`
        + `<text class="lab" x="${x(r.spi)}" y="${y(r.cpi) - rad - 4}" text-anchor="middle">${esc(r.code)}</text>`;
    });
    const el = svgEl(W, H, s, "ins-quad");
    el.addEventListener("click", (e) => { const c = e.target.closest("circle"); if (c) onPick(pts[Number(c.dataset.i)]); });
    return { el, shown: pts.length, missing: rows.length - pts.length };
  }

  function cashChart(cash) {
    const rows = cash.rows || [];
    if (!rows.length) return null;
    const W = 560, H = 210, L = 58, R = 12, T = 12, B = 28;
    const vals = rows.map((r) => r.closing);
    const minb = cash.min_balance || 0;
    const mn = Math.min(0, minb, ...vals), mx = Math.max(minb, ...vals, cash.opening || 0);
    const rg = mx - mn || 1;
    const x = (i) => L + (i / Math.max(1, rows.length - 1)) * (W - L - R);
    const y = (v) => T + (1 - (v - mn) / rg) * (H - T - B);
    let s = "";
    for (let g = 0; g <= 4; g++) { const v = mn + (rg * g) / 4; s += `<line class="g" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${money(v)}</text>`; }
    const pts = vals.map((v, i) => x(i).toFixed(1) + "," + y(v).toFixed(1));
    s += `<defs><linearGradient id="insg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="rgb(var(--acc-rgb))" stop-opacity=".28"/><stop offset="1" stop-color="rgb(var(--acc-rgb))" stop-opacity="0"/></linearGradient></defs>`;
    s += `<polygon points="${x(0)},${y(mn)} ${pts.join(" ")} ${x(rows.length - 1)},${y(mn)}" fill="url(#insg)"/>`;
    s += `<polyline points="${pts.join(" ")}" fill="none" stroke="var(--acc)" stroke-width="2.4" stroke-linejoin="round"/>`;
    if (minb || mn < 0) s += `<line class="min" x1="${L}" x2="${W - R}" y1="${y(minb)}" y2="${y(minb)}"/><text x="${W - R}" y="${y(minb) - 5}" text-anchor="end" style="fill:var(--bad)">minimum ${money(minb)}</text>`;
    rows.forEach((r, i) => {
      const short = r.overdraft_needed > 0;
      s += `<circle cx="${x(i)}" cy="${y(r.closing)}" r="${short ? 4.5 : 3}" fill="${short ? "#c53030" : "var(--acc)"}"><title>${r.month}: closing ${money(r.closing)}${short ? " · short by " + money(r.overdraft_needed) : ""}</title></circle>`;
      if (i % 2 === 0 || i === rows.length - 1) s += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${monthName(r.month)}</text>`;
    });
    return svgEl(W, H, s, "ins-cash");
  }
  const MN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const monthName = (k) => { const m = Number(String(k).slice(5, 7)); return m ? MN[m - 1] + " " + String(k).slice(2, 4) : k; };

  function heatMap(heat, onCell) {
    const g = h("div", { class: "ins-heat" });
    g.append(h("div", { class: "yl" }, "Probability ↑"));
    for (let p = 5; p >= 1; p--) {
      for (let i = 1; i <= 5; i++) {
        const n = (heat[p - 1] || [])[i - 1] || 0;
        g.append(h("div", { class: "c" + (n ? "" : " z"), style: "background:" + heatTone(p, i, n), title: "Probability " + p + " × impact " + i + " = " + p * i + (n ? " · " + n + " risk(s)" : ""), onclick: () => onCell && onCell(p, i) }, n || "·"));
      }
    }
    g.append(h("div", {}), h("div", { class: "xl" }, "Impact →"));
    return g;
  }

  /* ───────────────────────── portfolio trend from the daily snapshots ───────────────────────── */
  function portfolioTrend(tr, rows) {
    const byDate = {};
    rows.forEach((r) => (tr[r.id] || []).forEach((s) => {
      const d = (byDate[s.date] = byDate[s.date] || { profit: 0, cpiW: 0, spiW: 0, w: 0, wS: 0 });
      const w = r.contract_value || 1;
      if (s.forecast_profit != null) d.profit += s.forecast_profit;
      if (s.cpi != null) { d.cpiW += s.cpi * w; d.w += w; }
      if (s.spi != null) { d.spiW += s.spi * w; d.wS += w; }
    }));
    const dates = Object.keys(byDate).sort();
    return { dates, profit: dates.map((d) => byDate[d].profit), cpi: dates.map((d) => (byDate[d].w ? byDate[d].cpiW / byDate[d].w : null)), spi: dates.map((d) => (byDate[d].wS ? byDate[d].spiW / byDate[d].wS : null)) };
  }
  /* change against the snapshot about a month ago (or the oldest one) */
  function delta(series) {
    const v = series.filter((x) => x != null);
    if (v.length < 2) return null;
    const back = v[Math.max(0, v.length - 31)];
    return v[v.length - 1] - back;
  }
  const trendTag = (d, fmt, goodUp) => {
    if (d == null || Math.abs(d) < 1e-9) return null;
    const up = d > 0, good = goodUp ? up : !up;
    return h("span", { class: "ins-trend " + (good ? "up" : "dn"), title: "Change over the last month" }, (up ? "▲ " : "▼ ") + fmt(Math.abs(d)));
  };

  /* ───────────────────────── the dashboard ───────────────────────── */
  const hello = () => { const hr = new Date().getHours(); return hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening"; };
  const goProject = (pid, hash) => { if (pid && typeof setProject === "function") setProject(pid, true); location.hash = hash; };
  const startHere = () => LS("bco_start_dash", "1") === "1";

  async function dashboard(root) {
    const first = ((S.user && S.user.name) || "").replace(/\(.*?\)/g, "").trim().split(/\s+/)[0] || "";
    const scope = S.project ? nm.project(S.project) : "All projects";
    const wrap = h("div", { class: "ins" });
    const head = h("div", { class: "ins-head" },
      h("div", { class: "grow" }, h("h1", {}, hello() + (first ? ", " + first : "")),
        h("p", { class: "sub" }, scope + " · " + new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }))),
      S.project ? h("div", { class: "ins-scope" }, h("button", { onclick: () => { setProject("", true); go(); } }, "All projects"), h("button", { class: "on" }, nm.pcode(S.project))) : null,
      h("button", { class: "btn", title: "One page for the board or the client meeting", onclick: () => printReport(DATA) }, ico("print"), "Print report"),
      h("a", { class: "btn", href: "#/home", title: "Every module and screen" }, "All modules"));
    wrap.append(head, h("div", { class: "ins-kpis" }, [1, 2, 3, 4, 5].map(() => h("div", { class: "ins-skel" }))));
    root.append(wrap);
    let d;
    try { d = await api("insight.overview", { project_id: S.project || null }); } catch (e) {
      wrap.lastChild.replaceWith(h("div", { class: "ins-card" }, h("b", { class: "red" }, "The dashboard could not load. "), e.message, " ", h("a", { href: "#/dashboard/classic" }, "Open the classic dashboard")));
      return;
    }
    DATA = d;
    GL = !!(d.glance && d.glance.on);
    SEV = GL ? SEV_248 : SEV_218;
    wrap.classList.toggle("gl", GL);
    if (typeof approvalsCount !== "undefined" && d.attention) { try { approvalsCount = d.attention.approval || 0; } catch (e) { /* ignore */ } }
    wrap.lastChild.remove();
    const K = d.kpis || {};
    const ok = (d.projects || []).filter((r) => !r.error);
    const tr = portfolioTrend(d.trends || {}, ok);

    if (!d.projects.length && !(d.decisions || []).length) {
      wrap.append(h("div", { class: "ins-card ins-welcome" }, h("h2", {}, "Your dashboard fills in as you work"),
        h("p", {}, "Add a project with its BOQ and programme, then enter DPRs, measurements and bills. BuildCore turns them into progress, cost, cash and the decisions you need to take."),
        can("project", "edit") ? h("a", { class: "btn primary", href: "#/m/projects" }, "Add a project") : null, " ",
        h("a", { class: "btn", href: "#/home" }, "See all modules")));
      wrap.append(viewsRow());
      return;
    }

    /* 1. headline figures */
    const kp = h("div", { class: "ins-kpis" });
    const card = (o) => {
      const c = h("div", { class: "ins-kpi " + (o.level || ""), onclick: () => { location.hash = o.href; }, title: o.title || "" },
        h("div", { class: "lb" }, h("span", {}, o.label), o.tag ? h("span", { class: "ins-tag " + (o.tagLevel || o.level) }, o.tag) : null),
        h("div", { class: "v" + (o.neg ? " neg" : "") }, o.value, o.unit ? h("small", {}, o.unit) : null, h("span", { class: "sp" }, (o.spark && spark(o.spark, o.sparkColor)) || null)),
        h("div", { class: "s" }, o.sub || "", o.trend ? " " : "", o.trend || null));
      kp.append(c);
    };
    if (K.contract_value != null) {
      const done = K.contract_value ? 100 * (K.earned || 0) / K.contract_value : 0;
      const mm = K.value_mismatch || [];
      if (GL) card({ label: "Work in hand", value: money(K.backlog), unit: "NPR", level: "", tag: mm.length ? "Check contract value" : null, tagLevel: "info",
        sub: [pct(done, 0) + " done of " + money(K.contract_value) + " · " + K.projects + " project" + (K.projects === 1 ? "" : "s"),
          mm.length ? h("div", {}, "BOQ adds up to " + money(K.boq_value) + (mm.length === 1 ? " on " + mm[0].code : "") + ". ", h("a", { href: "#/m/projects", onclick: (e) => e.stopPropagation() }, "Check ›")) : null],
        href: "#/command", title: "Contract value typed on each project less the work done. The forecast uses the BOQ: when the BOQ total and the contract value differ, correct one of them." });
      else card({ label: "Work in hand", value: money(K.backlog), unit: "NPR", level: mm.length ? "attention" : "", tag: mm.length ? "BOQ ≠ contract" : null,
        sub: pct(done, 0) + " of " + money(K.contract_value) + " done · " + K.projects + " project" + (K.projects === 1 ? "" : "s") +
          (mm.length ? " · BOQ total " + money(K.boq_value) + "; contract value differs on " + mm.map((x) => x.code + " (BOQ " + money(x.boq) + ", contract " + money(x.contract_value) + ")").join(", ") : ""),
        href: "#/command", title: "Contract value typed on each project less the work done. The BOQ is what the forecast uses: when the two differ, correct the project's contract value or the BOQ." });
    } else card({ label: "Active projects", value: String(K.projects || 0), sub: "", href: "#/p/control" });
    if (K.forecast_profit != null) {
      const lv = K.forecast_profit < 0 ? "critical" : (K.forecast_margin != null && K.forecast_margin < 5 ? "attention" : "ok");
      const noCost = K.revenue_without_cost || 0, none = noCost > 0 && !(K.revenue_costed > 0);
      if (GL && none) card({ label: "Forecast profit", value: "—", level: "", tag: "Needs cost estimates", tagLevel: "info",
        sub: h("div", {}, "No BOQ item has a cost estimate yet, so profit cannot be worked out. ", h("a", { href: "#/cl/budget", onclick: (e) => e.stopPropagation() }, "Add the control budget ›")),
        href: "#/cl/budget", title: "Forecast profit needs a cost for each BOQ item: a control budget, a rate analysis or cost booked to it." });
      else if (GL && noCost > 0) card({ label: "Forecast profit", value: money(K.forecast_profit), unit: "NPR", level: lv === "critical" ? "critical" : "", neg: K.forecast_profit < 0,
        tag: K.forecast_margin != null ? pct(K.forecast_margin) + " margin (part)" : null,
        sub: h("div", {}, "On " + money(K.revenue_costed) + " of BOQ with cost estimates; " + money(noCost) + " still has none. ", h("a", { href: "#/cl/budget", onclick: (e) => e.stopPropagation() }, "Add ›")),
        trend: trendTag(delta(tr.profit), money, true), spark: tr.profit, href: "#/p/evm" });
      else card({ label: "Forecast profit", value: none ? "Not available" : money(K.forecast_profit), unit: none ? "" : "NPR", level: none ? "attention" : noCost > 0 && lv === "ok" ? "attention" : lv, neg: K.forecast_profit < 0,
        tag: K.forecast_margin != null ? pct(K.forecast_margin) + " margin" + (noCost > 0 ? " (part)" : "") : (noCost > 0 ? "No cost estimates" : null),
        sub: noCost > 0 ? money(noCost) + " of BOQ has no cost estimate yet and is not counted (add the control budget or rate analysis)" : "", trend: trendTag(delta(tr.profit), money, true), spark: tr.profit, sparkColor: lv === "critical" ? "#c53030" : "var(--acc)", href: "#/p/evm", title: "Forecast profit at completion: revenue at completion less the forecast cost (EAC) of every active project" });
    }
    if (K.cash != null) {
      const lv = K.cash_shortfall ? "critical" : "ok";
      card({ label: "Cash today", value: money(K.cash), unit: "NPR", level: lv, tag: K.cash_shortfall ? "Short in " + monthName(K.cash_shortfall) : null,
        sub: K.cash_lowest ? "Lowest " + money(K.cash_lowest.balance) + " in " + monthName(K.cash_lowest.month) : "", spark: d.cash ? d.cash.rows.map((r) => r.closing) : null, href: "#/acc/cash" });
    }
    if (K.receivable_overdue != null) {
      const lv = K.receivable_overdue > 0.5 * (K.receivable || 0) && K.receivable_overdue > 0 ? "critical" : K.receivable_overdue > 0 ? "attention" : "ok";
      card({ label: "Client money overdue", value: money(K.receivable_overdue), unit: "NPR", level: lv, sub: "of " + money(K.receivable) + " receivable" + (K.unbilled ? " · " + money(K.unbilled) + " not yet billed" : ""), href: "#/acc/ageing" });
    } else if (K.unbilled != null) card({ label: "Measured, not billed", value: money(K.unbilled), unit: "NPR", level: K.unbilled > 0 ? "attention" : "ok", sub: "Put it in the next IPC", href: "#/p/ipc" });
    card({ label: "SPI · CPI", value: ratio(K.spi) + " · " + ratio(K.cpi), level: [lvl(K.spi, 0.95, 0.85), lvl(K.cpi, 0.95, 0.85)].includes("critical") ? "critical" : [lvl(K.spi, 0.95, 0.85), lvl(K.cpi, 0.95, 0.85)].includes("attention") ? "attention" : (K.spi == null && K.cpi == null ? "" : "ok"),
      sub: K.spi == null && K.cpi == null ? (GL ? h("div", {}, "Shows once projects have a programme with dates (time) and a cost budget (cost). ", h("a", { href: "#/p/schedule", onclick: (e) => e.stopPropagation() }, "Programme ›")) : "Needs a programme and BOQ budget") : "1.00 = on plan; below 0.95 needs action", trend: trendTag(delta(tr.cpi), (x) => x.toFixed(2), true), spark: tr.cpi, href: "#/p/control", title: "Weighted by contract value. SPI = earned ÷ planned progress; CPI = earned value ÷ actual cost." });
    wrap.append(kp);
    const setup = GL ? setupList(d) : [];
    if (GL) { const mp = h("div", { class: "ins-card gl-month" }, h("div", { class: "ins-skel", style: "height:150px" })); wrap.append(mp); monthPanel(mp, null); }

    /* 2. decisions + portfolio health */
    const g1 = h("div", { class: "ins-grid" });
    g1.append(decisionsCard(d.decisions || [], d.attention || {}, d.glance || {}));
    if (ok.length) {
      const q = quadrant(ok, (r) => goProject(r.id, "#/p/control"));
      g1.append(h("div", { class: "ins-card" }, h("div", { class: "hd" }, h("h2", {}, "Portfolio health"), h("span", { class: "grow" }), h("a", { href: "#/command" }, "Portfolio ›")),
        q.shown ? q.el : (GL && setup.length ? setupCard(setup, true) : h("div", { class: "ins-empty" }, "Projects appear here once they have a programme (for SPI) and a BOQ budget with costs (for CPI).")),
        h("div", { class: "ins-note" }, q.shown ? "Bubble size = contract value. Click a project to open its control room." + (q.missing ? " " + q.missing + " project(s) without SPI/CPI yet." : "") : ""),
        quadSummary(ok)));
    } else g1.append(risksCard(d.risks));
    wrap.append(g1);

    /* 3. cash + risk */
    const g2 = h("div", { class: "ins-grid" });
    if (d.cash) {
      const ch = cashChart(d.cash);
      g2.append(h("div", { class: "ins-card" }, h("div", { class: "hd" }, h("h2", {}, "Cash outlook", h("span", { class: "n" }, "next 12 months")), h("span", { class: "grow" }), h("a", { href: "#/acc/cash" }, "What-if ›")),
        ch || h("div", { class: "ins-empty" }, "No cash forecast yet."),
        h("div", { class: "ins-note" }, K.cash_shortfall ? "Cash falls below the minimum balance in " + monthName(K.cash_shortfall) + ". Try a later purchase or an earlier IPC in What-if." : "Closing balance each month from every project's programme, payment terms, overheads, loans and advance tax.")));
    }
    if (ok.length || !d.cash) g2.append(risksCard(d.risks));
    if (g2.children.length === 1) g2.style.gridTemplateColumns = "1fr";
    if (g2.children.length) wrap.append(g2);
    if (GL && setup.length && q_shown(ok)) wrap.append(h("div", { class: "ins-card" }, h("div", { class: "hd" }, h("h2", {}, "To complete your figures", h("span", { class: "n" }, setup.length + " step" + (setup.length === 1 ? "" : "s")))), setupCard(setup, false)));

    /* 4. projects */
    if (d.projects.length > 1 || !S.project) wrap.append(projectsCard(d.projects, d.trends || {}, d.money));
    else if (ok[0]) wrap.append(projectsCard(d.projects, d.trends || {}, d.money));
    wrap.append(viewsRow());
  }
  let DATA = null;

  /* ───────────────────────── 2.48: what is missing for complete figures ───────────────────────── */
  const q_shown = (rows) => rows.some((r) => r.spi != null && r.cpi != null);
  function setupList(d) {
    const K = d.kpis || {}, rows = (d.projects || []).filter((r) => !r.error), out = [];
    (K.value_mismatch || []).forEach((x) => out.push({ t: "Check the contract value of " + x.code, w: "The BOQ adds up to " + money(x.boq) + " but the project's contract value is " + money(x.contract_value) + ". Work in hand uses the contract value, the forecast uses the BOQ.", href: "#/m/projects", l: "Projects ›" }));
    const noCost = rows.filter((r) => (r.revenue_without_cost || 0) > 0);
    if (noCost.length) out.push({ t: "Add cost estimates to the BOQ", w: money(noCost.reduce((a, r) => a + r.revenue_without_cost, 0)) + " of BOQ on " + noCost.map((r) => r.code).join(", ") + " has no control budget or rate analysis, so profit and CPI cannot be worked out for it.", href: "#/cl/budget", l: "Control budget ›" });
    const noProg = rows.filter((r) => r.planned_pct == null || r.spi == null);
    if (noProg.length) out.push({ t: "Give the programme its dates", w: noProg.map((r) => r.code).join(", ") + ": activities with planned start and finish give planned progress and SPI.", href: "#/p/schedule", l: "Programme ›" });
    if (K.receivable_overdue != null && !(K.receivable > 0) && rows.length) out.push({ t: "Bill the work done (IPC)", w: "No client bill is posted yet, so receivables show 0.", href: "#/p/ipc", l: "IPC ›" });
    if (d.money && K.cash == null && K.receivable_overdue != null) out.push({ t: "Enter the bank and cash opening balances", w: "Cash today and the 12-month cash outlook start from them.", href: "#/acc/bank", l: "Bank ›" });
    return out;
  }
  function setupCard(list, compact) {
    const ul = h("ul", { class: "gl-setup" });
    list.forEach((x) => ul.append(h("li", {}, h("span", { class: "k" }), h("b", {}, x.t), h("a", { href: x.href }, x.l), h("span", { class: "w" }, x.w))));
    return compact ? h("div", {}, h("div", { class: "ins-note", style: "margin-bottom:6px" }, "Time and cost health show here once these are in:"), ul) : ul;
  }

  /* ───────────────────────── 2.48: this month at a glance ───────────────────────── */
  const RESPN = { contractor: "Own", employer: "Employer's", neutral: "Neutral", concurrent: "Concurrent" };
  const RESPC = { contractor: "#a0aec0", employer: "#3182ce", neutral: "#d69e2e", concurrent: "#805ad5" };
  const n0 = (x) => (x == null ? "—" : Number(x).toLocaleString("en-IN", { maximumFractionDigits: 1 }));
  const hrs = (x) => (x == null ? "—" : n0(Math.round(x)) + " h");
  async function monthPanel(box, cal) {
    let g;
    try { g = await api("glance.month", { project_id: S.project || null, cal: cal || undefined }); } catch (e) { box.replaceChildren(h("div", { class: "ins-note" }, "This month could not load: " + e.message)); return; }
    const P = g.period, T = g.site_total || {}, M = g.money, U = g.supply, E = g.equipment, A = g.approvals || {};
    const other = P.cal === "bs" ? "ad" : "bs";
    box.replaceChildren(h("div", { class: "hd" }, h("h2", {}, "This month", h("span", { class: "n" }, P.label + " · day " + P.days_elapsed + " of " + P.days_total)), h("span", { class: "grow" }),
      h("div", { class: "ins-scope" }, h("button", { class: P.cal === "bs" ? "on" : "", onclick: () => P.cal !== "bs" && monthPanel(box, "bs") }, "Nepali month"), h("button", { class: P.cal === "ad" ? "on" : "", onclick: () => P.cal !== "ad" && monthPanel(box, "ad") }, "English month"))));
    const gr = h("div", { class: "gl-groups" });
    const grp = (title, link, linkText, ...kids) => gr.append(h("div", { class: "gl-g" }, h("h3", {}, title, link ? h("a", { href: link }, linkText + " ›") : null), ...kids));
    const rowsEl = (pairs) => h("div", { class: "gl-rows" }, pairs.filter(Boolean).flatMap(([k, v, cls]) => [h("span", {}, k), h("span", { class: cls || "" }, v)]));
    if (g.site_total) {
      const pr = g.projects.length;
      grp("Site work", "#/p/dpr", "DPRs",
        h("div", { class: "gl-big" }, money(T.work_value), h("small", {}, "NPR")),
        h("div", { class: "gl-cap" }, "work reported in DPRs at BOQ rates" + (T.work_value_prev ? " · " + money(T.work_value_prev) + " in " + T.prev_label : "")),
        rowsEl([["DPR days", T.dpr_days + (pr === 1 ? " of " + P.days_elapsed : " (all projects)"), pr === 1 && T.dpr_days < P.days_elapsed - 3 ? "warn" : ""],
          T.waiting ? ["Waiting for approval", String(T.waiting), "warn"] : null,
          ["Workers (man-days)", n0(T.man_days)],
          ["Machine hours", hrs(T.machine_hours)]]));
      const tot = (T.machine_hours || 0) + (T.idle_hours || 0) + (T.breakdown_hours || 0);
      const bar = (parts) => h("div", { class: "gl-bar" }, parts.filter((p) => p[0] > 0).map(([v, col, t]) => h("i", { style: "width:" + (100 * v / parts.reduce((a, p) => a + p[0], 0)).toFixed(1) + "%;background:" + col, title: t })));
      const dl = Object.entries(T.delay_by_resp || {});
      grp("Machines and delays", "#/x/delays", "Delays",
        h("div", { class: "gl-big" }, T.utilisation == null ? "—" : pct(T.utilisation, 0), h("small", {}, "machine time working")),
        tot ? bar([[T.machine_hours, "#38a169", "Working"], [T.idle_hours, "#d69e2e", "Idle"], [T.breakdown_hours, "#c53030", "Breakdown"]]) : h("div", { class: "gl-cap" }, "No machine hours in DPRs this month."),
        tot ? h("div", { class: "gl-legend" }, h("span", {}, h("i", { style: "background:#38a169" }), "Working " + hrs(T.machine_hours)), h("span", {}, h("i", { style: "background:#d69e2e" }), "Idle " + hrs(T.idle_hours)), h("span", {}, h("i", { style: "background:#c53030" }), "Breakdown " + hrs(T.breakdown_hours))) : null,
        h("div", { style: "margin-top:10px" }, rowsEl([["Delay hours", hrs(T.delay_hours)], ...dl.map(([k, v]) => ["  " + (RESPN[k] || k), hrs(v), k === "employer" ? "warn" : ""])])),
        (T.delay_top || []).length ? h("div", { class: "gl-note" }, "Most: " + T.delay_top.slice(0, 2).map((x) => x.category + " " + hrs(x.hours) + " (" + (RESPN[x.resp] || x.resp).toLowerCase() + ")").join(", ")) : null,
        E && E.down && E.down.length ? h("div", { class: "gl-note", style: "color:var(--bad)" }, "Down now: " + E.down.map((x) => x.code).join(", ")) : null);
    }
    if (M) {
      grp("Money", "#/acc/ageing", "Ageing",
        M.cash_total != null ? h("div", { class: "gl-big" }, money(M.cash_total), h("small", {}, "NPR cash and bank")) : h("div", { class: "gl-big" }, money(M.receivable), h("small", {}, "NPR receivable")),
        M.cash_total != null ? h("div", { class: "gl-cap" }, M.cash_entered ? (M.cash_bank || []).filter((x) => Math.abs(x.balance) > 0.5).slice(0, 3).map((x) => x.name + " " + money(x.balance)).join(" · ") || "balances today" : h("a", { href: "#/acc/bank" }, "Enter the opening bank and cash balances ›")) : h("div", { class: "gl-cap" }, "this project"),
        rowsEl([["Billed (IPC)", money(M.billed)], ["Received", money(M.received)], ["Paid", money(M.paid)],
          ["Receivable", money(M.receivable)], M.receivable_overdue > 0.5 ? ["  of which overdue", money(M.receivable_overdue), M.receivable_overdue_60 > 0.5 ? "bad" : "warn"] : null,
          ["Payable", money(M.payable)], M.payable_overdue > 0.5 ? ["  of which overdue", money(M.payable_overdue), M.payable_overdue_60 > 0.5 ? "bad" : "warn"] : null,
          ["Cost booked", money(M.cost)]]));
    }
    if (U || A) {
      grp("Supply and approvals", "#/approvals", "Approvals",
        U && U.stock_value != null ? h("div", { class: "gl-big" }, money(U.stock_value), h("small", {}, "NPR in stock")) : h("div", { class: "gl-big" }, String((A.approval || 0) + (A.to_post || 0)), h("small", {}, "waiting")),
        U && U.stock_value != null ? h("div", { class: "gl-cap" }, U.low_stock_count ? U.low_stock_count + " material(s) below reorder level" : "nothing below its reorder level") : h("div", { class: "gl-cap" }, "approvals and entries to post"),
        rowsEl([U && U.po_pending != null ? ["POs to deliver", U.po_pending + (U.po_pending ? " · " + money(U.po_pending_value) : "") + (U.po_overdue ? " (" + U.po_overdue + " late)" : ""), U.po_overdue ? "warn" : ""] : null,
          U && U.grn_count != null ? ["Goods received", U.grn_count + " GRN" + (U.grn_value ? " · " + money(U.grn_value) : "")] : null,
          ["To approve", String(A.approval || 0), A.approval ? "warn" : ""],
          A.to_post != null ? ["To post (accounts)", A.to_post + (A.to_post ? " · " + money(A.to_post_value) : ""), A.to_post ? "warn" : ""] : null,
          E ? ["Machines", E.total + (E.down && E.down.length ? " · " + E.down.length + " down" : " · all working"), E.down && E.down.length ? "bad" : ""] : null]));
    }
    box.append(gr);
    /* one row per project */
    if (g.site && g.projects.length) {
      const t = h("table", { class: "ins-ptable gl-ptable" });
      const pm = (M && M.cost_by_project) || {};
      t.append(h("thead", {}, h("tr", {}, h("th", {}, "Project"), h("th", { class: "n" }, "Work reported"), h("th", { class: "n hide-m" }, "DPR days"), h("th", { class: "n hide-s" }, "Workers / day"),
        h("th", { class: "n hide-m" }, "Machine h"), h("th", { class: "n hide-s" }, "Breakdown h"), h("th", { class: "n hide-s" }, "Delay h"), M ? h("th", { class: "n hide-m" }, "Cost booked") : null, h("th", { class: "hide-s" }, "Last DPR"))));
      const tb = h("tbody");
      g.projects.forEach((p) => {
        const x = g.site[p.id] || {};
        tb.append(h("tr", { onclick: () => goProject(p.id, "#/p/dpr") , title: (x.top_items || []).map((i) => i.code + " " + n0(i.qty) + " " + (i.unit || "") + " = " + money(i.value)).join("\n") || "Open the DPRs" },
          h("td", {}, h("b", {}, p.code), " ", h("span", { class: "hide-m" }, p.name)), h("td", { class: "n" }, money(x.work_value || 0)), h("td", { class: "n hide-m" + (x.dpr_days ? "" : " v-attention") }, String(x.dpr_days || 0)),
          h("td", { class: "n hide-s" }, x.workers_avg ? n0(x.workers_avg) : "—"), h("td", { class: "n hide-m" }, x.machine_hours ? n0(x.machine_hours) : "—"),
          h("td", { class: "n hide-s" + (x.breakdown_hours > 0 ? " v-attention" : "") }, x.breakdown_hours ? n0(x.breakdown_hours) : "—"), h("td", { class: "n hide-s" }, x.delays ? n0(x.delays.hours) : "—"),
          M ? h("td", { class: "n hide-m" }, money(pm[p.id] || 0)) : null, h("td", { class: "hide-s" }, x.last_dpr || (x.last_dpr_ever ? x.last_dpr_ever : "none yet"))));
      });
      t.append(tb);
      box.append(h("div", { style: "overflow-x:auto;margin-top:14px" }, t));
    }
    if ((T.top_items || []).length) box.append(h("div", { class: "gl-note" }, "Most work this month: " + T.top_items.slice(0, 4).map((i) => (g.projects.length > 1 ? i.project + " " : "") + i.code + " " + n0(i.qty) + " " + (i.unit || "") + " (" + money(i.value) + ")").join(" · ") + "."));
    if (g.own_events && g.own_events.count) box.append(h("div", { class: "gl-note" }, g.own_events.count + " own delay event(s) are open in the delay register (for example " + g.own_events.examples[0] + "). They need no contract notice; close them once the cause is fixed."));
  }

  /* the four quarters as a short list: which projects sit where, and the money in each */
  function quadSummary(rows) {
    const q = [["Late & over budget", (r) => r.spi < 1 && r.cpi < 1, "critical"], ["Late, under budget", (r) => r.spi < 1 && r.cpi >= 1, "attention"],
      ["Ahead, over budget", (r) => r.spi >= 1 && r.cpi < 1, "attention"], ["Ahead & under budget", (r) => r.spi >= 1 && r.cpi >= 1, "ok"]];
    const pts = rows.filter((r) => r.spi != null && r.cpi != null);
    if (!pts.length) return null;
    const ul = h("ul", { class: "ins-risks" });
    q.forEach(([label, test, lv]) => {
      const inq = pts.filter(test);
      if (!inq.length) return;
      ul.append(h("li", { onclick: () => goProject(inq[0].id, "#/p/control") }, h("span", { class: "ins-tag " + lv }, inq.length), h("span", { class: "t" }, label + ": " + inq.map((r) => r.code).join(", ")),
        h("span", { class: "e" }, inq.some((r) => r.contract_value) ? money(inq.reduce((a, r) => a + (r.contract_value || 0), 0)) : "")));
    });
    return ul;
  }

  function decisionsCard(list, att, gl) {
    gl = gl || {};
    let filter = "all", showAll = false;
    const kinds = [...new Set(list.map((x) => x.kind))];
    const box = h("div", { class: "ins-card" });
    const draw = () => {
      box.innerHTML = "";
      const vis = list.filter((x) => filter === "all" || x.kind === filter);
      const total = vis.reduce((a, x) => a + (x.impact || 0), 0);
      box.append(h("div", { class: "hd" }, h("h2", {}, GL ? "Needs attention" : "Decisions this week", h("span", { class: "n" }, list.length ? list.length + (total ? " · " + money(total) + " at stake" : "") : "")), h("span", { class: "grow" }),
        kinds.length > 1 ? h("div", { class: "ins-chips" }, [["all", "All"], ...kinds.map((k) => [k, KIND[k] || k])].map(([k, l]) => h("button", { class: filter === k ? "on" : "", onclick: () => { filter = k; showAll = false; draw(); } }, l))) : null));
      if (!vis.length) {
        box.append(h("div", { class: "ins-empty" }, h("span", { class: "ok" }, "✓"), h("span", {}, (GL ? "Nothing needs attention right now." : "Nothing needs a decision right now.") + (att.approval ? " " + att.approval + " item(s) wait for approval." : ""))));
      } else {
        const ul = h("ul", { class: "ins-dec" });
        (showAll ? vis : vis.slice(0, 6)).forEach((x) => {
          const grp = GL && x.items && x.items.length > 1;
          const li = h("li", { class: x.severity, title: grp ? "Show each one" : "Open the screen that fixes it" },
            h("span", { class: "ic" }, ico(x.kind)), h("b", {}, h("span", { class: "sev" }, SEV[x.severity] || ""), x.title), h("span", { class: "amt" }, x.impact ? money(x.impact) : ""),
            h("span", { class: "why" }, x.why), h("span", { class: "act" }, grp ? "Show " + x.items.length + " ▾" : (x.action || "Open") + " ›"));
          if (grp) {
            let sub = null;
            li.onclick = (e) => {
              if (e.target.closest(".subs")) return;
              if (sub) { sub.remove(); sub = null; li.querySelector(".act").textContent = "Show " + x.items.length + " ▾"; return; }
              sub = h("ul", { class: "subs" }, x.items.map((y) => h("li", { onclick: (ev) => { ev.stopPropagation(); goProject(y.project_id || x.project_id, y.link || x.link); }, style: "cursor:pointer" },
                h("b", {}, y.title), h("span", { class: "why" }, y.why), y.impact ? h("span", { class: "amt" }, money(y.impact)) : null, h("span", { class: "act" }, (y.action || "Open") + " ›"))));
              sub.append(h("li", { style: "border:0" }, h("a", { href: x.link, onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); goProject(x.project_id, x.link); } }, (x.action || "Open") + " ›")));
              li.append(sub);
              li.querySelector(".act").textContent = "Hide ▴";
            };
          } else li.onclick = () => goProject(x.project_id, x.link);
          ul.append(li);
        });
        box.append(ul);
        if (vis.length > 6 && !showAll) box.append(h("button", { class: "ins-more", onclick: () => { showAll = true; draw(); } }, "Show all " + vis.length));
      }
      const extra = [];
      if (att.approval) extra.push(h("a", { href: "#/approvals" }, att.approval + " waiting for approval"));
      if (att.overdue) extra.push(h("a", { href: "#/action" }, att.overdue + " overdue"));
      if (att.today) extra.push(h("a", { href: "#/action" }, att.today + " due today"));
      if (extra.length) box.append(h("div", { class: "ins-views", style: "margin-top:10px" }, h("span", {}, "Action centre:"), extra));
      if (GL && gl.own_events) box.append(h("div", { class: "ins-note", style: "margin-top:8px" }, gl.own_events + " delay event" + (gl.own_events === 1 ? " is" : "s are") + " the company's own (equipment breakdown, shortages): no contract notice is needed, so they are not listed here. ",
        h("a", { href: "#/x/delays" }, "Delays by responsibility ›")));
    };
    draw();
    return box;
  }

  function risksCard(r) {
    r = r || { top: [], heat: [[], [], [], [], []], open: 0, emv: 0 };
    const box = h("div", { class: "ins-card" }, h("div", { class: "hd" }, h("h2", {}, "Risk", h("span", { class: "n" }, r.open ? r.open + " open" + (r.emv ? " · expected " + money(r.emv) : "") : "")), h("span", { class: "grow" }), h("a", { href: "#/risks" }, "Risk register ›")));
    const inner = h("div", { class: "ins-rk" });
    inner.append(heatMap(r.heat, (p, i) => { location.hash = "#/risks?p=" + p + "&i=" + i; }));
    const ul = h("ul", { class: "ins-risks", style: "margin:0" });
    (r.top || []).slice(0, 4).forEach((x) => ul.append(h("li", { onclick: () => { location.hash = "#/risks?id=" + x.id; } },
      h("span", { class: "sc", style: "background:" + heatColor(x.probability, x.impact) }, x.score), h("span", { class: "t", title: x.title }, x.title), x.emv ? h("span", { class: "e" }, money(x.emv)) : null)));
    if (!(r.top || []).length) ul.append(h("li", { onclick: () => { location.hash = "#/risks"; } }, h("span", { class: "t" }, "No risks recorded. BuildCore can suggest some from your figures."), h("span", { class: "e" }, "Open ›")));
    inner.append(ul);
    box.append(inner);
    return box;
  }

  function projectsCard(rows, tr, money_) {
    const dims = [["schedule", "Time"], ["cost", "Cost"], ["quality", "Quality"], ["resources", "Resources"], ["commercial", "Commercial"]];
    const t = h("table", { class: "ins-ptable" });
    t.append(h("thead", {}, h("tr", {}, h("th", {}, "Project"), h("th", { class: "pb hide-m" }, "Progress"), h("th", { class: "n" }, "SPI"), h("th", { class: "n" }, "CPI"),
      money_ ? h("th", { class: "n hide-s" }, "Forecast margin") : null, money_ ? h("th", { class: "n hide-m" }, "Receivable") : null, h("th", { class: "hide-s" }, "Health"), h("th", { class: "n hide-s" }, "Finish"))));
    const tb = h("tbody");
    rows.forEach((r) => {
      if (r.error) { tb.append(h("tr", {}, h("td", {}, h("b", {}, r.code), " ", r.name), h("td", { colspan: 7, class: "ins-note" }, "Figures not available: " + r.error))); return; }
      const ss = tr[r.id] || [];
      const mDelta = delta(ss.map((s) => s.forecast_margin));
      const late = r.forecast_finish && r.end_date && r.forecast_finish > r.end_date;
      tb.append(h("tr", { onclick: () => goProject(r.id, "#/p/control"), title: Object.values(r.reasons || {}).flat().join("\n") || "Open the control room" },
        h("td", {}, h("b", {}, r.code), " ", h("span", { class: "hide-m" }, r.name)),
        h("td", { class: "pb hide-m" }, r.planned_pct != null ? [progressBar(r.planned_pct || 0, r.actual_pct || 0), h("small", {}, pct(r.actual_pct, 0) + " of " + pct(r.planned_pct, 0) + " planned")] : h("small", {}, "no programme")),
        h("td", { class: "n v-" + lvl(r.spi, 0.95, 0.85) }, ratio(r.spi)), h("td", { class: "n v-" + lvl(r.cpi, 0.95, 0.85) }, ratio(r.cpi)),
        money_ ? h("td", { class: "n hide-s v-" + (r.forecast_margin == null ? "" : r.forecast_margin < 0 ? "critical" : r.forecast_margin < 5 ? "attention" : "ok") }, pct(r.forecast_margin), trendTag(mDelta, (x) => x.toFixed(1), true)) : null,
        money_ ? h("td", { class: "n hide-m" }, money(r.receivable)) : null,
        h("td", { class: "hide-s" }, h("span", { class: "ins-dots" }, dims.map(([k, l]) => h("i", { class: (r.health || {})[k] || "", title: l + ": " + (LEVEL_TEXT[(r.health || {})[k]] || "—") })))),
        h("td", { class: "n hide-s" + (late ? " v-critical" : "") }, r.forecast_finish || r.end_date || "—")));
    });
    t.append(tb);
    return h("div", { class: "ins-card" }, h("div", { class: "hd" }, h("h2", {}, "Projects", h("span", { class: "n" }, rows.length + " active")), h("span", { class: "grow" }),
      h("span", { class: "ins-legend" }, h("span", {}, h("i", { style: "background:var(--ok)" }), "good"), h("span", {}, h("i", { style: "background:var(--warn)" }), "attention"), h("span", {}, h("i", { style: "background:var(--bad)" }), "critical"))),
    h("div", { style: "overflow-x:auto" }, t));
  }

  /* the screens that left the Dashboard menu are one click away */
  function viewsRow() {
    const all = [["command", "Portfolio (command centre)", "commercial"], ["p/control", "Project control room", "project"], ["action", "Action centre"], ["dc", "Decision centre", "commercial"],
      ["p/kpi", "KPI dashboard", "inventory"], ["p/live", "Live activity", "project"], ["dashboard/classic", "Classic dashboard"]];
    const links = all.filter(([p, , m]) => PAGES[p] && (!m || can(m, "view"))).map(([p, l]) => h("a", { href: "#/" + p }, l));
    const box = h("label", { class: "ins-note", style: "margin-left:auto;display:inline-flex;gap:6px;align-items:center;cursor:pointer" },
      h("input", { type: "checkbox", checked: startHere(), onchange: (e) => { LSset("bco_start_dash", e.target.checked ? "1" : "0"); toast(e.target.checked ? "BuildCore will open on this dashboard." : "BuildCore will open on the modules screen."); } }), "Open BuildCore here");
    return h("div", { class: "ins-views" }, h("span", {}, "More views:"), links, box);
  }

  /* ───────────────────────── one-page report ───────────────────────── */
  function printReport(d) {
    if (!d) return toast("Wait for the dashboard to load.", "err");
    const K = d.kpis || {};
    const node = h("div");
    const row = (pairs) => h("table", {}, h("tbody", {}, pairs.filter(Boolean).map(([k, v]) => h("tr", {}, h("th", { style: "text-align:left;width:45%" }, k), h("td", {}, v)))));
    node.append(h("h3", {}, "Headline figures"), row([
      K.contract_value != null && ["Work in hand (contract value less work done)", money(K.backlog) + " of " + money(K.contract_value)],
      K.forecast_profit != null && ["Forecast profit at completion", money(K.forecast_profit) + (K.forecast_margin != null ? " (" + pct(K.forecast_margin) + ")" : "")],
      K.cash != null && ["Cash and bank today", money(K.cash) + (K.cash_lowest ? "; lowest " + money(K.cash_lowest.balance) + " in " + monthName(K.cash_lowest.month) : "")],
      K.receivable != null && ["Receivable / overdue", money(K.receivable) + " / " + money(K.receivable_overdue)],
      ["Portfolio SPI / CPI", ratio(K.spi) + " / " + ratio(K.cpi)]]));
    node.append(h("h3", {}, "Decisions"), (d.decisions || []).length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Priority"), h("th", {}, "Decision"), h("th", {}, "Why"), h("th", {}, "At stake"))),
      h("tbody", {}, d.decisions.map((x) => h("tr", {}, h("td", {}, SEV[x.severity]), h("td", {}, x.title), h("td", {}, x.why), h("td", { style: "text-align:right" }, x.impact ? money(x.impact) : ""))))) : h("p", {}, "Nothing needs a decision."));
    node.append(h("h3", {}, "Projects"), h("table", {}, h("thead", {}, h("tr", {}, ["Project", "Actual / planned", "SPI", "CPI", d.money ? "Forecast margin" : null, d.money ? "Receivable" : null, "Finish"].filter(Boolean).map((x) => h("th", {}, x)))),
      h("tbody", {}, (d.projects || []).filter((r) => !r.error).map((r) => h("tr", {}, h("td", {}, r.code + " " + r.name), h("td", {}, pct(r.actual_pct, 0) + " / " + pct(r.planned_pct, 0)), h("td", {}, ratio(r.spi)), h("td", {}, ratio(r.cpi)),
        d.money ? h("td", {}, pct(r.forecast_margin)) : null, d.money ? h("td", { style: "text-align:right" }, money(r.receivable)) : null, h("td", {}, r.forecast_finish || r.end_date || ""))))));
    if (d.risks && d.risks.top.length) node.append(h("h3", {}, "Top risks"), h("table", {}, h("thead", {}, h("tr", {}, ["No", "Risk", "Score", "Expected cost", "Owner"].map((x) => h("th", {}, x)))),
      h("tbody", {}, d.risks.top.map((x) => h("tr", {}, h("td", {}, x.no), h("td", {}, x.title), h("td", {}, x.score + " / 25"), h("td", {}, money(x.emv)), h("td", {}, x.owner || ""))))));
    if (d.cash) node.append(h("h3", {}, "Cash outlook"), h("table", {}, h("thead", {}, h("tr", {}, d.cash.rows.map((r) => h("th", {}, monthName(r.month))))), h("tbody", {}, h("tr", {}, d.cash.rows.map((r) => h("td", { style: r.overdraft_needed > 0 ? "color:#c53030" : "" }, money(r.closing)))))));
    printFrame("Portfolio report", node, [["Scope", S.project ? nm.project(S.project) : "All projects"], ["As of", d.as_of]]);
  }

  /* ───────────────────────── risk register ───────────────────────── */
  let META = null;
  const RESP = { avoid: "Avoid", reduce: "Reduce", transfer: "Transfer / insure", accept: "Accept" };
  async function riskForm(row, reload) {
    META = META || await api("risk.meta", {});
    row = Object.assign({ probability: 3, impact: 3, response: "reduce", status: "open", project_id: S.project || "" }, row || {});
    const f = form([
      { k: "project_id", label: "Project", type: "select", options: opt.projects(), blank: "Company-wide" },
      { k: "title", label: "Risk (what could happen)", req: true, wide: true, ph: "e.g. Monsoon flood overtops the coffer dam" },
      { k: "category", label: "Category", type: "select", options: META.categories.map((x) => [x, x]) },
      { k: "owner", label: "Owner", ph: "Who watches it" },
      { k: "cause", label: "Cause", type: "textarea", wide: true },
      { k: "effect", label: "Effect on the project", type: "textarea", wide: true },
      { k: "probability", label: "Probability", type: "select", noBlank: true, options: [[1, "1 Rare (≈5%)"], [2, "2 Unlikely (≈20%)"], [3, "3 Possible (≈40%)"], [4, "4 Likely (≈60%)"], [5, "5 Almost certain (≈85%)"]] },
      { k: "impact", label: "Impact", type: "select", noBlank: true, options: [[1, "1 Minor"], [2, "2 Moderate"], [3, "3 Serious"], [4, "4 Major"], [5, "5 Severe"]] },
      { k: "cost_impact", label: "Cost if it happens (NPR)", type: "number" },
      { k: "time_impact_days", label: "Delay if it happens (days)", type: "number" },
      { k: "response", label: "Response", type: "select", noBlank: true, options: META.responses },
      { k: "action", label: "Action to take", wide: true },
      { k: "due_date", label: "Action due", type: "date" },
      { k: "status", label: "Status", type: "select", noBlank: true, options: [["open", "Open"], ["occurred", "Occurred"], ["closed", "Closed"]] },
    ], row);
    const score = h("p", { class: "hint" });
    const upd = () => { const v = f.values(); const p = Number(v.probability), i = Number(v.impact); const emv = (META.prob_pct[p] || 0.4) * Number(v.cost_impact || 0);
      score.innerHTML = ""; score.append(h("span", { class: "rk-sc", style: "background:" + heatColor(p, i) }, p * i), " Score " + p * i + " of 25" + (emv ? " · expected cost " + money(emv) + " NPR (probability × cost)" : "")); };
    f.addEventListener("change", upd); f.addEventListener("input", upd); upd();
    modal(row.id ? "Risk " + (row.no || "") : "New risk", h("div", {}, f, score), [
      can("project", "edit") ? { label: "Save", cls: "primary", act: async () => { await run("risk.save", { row: Object.assign({ id: row.id || null }, f.values()) }, "Risk saved"); reload(); } } : null,
      row.id && can("project", "approve") ? { label: "Delete", cls: "warn", act: async () => { if (!(await ask("Delete risk", "Remove " + (row.no || "this risk") + " from the register? Closing it keeps the history.", { danger: true, ok: "Delete" }))) return false; await run("risk.delete", { id: row.id }, "Deleted"); reload(); } } : null]);
  }

  async function riskPage(root, params) {
    const reload = () => go();
    root.append(pageHead("Risk register", "What could go wrong, how likely, what it would cost, and who is acting on it. Score = probability × impact; expected cost = chance × cost if it happens.",
      can("project", "edit") ? h("button", { class: "btn primary", onclick: () => riskForm(null, reload) }, "+ New risk") : null));
    const rows = await run("risk.list", { project_id: S.project || null });
    let cell = params.p && params.i ? [Number(params.p), Number(params.i)] : null;
    let status = "open";
    const open = rows.filter((r) => r.status === "open");
    const heat = [0, 1, 2, 3, 4].map(() => [0, 0, 0, 0, 0]);
    open.forEach((r) => { heat[r.probability - 1][r.impact - 1] += 1; });
    const emv = open.reduce((a, r) => a + (r.emv || 0), 0);
    const top = h("div", { class: "rk-top" });
    const hm = h("div", { class: "ins-card" }, h("div", { class: "hd" }, h("h2", {}, "Heat map", h("span", { class: "n" }, open.length + " open · expected " + money(emv)))), heatMap(heat, (p, i) => { cell = cell && cell[0] === p && cell[1] === i ? null : [p, i]; draw(); }));
    const side = h("div", { class: "ins-card" });
    top.append(hm, side);
    root.append(top);
    const listBox = h("div");
    root.append(listBox);
    const draw = () => {
      listBox.innerHTML = "";
      const vis = rows.filter((r) => (status === "all" || r.status === status) && (!cell || (r.probability === cell[0] && r.impact === cell[1])));
      listBox.append(h("div", { class: "ins-chips", style: "margin:0 0 8px" }, [["open", "Open"], ["occurred", "Occurred"], ["closed", "Closed"], ["all", "All"]].map(([k, l]) => h("button", { class: status === k ? "on" : "", onclick: () => { status = k; draw(); } }, l)),
        cell ? h("button", { class: "on", onclick: () => { cell = null; draw(); } }, "P" + cell[0] + " × I" + cell[1] + " ✕") : null));
      listBox.append(table([{ label: "No", v: (r) => h("span", { style: "white-space:nowrap" }, r.no || "") }, { label: "Project", v: (r) => r.project_code || "Company" }, { k: "title", label: "Risk" }, { k: "category", label: "Category" }, { k: "owner", label: "Owner" },
        { label: "Score", v: (r) => h("span", { class: "rk-sc", style: "background:" + heatColor(r.probability, r.impact) }, r.score) }, { k: "emv", label: "Expected cost", fmt: "money" },
        { label: "Response", v: (r) => RESP[r.response] || r.response || "" }, { k: "action", label: "Action" }, { label: "Due", v: (r) => h("span", { style: "white-space:nowrap", class: r.status === "open" && r.due_date && r.due_date < today() ? "red" : "" }, r.due_date || "") }, { label: "Status", v: (r) => stamp(r.status) }],
      vis, { name: "risks", onRow: (r) => riskForm(r, reload), totals: ["emv"], empty: "No risks here. Add one, or take a suggestion from your figures." }));
    };
    draw();
    if (params.id) { const r = rows.find((x) => String(x.id) === String(params.id)); if (r) riskForm(r, reload); }
    /* suggestions: risks the figures already point to */
    side.append(h("div", { class: "hd" }, h("h2", {}, "Suggested from your figures")));
    try {
      const sug = await api("risk.suggest", { project_id: S.project || null });
      if (!sug.length) side.append(h("p", { class: "ins-note" }, "Nothing new: the figures don't point to risks that aren't already in the register."));
      const sb = h("div", { class: "rk-sug" });
      sug.forEach((x) => sb.append(h("div", {}, h("span", { class: "rk-sc", style: "background:" + heatColor(x.probability, x.impact) }, x.probability * x.impact),
        h("b", {}, x.project_code + ": " + x.title, h("br"), h("small", {}, x.cause)),
        can("project", "edit") ? h("button", { class: "btn small", onclick: () => riskForm(Object.assign({}, x, { project_code: undefined }), reload) }, "Add") : null)));
      side.append(sb);
    } catch (e) { side.append(h("p", { class: "ins-note" }, e.message)); }
    side.append(h("p", { class: "ins-note", style: "margin-top:10px" }, "Responses follow ISO 31000: avoid, reduce, transfer (insure or subcontract), or accept with a contingency."));
  }

  /* ───────────────────────── menu, landing page, what's new ───────────────────────── */
  const KEEP = ["dashboard", "action", "risks", "p/control", "command", "dc", "dc/house", "mywork", "inbox"];
  function tidyMenu() {
    if (typeof MENU === "undefined") return;
    const ov = MENU.find((g) => g[0] === "Overview");
    if (!ov || ov._bco218) return;
    const items = ov[2];
    const byKey = Object.fromEntries(items.map((x) => [x[0], x]));
    byKey.dashboard = ["dashboard", "Dashboard", null];
    byKey.risks = ["risks", "Risk register", "project"];
    if (byKey.command) byKey.command = ["command", "Portfolio", byKey.command[2]];
    const keep = KEEP.filter((k) => byKey[k]).map((k) => byKey[k]);
    const rest = items.filter((x) => !KEEP.includes(x[0]));
    rest.push(["dashboard/classic", "Classic dashboard", "accounts"]);
    ov[2] = keep;
    ov._bco218 = true;
    const i = MENU.indexOf(ov);
    if (!MENU.some((g) => g[0] === "Tools & views")) MENU.splice(i + 1, 0, ["Tools & views", null, rest]);
  }

  function whatsNew() {
    const li = (b, t) => h("li", {}, h("b", {}, b), " ", t);
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:560px" },
      h("p", {}, "A simpler dashboard that tells you where to act."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        li("One dashboard.", "Five headline figures with their trend, the decisions to take this week ranked by money at stake, portfolio health (SPI × CPI), cash for the next 12 months and a risk heat map."),
        li("Decisions with a fix.", "Each one says why and opens the screen that fixes it: bill measured work, chase an overdue client, plan cost or programme recovery, send a contract notice before it is time-barred, order short materials."),
        li("Risk register.", "Probability × impact scoring, expected cost, owner, response and action date, a 5 × 5 heat map, and risks suggested from your own figures."),
        li("Trends.", "BuildCore keeps one snapshot of each project's figures a day, so the dashboard shows whether profit, SPI and CPI are improving."),
        li("Shorter menu.", "The Dashboard module has 9 screens instead of 15; the rest are under Tools & views. The old dashboard is still there as Classic dashboard."),
        li("Print report.", "One page with the figures, decisions, projects, risks and cash for a board or client meeting.")),
      h("p", { class: "hint" }, "Also from 2.17: dark mode, Ctrl+K to find anything, pinned screens and sortable lists.")),
    [{ label: "Open the dashboard", cls: "primary", act: () => { location.hash = "#/dashboard"; } }], { narrow: true });
  }

  /* 2.17's own what's-new is folded into this one */
  LSset("bco_seen_2.17.0", "1");

  /* runs right after 2.6's ensureItems, before the Focus profiles copy the menu */
  const hooks = (window.bcoBootHooks = window.bcoBootHooks || []);
  hooks.splice(Math.min(1, hooks.length), 0, () => { try { tidyMenu(); } catch (e) { /* ignore */ } });
  hooks.push(() => {
    try {
      const classic = PAGES.dashboard;
      if (classic && !classic._bco218) PAGES["dashboard/classic"] = classic;
      dashboard._bco218 = true;
      PAGES.dashboard = dashboard;
      PAGES.risks = riskPage;
      /* the Dashboard module opens the dashboard itself, not a list of screens */
      const mod = PAGES.mod;
      if (mod && !mod._bco218) { PAGES.mod = async (root, params) => (params.m === "Overview" ? dashboard(root) : mod(root, params)); PAGES.mod._bco218 = true; }
      /* land on the dashboard (can be switched off on the dashboard itself) */
      if (startHere() && typeof HOME === "object") Object.keys(HOME).forEach((k) => { HOME[k] = "dashboard"; });
    } catch (e) { /* the old screens keep working */ }
    setTimeout(() => {
      if (LS("bco_seen_" + VER, "") === "1") return;
      if (!document.querySelector(".top") || document.querySelector(".overlay")) return;
      LSset("bco_seen_" + VER, "1");
      whatsNew();
    }, 1800);
  });
  window.bcoInsight = { VER, dashboard, riskPage, printReport, whatsNew, money };
})();
