/* AlooSoul FPL agent: static app. Reads editions/index.json, the current
   edition and the run's app.json, then renders every screen from them.
   Routing is on the hash: #edition, #squad, #planner, #captain, #chips,
   #finder, #dataroom[-tab | -story-hN], #player-ID, #team-ID, #freehit,
   #ask, #alerts, #archive, #edition-GW. Click targets follow
   design/mockups/ClickMap.dc.html. */
(function () {
  "use strict";

  // ---------- state ----------
  let BASE = "";
  let IDX, ED, D, SRC;
  const S = {
    squadView: "after", squadMode: "cards", plan: "call", build: false, bOut: null, bIn: null,
    cap: null, chip: "fh1", fPos: "MID", fCap: "99",
    tab: "stories", pgroup: "attack", tgroup: "table", tick: "att", run: 6, gw9: false,
    pmg: "attack", ask: { q: null, custom: null, draft: "", err: "", busy: false, answer: null }
  };
  const trail = [];
  let depth = {};

  // ---------- helpers ----------
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const f1 = (x) => (Math.round(x * 10) / 10).toFixed(1);
  const f2 = (x) => Number(x).toFixed(2);
  const sg = (x, d = 1) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);
  const pct = (x) => (x == null ? "0" : Math.round(x)) + "%";
  const intl = (n) => Number(n).toLocaleString("en-GB");
  const P = (id) => D.players[String(id)];
  const nm = (id) => (P(id) ? P(id).n : "Unknown");
  const team = (id) => D.teams[String(id)];
  const teamByShort = (s) => Object.values(D.teams).find((t) => t.short === s);
  const POSNAME = { GK: "Goalkeeper", DEF: "Defender", MID: "Midfielder", FWD: "Forward" };
  const POSPL = { GK: "Goalkeepers", DEF: "Defenders", MID: "Midfielders", FWD: "Forwards" };
  const ord = (n) => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");
  const ist = (iso, opts) => new Intl.DateTimeFormat("en-GB", Object.assign({ timeZone: "Asia/Kolkata" }, opts)).format(new Date(iso));
  const uk = (iso, opts) => new Intl.DateTimeFormat("en-GB", Object.assign({ timeZone: "Europe/London" }, opts)).format(new Date(iso));
  const pulled = () => ist(D.meta.pulled_at, { day: "numeric", month: "short", year: "numeric" }) + ", " + ist(D.meta.pulled_at, { hour: "2-digit", minute: "2-digit", hour12: false }) + " IST";
  const pulledShort = () => ist(D.meta.pulled_at, { day: "numeric", month: "short" }) + ", " + ist(D.meta.pulled_at, { hour: "2-digit", minute: "2-digit", hour12: false }) + " IST";
  const plink = (id, text, cls) => `<a href="#player-${id}"${cls ? ` class="${cls}"` : ""}>${esc(text == null ? nm(id) : text)}</a>`;
  const gws = () => Object.keys(P(D.squad.ids[0]).w).map(Number).sort((a, b) => a - b);
  const g0 = () => D.meta.model.horizon[0];
  const g1 = () => D.meta.model.horizon[1];
  const oppLabel = (fx) => fx.map(([o, h]) => (h ? o.toUpperCase() : o.toLowerCase())).join(" + ") || "none";
  const weekXp = (p, g) => (p.w[g] ? p.w[g][0] : 0);
  const heatCls = (x) => (x >= 5 ? "h-hot" : x >= 4 ? "h-warm" : "h-cool");
  const live = (k) => SRC && SRC.sources && SRC.sources[k] && SRC.sources[k].status === "healthy";
  const mine = (id) => D.squad.ids.includes(Number(id));
  const sellsInCall = (id) => ED.call.transfers.some((t) => t.out_id === Number(id));
  const buysInCall = (id) => ED.call.transfers.some((t) => t.in_id === Number(id));
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage off */ } }
  };

  async function getJSON(path) {
    const r = await fetch(BASE + path);
    if (!r.ok) throw new Error(path + " " + r.status);
    return r.json();
  }
  async function findBase() {
    for (const b of ["", "../"]) {
      try { const r = await fetch(b + "editions/index.json"); if (r.ok) { BASE = b; return r.json(); } } catch (e) { /* next */ }
    }
    throw new Error("editions/index.json not found");
  }

  // ---------- markdown (headings, tables, lists, bold) ----------
  function inline(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }
  function md(src) {
    const out = [];
    const blocks = String(src || "").split(/\n{2,}/);
    for (const b of blocks) {
      const lines = b.split("\n");
      if (/^#{1,3} /.test(lines[0])) { out.push(`<h3>${inline(lines[0].replace(/^#+ /, ""))}</h3>`); if (lines.length > 1) out.push(`<p>${inline(lines.slice(1).join(" "))}</p>`); continue; }
      if (lines[0].trim().startsWith("|")) {
        const rows = lines.filter((l) => !/^\|\s*-/.test(l)).map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
        const [h, ...rs] = rows;
        out.push(`<div class="scrollx"><table><thead><tr>${h.map((c) => `<th scope="col">${inline(c)}</th>`).join("")}</tr></thead><tbody>${rs.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      if (lines.every((l) => /^- /.test(l))) { out.push(`<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join("")}</ul>`); continue; }
      out.push(`<p>${inline(lines.join(" "))}</p>`);
    }
    return out.join("");
  }

  // ---------- shared pieces ----------
  function nav(cur) {
    const n = D.alerts.filter((a) => a.tonight).length;
    const items = [["edition", "Edition"], ["squad", "Squad"], ["planner", "Planner"], ["ask", "Ask"], ["alerts", "Alerts"]];
    return `<nav class="nav" aria-label="Main"><div>${items.map(([h, l]) => `<a href="#${h}"${cur === h ? ' aria-current="page"' : ""}>${l}${h === "alerts" && n ? ` <span class="count" aria-label="${n} need action">${n}</span>` : ""}</a>`).join("")}</div></nav>`;
  }
  function back(fallback, label) {
    return `<button type="button" class="back" data-act="back" data-fallback="${fallback}">← ${esc(label)}</button>`;
  }
  function v1box(title, body, small) {
    return `<div class="note-blue"><span class="t">${esc(title || "Connects in v1")}</span><span>${esc(body)}</span>${small ? `<span style="font-size:14px">${esc(small)}</span>` : ""}</div>`;
  }
  function planTabs(cur) {
    const t = [["planner", "Transfers"], ["captain", "Captain"], ["chips", "Chips"], ["finder", "Finder"]];
    return `<nav aria-label="Planner sections" class="seg gutter-in" style="margin: 0 20px 16px;">${t.map(([h, l]) => `<a href="#${h}"${cur === h ? ' aria-current="page"' : ""}>${l}</a>`).join("")}</nav>`;
  }
  function tagFor(tone) { return { review: "tag-green", decision: "tag-orange", template: "tag-orange", chip: "tag-orange", price: "tag-orange", fixtures: "tag-blue", data: "tag-blue", injury: "tag-red" }[tone] || "tag-blue"; }
  function minibars(fig) {
    const max = Math.max(...fig.data.map((d) => d.value), 0.1);
    return `<div class="minibars" role="img" aria-label="${esc(fig.title + ": " + fig.data.map((d) => d.label + " " + d.value).join(", "))}">${fig.data.map((d) => `<span class="${d.highlight ? "hi" : ""}" style="height:${Math.max(4, (d.value / max) * 100).toFixed(0)}%"></span>`).join("")}</div><div class="minilabels" aria-hidden="true">${fig.data.map((d) => `<span>${esc(d.label)}<br><b>${d.value}</b></span>`).join("")}</div>`;
  }
  function kv(rows) { return `<div class="kv">${rows.map(([k, v, sub]) => `<div><span class="k">${k}</span><span class="v${sub ? " sub" : ""}">${v}</span></div>`).join("")}</div>`; }

  // ---------- Edition ----------
  function vEdition(gw) {
    const ed = ED;
    const now = Date.now();
    const ms = new Date(ed.deadline_utc) - now;
    const dl = ms > 0 ? `Deadline in ${Math.floor(ms / 864e5)}d ${Math.floor((ms % 864e5) / 36e5)}h` : "Deadline passed";
    const st = ed.status;
    depth = store.get("depth-gw" + ed.gw) || {};
    const call = ed.call;
    const heads = ed.headlines.map((h) => {
      const read = ed.reads.find((r) => r.id === h.read);
      const deep = read && read.deep ? ed.data_room.find((d) => d.id === read.deep) : null;
      const opts = [[0, "Headline"]];
      if (read) opts.push([1, "The read"]);
      if (deep || h.evidence) opts.push([2, "Data room"]);
      let d = depth[h.id] || 0;
      if (!opts.some((o) => o[0] === d)) d = 0;
      const fig = read && read.figure;
      const isFH = deep && deep.id && ed.data_room.find((x) => x.id === deep.id).bottom_line;
      const teaserHref = isFH ? "#freehit" : `#dataroom-story-${h.id}`;
      const teaserLabel = isFH ? "Open the Free Hit analysis" : "Open the evidence";
      const teaser = d >= 2 ? `<div class="inset"><span class="inset-lab">Data room</span>${fig ? minibars(fig) : kv(h.evidence.facts.slice(0, 3).map((f) => [esc(f.k), esc(f.v)]))}<a href="${teaserHref}" class="textlink" style="font-size:16px">${teaserLabel} →</a></div>` : "";
      return `<article class="card" id="story-${h.id}">
        <span class="tag ${tagFor(h.tone)}">${esc(h.kicker)}</span>
        <h3 class="t-headline">${esc(h.title)}</h3>
        <p class="dek">${esc(h.dek)}</p>
        ${d >= 1 && read ? `<div class="readlayer md">${md(read.body)}</div>` : ""}
        ${teaser}
        ${opts.length > 1 ? `<div role="group" aria-label="How deep" class="depth">${opts.map(([n, l]) => `<button type="button" data-act="depth" data-id="${h.id}" data-n="${n}" aria-pressed="${d === n}">${l}</button>`).join("")}</div>` : ""}
      </article>`;
    }).join("");
    const alert = (ed.alerts || [])[0];
    const pub = new Date(ed.published_at);
    return `
    <header class="ed-head gutter">
      <div class="ed-top"><span class="brand">AlooSoul</span><span class="deadline">${dl}</span></div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <div class="ed-meta"><span>Gameweek ${ed.gw} · Edition ${ed.edition || 1} · ${ist(pub, { day: "numeric", month: "short" })}</span><a href="#archive">Past editions</a></div>
        <h1 class="t-hero" tabindex="-1">${esc(ed.title)}</h1>
      </div>
      <div class="tiles">
        <div class="tile"><b>${intl(st.overall_rank)}</b><span>Overall rank</span></div>
        <div class="tile"><b>${st.gap_top10k} pts</b><span>to the top 10k</span></div>
        <div class="tile"><b>${st.free_transfers}</b><span>Free transfers</span></div>
        <div class="tile"><b>£${f1(st.bank)}m</b><span>In the bank</span></div>
      </div>
    </header>
    <section class="navy callcard" aria-labelledby="call-h">
      <div class="navy-head"><h2 class="t-section" id="call-h">The call</h2><span class="cap">${sg(call.projected_gain)} pts over ${call.horizon[1] - call.horizon[0] + 1} GWs</span></div>
      <div class="moves">${call.transfers.map((t) => `<div class="move"><span><span class="lab">Out</span><a class="out" href="#player-${t.out_id}">${esc(t.out)}</a></span><span class="arrow" aria-hidden="true">→</span><span><span class="lab">In</span><a class="in" href="#player-${t.in_id}">${esc(t.in)}</a></span></div>`).join("") || `<p class="move">No transfers this week.</p>`}</div>
      <div class="row-wrap">
        <a class="pill pill-cap" href="#player-${call.captain_id}">Captain ${esc(call.captain)}</a>
        <a class="pill" href="#player-${call.vice_id}">Vice ${esc(call.vice)}</a>
        <span class="pill">£${f1(call.bank_after)}m left</span>
        ${call.chip ? `<span class="pill">Chip: ${esc(call.chip)}</span>` : ""}
      </div>
      <div class="btn-row"><a href="#planner" data-act="plan-call" class="btn btn-primary">Try it in the planner</a><a href="#dataroom" class="btn btn-ghost-navy">Evidence</a></div>
    </section>
    <section class="section gutter" aria-labelledby="hl-h">
      <div style="display:flex;flex-direction:column;gap:2px"><h2 class="t-section" id="hl-h">This week's headlines</h2><span class="cap">Pick how deep you want to go on each one.</span></div>
      ${heads}
    </section>
    ${alert ? `<a href="#alerts" class="strip"><span class="dot" aria-hidden="true"></span><span>${esc(alert.text)}</span><span aria-hidden="true" style="margin-left:auto;font-size:18px">→</span></a>` : ""}
    ${nav("edition")}`;
  }

  // ---------- Squad ----------
  function vSquad() {
    const after = S.squadView === "after";
    const ids = after ? D.squad.after.ids : D.squad.ids;
    const xi = after ? D.squad.after.xi : D.squad.now.xi;
    const G = gws();
    const span = `GW${g0()} to GW${g1()}`;
    let body;
    if (S.squadMode === "heat") {
      const rows = ids.map((id) => { const p = P(id); const tot = G.reduce((s, g) => s + weekXp(p, g), 0); return { p, tot }; }).sort((a, b) => b.tot - a.tot);
      body = `<section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:8px">
        <div class="scrollx"><table class="heat"><thead><tr><th scope="col">Player</th><th scope="col">Total</th>${G.map((g) => `<th scope="col">${g}</th>`).join("")}</tr></thead><tbody>
        ${rows.map(({ p, tot }) => `<tr><td>${plink(p.id)}<br><span class="cap">${p.pos}</span></td><td class="tot">${f1(tot)}</td>${G.map((g) => { const x = weekXp(p, g); return `<td class="c ${heatCls(x)}">${oppLabel(p.w[g] ? p.w[g][1] : [])}<br><b>${f1(x)}</b></td>`; }).join("")}</tr>`).join("")}
        </tbody></table></div>
        <span class="cap">Projected points, GW${G[0]} to GW${G[G.length - 1]}, sorted by total. Scroll sideways for later weeks.</span></section>`;
    } else {
      body = ["GK", "DEF", "MID", "FWD"].map((pos) => {
        const rows = ids.filter((id) => P(id).pos === pos).sort((a, b) => P(b).h6 - P(a).h6);
        return `<section class="group gutter"><h2 class="t-h2">${POSPL[pos]}</h2>${rows.map((id) => {
          const p = P(id);
          const next = G.slice(0, 3).map((g) => { const x = weekXp(p, g); return `<span class="fxc ${heatCls(x)}"><span>${oppLabel(p.w[g] ? p.w[g][1] : [])}</span><b>${f1(x)}</b></span>`; }).join("");
          const isIn = after && buysInCall(id), isOut = !after && sellsInCall(id);
          const flag = p.status !== "a" || (p.chance != null && p.chance < 100);
          return `<a href="#player-${id}" class="pcard">
            <div class="pcard-top"><div><span class="pname">${esc(p.n)}</span><span class="cap">${p.t} · £${f1(p.cost)}m${after ? (xi.includes(id) ? " · Starting" : " · Bench") : ""}</span></div>
            <div class="pbig"><b>${f1(p.h6)}</b><span class="cap">6 GWs</span></div></div>
            <div class="fx3">${next}</div>
            <div class="row-wrap"><span class="tag tag-sunk">In ${Math.round(p.o_top || 0)}% of top 10k</span>
            ${p.xm < 75 ? `<span class="tag tag-red">Minutes risk: expects ${Math.round(p.xm)} mins</span>` : ""}
            ${flag ? `<span class="tag tag-red">${esc(p.news || "Flagged")}</span>` : ""}
            ${isIn ? `<span class="tag tag-green">Coming in</span>` : ""}${isOut ? `<span class="tag tag-orange">The call sells him</span>` : ""}</div>
          </a>`;
        }).join("")}</section>`;
      }).join("");
    }
    const ft = after ? `${D.squad.after.ft_left} free transfer${D.squad.after.ft_left === 1 ? "" : "s"} left` : `${D.state.free_transfers} free transfers`;
    const bank = after ? D.squad.after.bank : D.state.bank;
    return `<header class="squad-head gutter">
      <div class="phead-row"><h1 class="t-h1" tabindex="-1">Your squad</h1><span class="cap">${span}</span></div>
      <div role="group" aria-label="Which squad" class="seg">
        <button type="button" data-act="sq-view" data-v="now" aria-pressed="${!after}">As it is now</button>
        <button type="button" data-act="sq-view" data-v="after" aria-pressed="${after}">After the call</button>
      </div>
      <div role="group" aria-label="View" class="row-wrap" style="gap:6px">
        <button type="button" class="opt" data-act="sq-mode" data-v="cards" aria-pressed="${S.squadMode === "cards"}">Cards</button>
        <button type="button" class="opt" data-act="sq-mode" data-v="heat" aria-pressed="${S.squadMode === "heat"}">Heatmap, 10 GWs</button>
      </div>
      <div class="row-wrap"><span class="pill pill-light">${ft}</span><span class="pill pill-light">£${f1(bank)}m in the bank</span></div>
      <div class="legend"><span><i class="sw sw-hot" aria-hidden="true"></i>5+ pts</span><span><i class="sw sw-warm" aria-hidden="true"></i>4 to 5</span><span><i class="sw sw-cool" aria-hidden="true"></i>under 4</span><span>Capitals = home · tap a player for the profile</span></div>
    </header>${body}${nav("squad")}`;
  }

  // ---------- Planner: transfers ----------
  function planSummary(p) {
    if (!p.outs.length) return `No moves. ${p.ft_next} free transfers for GW${D.meta.gw + 1}.`;
    if (p.hits) { const extra = p.ins.filter((e) => !ED.call.transfers.some((t) => t.in_id === e)); const xo = p.outs.filter((e) => !ED.call.transfers.some((t) => t.out_id === e)); return `The call plus ${xo.map(nm).join(", ")} to ${extra.map(nm).join(", ")}, paid with a -${p.hits}.`; }
    const ins = p.ins.map(nm);
    const left = p.outs.length < D.state.free_transfers ? `One move now, ${p.ft_next} free transfers for GW${D.meta.gw + 1}.` : `No hit, £${f1(p.bank_after)}m left.`;
    return `${ins.length > 1 ? ins.slice(0, -1).join(", ") + " and " + ins[ins.length - 1] : ins[0]}. ${left}`;
  }
  function vPlanner() {
    const plans = D.plans;
    const sel = plans.find((p) => p.id === S.plan) || plans[0];
    const B = D.builder;
    const bOut = B.outs.includes(S.bOut) ? S.bOut : (ED.call.transfers[0] ? ED.call.transfers[0].out_id : B.outs[0]);
    const ins = B.ins[P(bOut).pos] || [];
    const bIn = ins.includes(S.bIn) ? S.bIn : (ins.includes(ED.call.transfers.find((t) => t.out_id === bOut)?.in_id) ? ED.call.transfers.find((t) => t.out_id === bOut).in_id : ins[0]);
    const r = B.gain[bOut + ">" + bIn];
    let result, gain;
    if (!r.legal) { result = `${nm(bOut)} to ${nm(bIn)} would put four players from one club in your squad. FPL allows three.`; gain = "Not allowed"; }
    else if (!r.ok) { result = `${nm(bOut)} to ${nm(bIn)} needs £${f1(-r.bank)}m more than you have.`; gain = "Too dear"; }
    else { result = `${nm(bOut)} to ${nm(bIn)}. Uses 1 of ${D.state.free_transfers} free transfers, £${f1(r.bank)}m left. Projected over 6 GWs:`; gain = sg(r.gain); }
    const moves = sel.outs.map((o, i) => `<div class="move"><span><span class="lab">Out</span><a class="out" href="#player-${o}">${esc(nm(o))}</a></span><span class="arrow" aria-hidden="true">→</span><span><span class="lab">In</span><a class="in" href="#player-${sel.ins[i]}">${esc(nm(sel.ins[i]))}</a></span></div>`).join("");
    return `<header class="phead gutter"><h1 class="t-h1" tabindex="-1">Planner</h1><p class="lede">Pick a plan to see what it does to the next six gameweeks. Gains are projections against making no transfers.</p></header>
    ${planTabs("planner")}
    <section class="navy" style="margin:0 20px;gap:14px">
      <div class="navy-head"><h2 class="t-section" style="font-size:20px;line-height:1.25">${esc(sel.name)}</h2><span class="gainbig">${sg(sel.gain)}</span></div>
      ${moves}
      ${!sel.outs.length ? `<p class="move">No transfers this week. ${D.state.free_transfers === 2 ? "Both free transfers roll" : "Your free transfers roll"} over.</p>` : ""}
      <div class="minis"><div class="mini"><b>${sel.hits ? "-" + sel.hits : "None"}</b><span>Hit</span></div><div class="mini"><b>£${f1(sel.bank_after)}m</b><span>Bank after</span></div><div class="mini"><b>${sel.ft_next}</b><span>FT in GW${D.meta.gw + 1}</span></div></div>
      <p class="body" style="font-size:15px;line-height:1.55">${esc(sel.verdict)}</p>
      <a href="https://fantasy.premierleague.com/transfers" target="_blank" rel="noopener" class="btn btn-primary">Make these moves in FPL ↗</a>
      <span class="cap">The app plans. You confirm transfers on the FPL site.</span>
    </section>
    <section class="gutter" style="padding-top:24px;padding-bottom:8px;display:flex;flex-direction:column;gap:10px">
      <h2 class="t-h2">Plans to compare</h2>
      ${plans.map((p) => `<button type="button" class="plan" data-act="plan" data-id="${p.id}" aria-pressed="${p.id === sel.id}"><span class="plan-top"><span class="plan-name">${esc(p.name)}</span><span class="plan-gain">${sg(p.gain)}</span></span><span class="plan-sum">${esc(planSummary(p))}</span></button>`).join("")}
      <button type="button" class="btn btn-ghost" style="margin-top:6px" data-act="build" aria-expanded="${S.build}">${S.build ? "Close my own plan" : "Build my own plan"}</button>
      ${S.build ? `<div class="builder">
        <span class="step">1. Who goes out</span>
        <div class="row-wrap" style="gap:6px">${B.outs.map((o) => `<button type="button" class="opt opt-sunk" data-act="b-out" data-id="${o}" aria-pressed="${o === bOut}">${esc(nm(o))}</button>`).join("")}</div>
        <span class="step">2. Who comes in</span>
        <div class="row-wrap" style="gap:6px">${ins.map((i) => `<button type="button" class="opt opt-sunk" data-act="b-in" data-id="${i}" aria-pressed="${i === bIn}">${esc(nm(i))} <span class="cap">£${f1(P(i).cost)}m</span></button>`).join("")}</div>
        <div class="result" aria-live="polite"><span>${esc(result)}</span><b>${gain}</b></div>
      </div>` : ""}
    </section>${nav("planner")}`;
  }

  // ---------- Planner: captain ----------
  function vCaptain() {
    const capId = ED.call.captain_id;
    const cap = P(capId);
    const pool = D.captain_pool.slice().sort((a, b) => weekXp(P(b), D.meta.gw) - weekXp(P(a), D.meta.gw));
    if (!pool.includes(S.cap)) S.cap = pool.find((e) => e !== capId) || capId;
    const s = P(S.cap);
    const gw = D.meta.gw;
    const H = weekXp(cap, gw);
    const d = weekXp(s, gw) - H;
    const capShare = Math.round(cap.cap_top || 0);
    const eo = Math.round(cap.eo_top || 0);
    const opp = (p) => oppLabel(p.w[gw] ? p.w[gw][1] : []);
    return `<header class="phead gutter" style="padding-bottom:14px"><h1 class="t-h1" tabindex="-1">Planner</h1><p class="lede">Who gets the armband in GW${gw}.</p></header>
    ${planTabs("captain")}
    <section class="navy" style="margin:0 20px;gap:12px">
      <div class="row-wrap"><a class="pill pill-cap" href="#player-${capId}">Captain ${esc(ED.call.captain)}</a><a class="pill" href="#player-${ED.call.vice_id}">Vice ${esc(ED.call.vice)}</a></div>
      <p class="body">${capShare}% of the top 10k captained ${esc(cap.n)} in GW${D.ownership.sample_gw}, so his effective ownership there is ${eo}%. If you go elsewhere and he scores 10, you drop about ${Math.round(10 * (eo / 100 - 1))} points against them.</p>
    </section>
    <section class="gutter" style="padding-top:24px;padding-bottom:8px;display:flex;flex-direction:column;gap:10px">
      <div style="display:flex;flex-direction:column;gap:2px"><h2 class="t-h2">Compare the options</h2><span class="cap">Tap one to see what happens if you captain them instead.</span></div>
      ${pool.map((id) => { const p = P(id); return `<button type="button" class="plan" data-act="cap" data-id="${id}" aria-pressed="${id === S.cap}" style="gap:6px">
        <span class="plan-top"><span class="plan-name">${esc(p.n)} <span style="font-weight:500;color:var(--ink-subtle)">v ${opp(p)}</span></span><span class="plan-gain">${f1(weekXp(p, gw))}</span></span>
        <span class="plan-grid"><span>Haul ${p.haul}%</span><span>Blank ${p.blank}%</span><span>EO ${Math.round(p.eo_top || 0)}%</span></span></button>`; }).join("")}
      <span class="cap">Projected points from the v0 model. Haul is 10 or more, blank is 2 or fewer, from ${intl(D.meta.sims)} simulated games. EO is effective ownership in the top 10k, captaincy counted twice.</span>
    </section>
    <section class="card" style="margin:8px 20px 20px;gap:12px">
      <h2 class="t-h2">${S.cap === capId ? "Captaining " + esc(cap.n) : "Captaining " + esc(s.n) + " instead"}</h2>
      ${S.cap === capId ? `<p class="muted">You match ${capShare}% of the top 10k. You only gain or lose on ${esc(cap.n)} against the ${100 - capShare}% who went elsewhere.</p>`
        : `<div class="swing-good">If ${esc(cap.n)} scores 2 and ${esc(s.n)} scores 10, you gain about 8 on most of the top 10k.</div>
           <div class="swing-bad">If ${esc(cap.n)} scores 12 and ${esc(s.n)} scores 2, you lose about 10.</div>
           <p class="muted">The model has ${esc(s.n)} ${Math.abs(d).toFixed(1)} ${d >= 0 ? "ahead of" : "behind"} ${esc(cap.n)} this week. It underrates premium forwards, so treat a gap under 1.5 as a tie.</p>`}
      <a href="#player-${S.cap}" class="textlink">${esc(s.n)} profile →</a>
    </section>${nav("planner")}`;
  }

  // ---------- Planner: chips ----------
  function vChips() {
    const CP = D.chip_plan;
    const used = Object.fromEntries((D.manager.chips_used || []).map((c) => [c.name, c.gw]));
    const fhDone = used.freehit != null;
    const sel = CP.chips.find((c) => c.id === S.chip) || CP.chips[0];
    const ev19 = D.events.find((e) => e.gw === 19);
    const exp = ev19 ? uk(ev19.deadline, { day: "numeric", month: "short" }) + " " + uk(ev19.deadline, { hour: "2-digit", minute: "2-digit", hour12: false }) + " UK" : "";
    const tile = (k, l) => used[k] != null ? `<div class="chiptile"><b>${l}</b><span>Used GW${used[k]}</span></div>` : `<div class="chiptile"><b>${l}</b><span>Left</span></div>`;
    const cells = [];
    const tags = Object.assign({}, CP.forecast);
    CP.festive.forEach((g) => (tags[g] = "Xmas"));
    for (let g = D.meta.gw; g <= 38; g++) {
      const cls = sel.win.includes(g) ? "best" : CP.forecast[g] ? "fc" : CP.festive.includes(g) ? "fest" : "";
      cells.push(`<div class="${cls}"><span>${g}</span><span>${tags[g] || ""}</span></div>`);
    }
    return `<header class="phead gutter" style="padding-bottom:14px"><h1 class="t-h1" tabindex="-1">Planner</h1><p class="lede">Where each chip earns the most this season.</p></header>
    ${planTabs("chips")}
    <section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:10px">
      <h2 class="t-h2">First set, until GW19</h2>
      <div class="chiptiles">${tile("bboost", "Bench Boost")}${tile("wildcard", "Wildcard")}${tile("3xc", "Triple Captain")}
        ${fhDone ? `<div class="chiptile"><b>Free Hit</b><span>Used GW${used.freehit}</span></div>` : `<a href="#freehit" class="chiptile"><b>Free Hit</b><span>Left · plan GW18 or 19 →</span></a>`}</div>
      <span class="cap">Unused first-set chips expire at the GW19 deadline, ${exp}.</span>
    </section>
    <section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:10px">
      <div style="display:flex;flex-direction:column;gap:2px"><h2 class="t-h2">The season calendar</h2><span class="cap">Tap a chip to see its best window.</span></div>
      <div role="group" aria-label="Chip" class="row-wrap" style="gap:6px">${CP.chips.map((c) => `<button type="button" class="opt" data-act="chip" data-id="${c.id}" aria-pressed="${c.id === sel.id}">${esc(c.label)}</button>`).join("")}</div>
      <div class="cal">${cells.join("")}</div>
      <div class="legend"><span><i class="sw sw-hot" aria-hidden="true"></i>Best window</span><span><i class="sw sw-blue" aria-hidden="true"></i>BGW blank, DGW double (forecast)</span><span><i class="sw sw-warm" aria-hidden="true"></i>Festive run</span></div>
    </section>
    <section class="navy" style="margin:0 20px 20px;padding:18px;gap:8px" aria-live="polite">
      <span style="font:700 14px/1.3 var(--font-text);color:var(--accent-on-navy)">${esc(sel.label)}</span>
      <p style="font:700 18px/1.4 var(--font-display)">${esc(sel.when)}</p>
      <p class="body">${esc(sel.why)}</p>
    </section>
    <section class="note-orange" style="margin:0 20px 20px"><h2 class="t">How firm is this</h2><p>The second-half blanks and doubles are forecasts from the cup schedules. They move with cup results, and the app updates this calendar as soon as a fixture is moved.</p></section>
    ${nav("planner")}`;
  }

  // ---------- Planner: finder ----------
  function priceTag(p) {
    if (p.pcp >= 90) return `<span class="ptag up">Rising soon</span>`;
    if (p.pcp <= -80) return `<span class="ptag down">Falling soon</span>`;
    return `<span class="ptag">Price steady</span>`;
  }
  function vFinder() {
    const cap = S.fCap === "99" ? 99 : Number(S.fCap);
    const G = gws();
    const res = Object.values(D.players).filter((p) => p.pos === S.fPos && p.cost <= cap && !mine(p.id) && p.xm >= 60).sort((a, b) => b.h6 - a.h6).slice(0, 5);
    const pos = [["DEF", "Defenders"], ["MID", "Midfielders"], ["FWD", "Forwards"]];
    const pr = [["5.5", "£5.5m"], ["7.0", "£7.0m"], ["99", "Any"]];
    return `<header class="phead gutter" style="padding-bottom:14px"><h1 class="t-h1" tabindex="-1">Planner</h1><p class="lede">Find the best players you don't own yet.</p></header>
    ${planTabs("finder")}
    <section class="gutter" style="padding-bottom:12px;display:flex;flex-direction:column;gap:10px">
      <span style="font:700 15px/1.3 var(--font-text)">Position</span>
      <div role="group" aria-label="Position" class="row-wrap" style="gap:6px">${pos.map(([id, l]) => `<button type="button" class="opt opt-lg" data-act="f-pos" data-v="${id}" aria-pressed="${S.fPos === id}">${l}</button>`).join("")}</div>
      <span style="font:700 15px/1.3 var(--font-text)">Most you can spend</span>
      <div role="group" aria-label="Price" class="row-wrap" style="gap:6px">${pr.map(([id, l]) => `<button type="button" class="opt opt-lg" data-act="f-cap" data-v="${id}" aria-pressed="${S.fCap === id}">${l}</button>`).join("")}</div>
    </section>
    <section class="gutter" style="padding-top:8px;padding-bottom:20px;display:flex;flex-direction:column;gap:10px">
      <span class="cap">Ranked by projected points, GW${g0()} to GW${g1()}. Players expected to play under 60 minutes are left out.</span>
      ${res.map((p) => `<a href="#player-${p.id}" class="fcard"><span class="fcard-top"><span><b style="font-size:17px">${esc(p.n)}</b><span class="cap">${p.t} · £${f1(p.cost)}m · next ${G.slice(0, 3).map((g) => oppLabel(p.w[g] ? p.w[g][1] : [])).join(" ")}</span></span><span><b class="big">${f1(p.h6)}</b><span class="cap">6 GWs</span></span></span>
        <span class="row-wrap" style="gap:6px"><span class="ptag">Expects ${Math.round(p.xm)} mins</span><span class="ptag">Top 10k ${Math.round(p.o_top || 0)}%</span>${priceTag(p)}</span></a>`).join("") || `<p class="cap">No one fits this filter.</p>`}
      <a href="#dataroom-fixtures" class="textlink">Fixture heatmap: data room, Fixtures tab →</a>
    </section>${nav("planner")}`;
  }

  // ---------- Data room ----------
  const PG = {
    attack: { label: "Attack", note: "Goals and the chances behind them. G minus xG above zero means finishing better than the chances, which tends to cool.", cols: ["xG", "Goals", "G − xG", "xG/90", "Threat"], key: 3,
      f: (r) => [f2(r.xg), r.g, sg(r.g - r.xg), f2(r.min ? (r.xg * 90) / r.min : 0), Math.round(r.thr)], k: (r) => (r.min ? (r.xg * 90) / r.min : 0), sortLabel: "xG per 90" },
    create: { label: "Creating", note: "Expected assists and creativity. A minus xA far above zero usually means teammates finished well.", cols: ["xA", "Assists", "A − xA", "xA/90", "Creativity"], key: 3,
      f: (r) => [f2(r.xa), r.a, sg(r.a - r.xa), f2(r.min ? (r.xa * 90) / r.min : 0), Math.round(r.cre)], k: (r) => (r.min ? (r.xa * 90) / r.min : 0), sortLabel: "xA per 90" },
    defend: { label: "Defending", note: "Defensive contributions earn 2 points at 10 per game for defenders, 12 for midfielders and forwards (recoveries count for them).", cols: ["DefCon/90", "CBI", "Tackles", "Recoveries", "Clean sheets"], key: 0,
      f: (r) => [f1(r.dc90), r.cbi, r.tck, r.rec, r.cs], k: (r) => r.dc90, sortLabel: "DefCon per 90", noGK: true },
    mins: { label: "Minutes", note: "Who actually plays. Expected minutes are the model's blend of recent games and injury flags; minutes in each of the last four games arrive with the next weekly run.", cols: ["Minutes", "Starts", "Per game", "Expected"], key: 3,
      f: (r) => [r.min, r.starts, Math.round(r.min / Math.max(1, team(r.tid).gp)), Math.round(r.xm)], k: (r) => r.xm, sortLabel: "expected minutes next game" },
    bonus: { label: "Bonus & ICT", note: "BPS decides who gets the 3, 2 and 1 bonus. ICT combines influence, creativity and threat.", cols: ["Bonus", "BPS", "ICT", "Influence"], key: 1,
      f: (r) => [r.bonus, r.bps, f1(r.ict), Math.round(r.inf)], k: (r) => r.bps, sortLabel: "BPS" },
    form: { label: "Form & value", note: "Form is average points over the last four. Value is total points per £m.", cols: ["Points", "Per game", "Form", "Pts/£m", "xP 6 GW"], key: 4,
      f: (r) => [r.pts, f1(r.ppg), f1(r.form), f1(r.pts / r.cost), f1(r.h6)], k: (r) => r.h6, sortLabel: "projected points, next 6" },
    own: { label: "Price & ownership", note: "Ownership near your rank matters more than overall. Transfers are this gameweek so far.", cols: ["£m", "Since GW1", "Top 10k", "Everyone", "In", "Out"], key: 2,
      f: (r) => [f1(r.cost), sg(r.chg), Math.round(r.o_top || 0) + "%", f1(r.sel) + "%", Math.round(r.tin / 1000) + "k", Math.round(r.tout / 1000) + "k"], k: (r) => r.o_top || 0, sortLabel: "top 10k ownership" },
    events: { label: "Duels & dribbles", soon: true, note: "Event data that the FPL feed does not carry.", sortLabel: "nothing yet" }
  };
  const TG = {
    table: { label: "Table", note: "Standings after GW" + "%LAST%" + ", with the last five results.", cols: ["Pts", "W-D-L", "GD", "Form"], key: 0, f: (r) => [r.pts, `${r.w}-${r.d}-${r.l}`, sg(r.gf - r.ga, 0).replace("−0", "0"), r.form], k: (r) => -r.pos, sortLabel: "league position" },
    attack: { label: "Attack", note: "Chance creation per game this season. Goals above xG tends to cool.", cols: ["xG", "Goals", "G − xG", "xG rank"], key: 0, f: (r) => [f2(r.xgf), r.gf, sg(r.gf - r.xg_total), ord(r.xgf_rank)], k: (r) => r.xgf, sortLabel: "xG per game", soon: true },
    defence: { label: "Defence", note: "Chances given up per game. Low xG against plus clean sheets is where defenders and keepers come from.", cols: ["xG against", "Conceded", "Clean sheets", "Rank"], key: 0, f: (r) => [f2(r.xga), r.ga, r.cs, ord(r.xga_rank)], k: (r) => -r.xga, sortLabel: "xG against per game (lowest first)", soon: true },
    form: { label: "Form", note: "xG difference per game this season. Last-four splits need per-match xG, which the nightly archive builds up from 3 Nov; they appear here from GW13.", cols: ["xGD", "xG for", "xG against", "Pts"], key: 0, f: (r) => [sg(r.xgf - r.xga, 2), f2(r.xgf), f2(r.xga), r.pts], k: (r) => r.xgf - r.xga, sortLabel: "season xG difference per game" },
    venue: { label: "Home & away", note: "Points per game at home and away.", cols: ["Home", "Away", "Gap"], key: 0, f: (r) => [f2(r.hppg || 0), f2(r.appg || 0), sg((r.hppg || 0) - (r.appg || 0), 2)], k: (r) => r.hppg || 0, sortLabel: "home points per game" }
  };
  function storyActions(h) {
    const a = h.evidence.action || {};
    if (a.kind === "freehit") return `<a href="#freehit" class="textlink">${esc(a.label)} →</a>`;
    if (a.kind === "team") return `<a href="#team-${a.team}" class="textlink">${esc(a.label)} →</a>`;
    if (a.kind === "planner") return `<a href="#planner" data-act="plan-call" class="textlink">${esc(a.label)} →</a>`;
    if (a.kind === "captain") return `<a href="#captain" class="textlink">${esc(a.label)} →</a>`;
    if (a.kind === "gw9") return `<button type="button" class="linkbtn" data-act="gw9">${S.gw9 ? "Show the summary" : esc(a.label)}</button>`;
    if (a.kind === "players-own") return `<button type="button" class="linkbtn" data-act="to-own">${esc(a.label)}</button>`;
    return "";
  }
  function vDataRoom(sub) {
    if (sub && sub.startsWith("story-")) { S.tab = "stories"; }
    else if (sub && ["stories", "players", "teams", "fixtures", "own", "model"].includes(sub)) S.tab = sub;
    const tabs = [["stories", "Stories"], ["players", "Players"], ["teams", "Teams"], ["fixtures", "Fixtures"], ["own", "Ownership"], ["model", "Model"]];
    let body = "";
    const lastGw = D.last_gw.gw;
    if (S.tab === "stories") {
      body = `<section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:12px"><p class="muted" style="font-size:15px">The evidence for each headline, in the order they appear in the edition.</p>
      ${ED.headlines.map((h) => {
        let facts = h.evidence.facts.map((f) => [esc(f.k), esc(f.v)]);
        if (h.evidence.action && h.evidence.action.kind === "gw9" && S.gw9) {
          facts = D.last_gw.my_players.slice().sort((a, b) => (b.multiplier > 0) - (a.multiplier > 0) || b.points * Math.max(1, b.multiplier) - a.points * Math.max(1, a.multiplier))
            .map((p) => [p.multiplier === 0 ? "Bench: " + plink(p.id, p.name) : plink(p.id, p.name) + (p.multiplier > 1 ? " (captain)" : ""), p.multiplier > 1 ? `${p.points} × ${p.multiplier}` : p.points]);
        }
        const read = ED.reads.find((r) => r.id === h.read);
        const deep = read && read.deep ? ED.data_room.find((x) => x.id === read.deep) : null;
        return `<article class="card card-16" id="dr-${h.id}"><span class="tag ${tagFor(h.tone)}">${esc(h.kicker)}</span><h2 class="t-story">${esc(h.title)}</h2>${kv(facts)}<span class="cap">Source: ${esc(h.evidence.src)}</span>
        ${deep && !deep.bottom_line ? `<div class="readlayer"><h3 class="t-h2">${esc(deep.title)}</h3><div class="md">${md(deep.body)}</div></div>` : ""}
        ${storyActions(h)}</article>`;
      }).join("")}</section>`;
    } else if (S.tab === "players") {
      const g = PG[S.pgroup];
      let table = "";
      if (!g.soon) {
        const rows = D.watch.map(P).filter((r) => !(g.noGK && r.pos === "GK")).sort((a, b) => g.k(b) - g.k(a));
        table = `<div class="scrollx"><table class="tbl"><thead><tr><th scope="col">Player</th>${g.cols.map((c) => `<th scope="col">${c}</th>`).join("")}</tr></thead><tbody>
        ${rows.map((r, i) => `<tr><td>${plink(r.id)}<br><span class="sub">${r.t} ${r.pos}${mine(r.id) ? " · yours" : ""}</span></td>${g.f(r).map((v, j) => `<td class="${j === g.key ? (i < 3 ? "top3" : "key") : ""}">${v}</td>`).join("")}</tr>`).join("")}
        </tbody></table></div>`;
      } else {
        table = v1box("Connects in v1", "Chances created, big chances created, successful dribbles and %, duels won and %, aerial duels won and %, touches in the box, interceptions, dispossessed, xG on target, shots and shots on target.", "From Understat (shots, key passes) and FotMob (the rest). Touch heatmaps from Sofascore.");
      }
      body = `<section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:12px">
        <div role="group" aria-label="Player metrics" class="row-wrap" style="gap:6px">${Object.keys(PG).map((id) => `<button type="button" class="opt" data-act="pgroup" data-id="${id}" aria-pressed="${S.pgroup === id}">${PG[id].label}</button>`).join("")}</div>
        <p class="muted" style="font-size:15px">${esc(g.note)}</p>${table}
        <span class="cap">${g.soon ? "Arrives when Understat and FotMob connect." : `Your squad, this week's targets and the template. Sorted by ${g.sortLabel}. Orange marks the top three. Tap a name for the full profile.`}</span></section>`;
    } else if (S.tab === "teams") {
      const g = TG[S.tgroup];
      const rows = Object.values(D.teams).slice().sort((a, b) => g.k(b) - g.k(a));
      body = `<section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:12px">
        <div role="group" aria-label="Team metrics" class="row-wrap" style="gap:6px">${Object.keys(TG).map((id) => `<button type="button" class="opt" data-act="tgroup" data-id="${id}" aria-pressed="${S.tgroup === id}">${TG[id].label}</button>`).join("")}</div>
        <p class="muted" style="font-size:15px">${esc(g.note.replace("%LAST%", lastGw))}</p>
        <div class="scrollx"><table class="tbl tbl-full"><thead><tr><th scope="col">#</th><th scope="col" class="l">Team</th>${g.cols.map((c) => `<th scope="col">${c}</th>`).join("")}</tr></thead><tbody>
        ${rows.map((r, i) => `<tr><td>${i + 1}</td><td class="l"><a href="#team-${r.id}">${r.short}</a></td>${g.f(r).map((v, j) => `<td class="${j === g.key ? (i < 3 ? "top3" : "key") : ""}">${v}</td>`).join("")}</tr>`).join("")}
        </tbody></table></div>
        ${g.soon ? `<div class="note-blue" style="padding:14px 16px;font-size:15px">Shots for and against, shots in the box, big chances, PPDA (pressing) and deep completions connect in v1 from Understat and FotMob. Distance covered has no free source we can confirm.</div>` : ""}
        <span class="cap">Ranked by ${g.sortLabel}. xG figures per game, our calculation from FPL player data. Tap a team for its profile.</span></section>`;
    } else if (S.tab === "fixtures") {
      const att = S.tick === "att";
      const G = gws();
      const N = S.run;
      const shade = (x, lo, hi) => { const t = Math.max(0, Math.min(1, (x - lo) / (hi - lo))); return t > 0.66 ? "h-hot" : t > 0.33 ? "h-warm" : "h-white"; };
      const rows = Object.values(D.teams).map((t) => {
        const cells = G.map((g) => {
          const fx = t.next[g] || [];
          if (!fx.length) return { opp: "none", v: "–", cls: "h-white", val: 0 };
          const gsum = fx.reduce((s, x) => s + x.g, 0), csAvg = fx.reduce((s, x) => s + x.cs, 0) / fx.length;
          return { opp: fx.map((x) => (x.home ? x.opp.toUpperCase() : x.opp.toLowerCase())).join("+"), v: att ? f1(gsum) : Math.round(csAvg) + "%", cls: att ? shade(gsum / fx.length, 1.1, 2.1) : shade(csAvg, 15, 38), val: att ? gsum : csAvg };
        });
        const avg = cells.slice(0, N).reduce((s, c) => s + c.val, 0) / N;
        return { t, cells, avg };
      }).sort((a, b) => b.avg - a.avg);
      body = `<section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:12px">
        <div role="group" aria-label="Fixture view" class="seg"><button type="button" data-act="tick" data-v="att" aria-pressed="${att}">Goals expected</button><button type="button" data-act="tick" data-v="def" aria-pressed="${!att}">Clean sheet chance</button></div>
        <div role="group" aria-label="Rank by run" class="row-wrap" style="gap:6px"><span class="cap">Easiest run, next</span>${[3, 6, 10].map((n) => `<button type="button" class="opt" data-act="run" data-v="${n}" aria-pressed="${N === n}">${n} GWs</button>`).join("")}</div>
        <div class="scrollx"><table class="tbl"><thead><tr><th scope="col">Team</th><th scope="col">Avg</th>${G.map((g) => `<th scope="col" style="text-align:center">${g}</th>`).join("")}</tr></thead><tbody>
        ${rows.map(({ t, cells, avg }) => `<tr><td><a href="#team-${t.id}">${t.short}</a></td><td class="key">${att ? f2(avg) : Math.round(avg) + "%"}</td>${cells.map((c) => `<td class="hc ${c.cls}">${c.opp}<br><b>${c.v}</b></td>`).join("")}</tr>`).join("")}
        </tbody></table></div>
        <div class="legend"><span><i class="sw sw-hot" aria-hidden="true"></i>Best</span><span><i class="sw sw-warm" aria-hidden="true"></i>Good</span><span><i class="sw sw-white" aria-hidden="true"></i>Harder</span><span>Capitals are home games</span></div>
        <span class="cap">Projections from the v0 model: each team's expected goals and clean-sheet chance per fixture.</span></section>`;
    } else if (S.tab === "own") {
      const O = D.ownership;
      const rows = D.watch.map(P).sort((a, b) => (b.o_top || 0) - (a.o_top || 0));
      const you = (r) => sellsInCall(r.id) ? ["Selling", "you-mid"] : buysInCall(r.id) ? ["Buying", "you-mid"] : mine(r.id) ? ["Yes", "you-yes"] : ["No", "you-no"];
      body = `<section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:14px">
        <h2 class="t-h2">Who your rivals own</h2>
        <div class="scrollx"><table class="tbl tbl-full"><thead><tr><th scope="col">Player</th><th scope="col">Top 10k</th><th scope="col">Near you</th><th scope="col">Everyone</th><th scope="col">You</th></tr></thead><tbody>
        ${rows.map((r) => { const [y, c] = you(r); return `<tr><td>${plink(r.id)}</td><td>${Math.round(r.o_top || 0)}%</td><td>${Math.round(r.o_peer || 0)}%</td><td>${f1(r.sel)}%</td><td class="key ${c}">${y}</td></tr>`; }).join("")}
        </tbody></table></div>
        <div class="card card-16" style="gap:8px"><h3 class="t-h2" style="font-size:17px">Captaincy in the top 10k, GW${O.sample_gw}</h3>
        ${O.captain_top.slice(0, 3).map(([v, id]) => `<div class="capbar"><span>${plink(id)}</span><span class="track"><span class="fill" style="width:${v}%"></span></span><b>${Math.round(v)}%</b></div>`).join("")}</div>
        <span class="cap">Sample: ${O.n_top} teams from the top 10k and ${O.n_peer} ranked around ${intl(O.peer_rank)}, read on ${ist(D.meta.pulled_at, { day: "numeric", month: "short" })}. In GW${O.sample_gw}, ${Math.round((100 * (O.chips_top.freehit || 0)) / O.n_top)}% of the sampled top 10k played their Free Hit.</span></section>`;
    } else {
      body = `<section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:12px">
        <div class="card card-16" style="gap:8px"><h2 class="t-h2">What the projections use</h2><p>Team attack from total xG, team defence from xG conceded, each player's xG, xA, bonus and saves per 90, defensive contributions for the DefCon bonus, and expected minutes from recent games and injury flags. All from the official FPL data for now.</p></div>
        <div class="note-orange"><h2 class="t">Known weak spots</h2><p>No rotation model yet, no betting odds, and it underrates big hauls from premium forwards. That is why captaincy and close calls get a human check in the edition.</p></div>
        <div class="note-green"><h2 class="t">Track record</h2><p>Starts this week. After each gameweek, every projection is scored against real points and shown here.</p></div>
        <span class="cap">Model ${esc(D.meta.model.version)} · each later week weighted ${Math.round((1 - D.meta.model.decay) * 100)}% less in plan scoring · data pulled ${pulled()}</span></section>`;
    }
    return `<header class="phead gutter" style="padding-bottom:14px"><span class="cap">GW${D.meta.gw} · data pulled ${pulledShort()}</span><h1 class="t-h1" tabindex="-1">Data room</h1><p class="lede">Every number behind this week's edition, so you can check the call yourself.</p></header>
    <div role="tablist" aria-label="Data room sections" class="row-wrap gutter" style="gap:6px;padding-bottom:16px">${tabs.map(([id, l]) => `<button type="button" role="tab" class="opt" data-act="tab" data-id="${id}" aria-selected="${S.tab === id}">${l}</button>`).join("")}</div>
    ${body}${nav("")}`;
  }

  // ---------- Player profile ----------
  function vPlayer(id) {
    const p = P(id);
    if (!p) return `<div class="page gutter">${back("dataroom", "Back")}<h1 class="t-h1">Player not found</h1><p>This player has no minutes and no projection this season.</p></div>`;
    const t = team(p.tid);
    const gw = D.meta.gw;
    const xgi90 = p.min ? ((p.xg + p.xa) * 90) / p.min : 0;
    const line = p.pos === "DEF" ? 10 : 12;
    const tags = [];
    if (buysInCall(id)) tags.push(`<span class="tag tag-green">In the call this week</span>`);
    if (sellsInCall(id)) tags.push(`<span class="tag tag-orange">The call sells him</span>`);
    else if (mine(id)) tags.push(`<span class="tag tag-green">In your squad</span>`);
    if (p.news) tags.push(`<span class="tag tag-red">${esc(p.news)}</span>`);
    if (p.cor && p.cor <= 3) tags.push(`<span class="tag tag-plain">Corners ${ord(p.cor)}</span>`);
    if (p.dfk && p.dfk <= 3) tags.push(`<span class="tag tag-plain">Free kicks ${ord(p.dfk)}</span>`);
    if (p.pen && p.pen <= 3) tags.push(`<span class="tag tag-plain">Penalties ${ord(p.pen)}</span>`);
    // what the numbers say
    const peers = Object.values(D.players).filter((x) => x.pos === p.pos && x.min >= 450);
    const rank = peers.filter((x) => (x.xg + x.xa) / x.min > (p.xg + p.xa) / Math.max(p.min, 1)).length + 1;
    let say = "";
    if (p.pos === "GK") say = `He has ${p.cs} clean sheets and ${p.saves} saves in ${p.min} minutes. ${esc(t.name)} allow ${f2(t.xga)} xG a game, ${ord(t.xga_rank)} best in the league.`;
    else {
      const diff = p.g - p.xg;
      say = `${xgi90.toFixed(2)} xG plus xA per 90 ranks ${ord(rank)} of ${peers.length} ${POSPL[p.pos].toLowerCase()} with 450+ minutes, and ${esc(t.name)} create ${f2(t.xgf)} xG a game, ${ord(t.xgf_rank)} in the league. `;
      say += Math.abs(diff) < 0.75 ? `${p.g} goals from ${f1(p.xg)} xG is in line with his chances.` : diff > 0 ? `${p.g} goals from ${f1(p.xg)} xG means he has finished above his chances, so the model expects fewer goals than so far, not more.` : `${p.g} goals from ${f1(p.xg)} xG means he has finished below his chances, so goals may pick up if the chances keep coming.`;
      if (p.pos !== "FWD") say += ` DefCon: ${f1(p.dc90)} per 90 against a line of ${line}.`;
    }
    // breakdown
    const parts = p.parts || {};
    const PC = [["appearance", "Appearance", "c-app"], ["goals", "Goals", "c-goals"], ["bonus", "Bonus", "c-bonus"], ["assists", "Assists", "c-assists"], ["clean_sheet", "Clean sheet", "c-cs"], ["defcon", "DefCon", "c-defcon"], ["saves", "Saves", "c-saves"]].filter(([k]) => (parts[k] || 0) >= 0.05);
    const tot = weekXp(p, gw);
    const posSum = PC.reduce((s, [k]) => s + parts[k], 0);
    const conceded = parts.conceded || 0;
    const M = {
      attack: ["Attacking", [["Goals", p.g], ["xG", f2(p.xg)], ["Goals minus xG", sg(p.g - p.xg)], ["xG per 90", f2(p.min ? (p.xg * 90) / p.min : 0)], ["Threat (ICT)", Math.round(p.thr)], ["Penalty order", p.pen ? ord(p.pen) : "Not on the list"]]],
      create: ["Creating", [["Assists", p.a], ["xA", f2(p.xa)], ["Assists minus xA", sg(p.a - p.xa)], ["xA per 90", f2(p.min ? (p.xa * 90) / p.min : 0)], ["Creativity (ICT)", Math.round(p.cre)], ["Corners and free kicks", p.cor ? ord(p.cor) : "Not on the list"]]],
      defend: ["Defending", [["DefCon per 90", `${f1(p.dc90)} (line ${p.pos === "GK" ? "n/a" : line})`], ["Clearances, blocks, interceptions", p.cbi], ["Tackles", p.tck], ["Recoveries", p.rec], ["Clean sheets", p.cs], ["xG conceded per 90", f2(p.min ? (p.xgc * 90) / p.min : 0)]].concat(p.pos === "GK" ? [["Saves per 90", f2(p.min ? (p.saves * 90) / p.min : 0)]] : [])],
      mins: ["Minutes", [["Minutes", p.min], ["Starts", `${p.starts} of ${t.gp}`], ["Last four games", p.hist ? p.hist.slice(-4).map((r) => r[2]).join(", ") : "Logged from the next weekly run"], ["Expected next game", Math.round(p.xm)]]],
      bonus: ["Bonus & ICT", [["Bonus points", p.bonus], ["BPS", p.bps], ["ICT index", f1(p.ict)], ["Influence", Math.round(p.inf)]]],
      form: ["Value & form", [["Points", p.pts], ["Per game", f1(p.ppg)], ["Form, last four", f1(p.form)], ["Points per £m", f1(p.pts / p.cost)], ["Home / away per game", p.hist ? homeAway(p.hist) : "Logged from the next weekly run"]]],
      price: ["Price & transfers", [["Price", `£${f1(p.cost)}m (${sg(p.chg)} since GW1)`], ["Bought this gameweek", intl(p.tin)], ["Sold this gameweek", intl(p.tout)], ["Progress to a " + (p.pcp < 0 ? "fall" : "rise"), Math.round(Math.abs(p.pcp)) + "%"], ["Effective ownership: top 10k / near you", `${Math.round(p.eo_top || 0)}% / ${Math.round(p.eo_peer || 0)}%`]]]
    };
    const mg = M[S.pmg] || M.attack;
    const events = [["Shots and shots on target", "Understat"], ["Key passes (chances created)", "Understat"], ["Big chances created", "FotMob"], ["Successful dribbles and %", "FotMob"], ["Duels won and %", "FotMob"], ["Aerial duels won and %", "FotMob"], ["Touches in the box", "FotMob"], ["Interceptions", "FotMob"], ["Dispossessed", "FotMob"], ["xG on target", "FotMob"]];
    const next = gws().slice(0, 6).map((g) => { const fx = t.next[g] || []; return { g, opp: oppLabel(p.w[g] ? p.w[g][1] : []), xp: f1(weekXp(p, g)), tg: fx.length ? f2(fx.reduce((s, x) => s + x.g, 0)) : "–", cs: fx.length ? Math.round(fx.reduce((s, x) => s + x.cs, 0) / fx.length) + "%" : "–" }; });
    const prog = p.pcp >= 0 ? `${Math.round(p.pcp)}%${(p.pc0 || 0) >= 100 ? ", likely tonight" : ", not tonight"}` : `${Math.round(-p.pcp)}% toward a fall${(p.pc0 || 0) <= -100 ? ", likely tonight" : ", not tonight"}`;
    let hist;
    if (p.hist && p.hist.length) {
      const H = p.hist.slice(-9);
      const shortOf = (tid) => (team(tid) ? team(tid).short : "");
      hist = `<div role="img" aria-label="Points by gameweek: ${H.map((r) => "GW" + r[0] + " " + r[1]).join(", ")}" class="bars" style="grid-template-columns:repeat(${H.length},minmax(0,1fr));height:130px">${H.map((r) => `<div><span>${r[1]}</span><div class="${r[1] >= 8 ? "hi" : ""}" style="height:${Math.max(4, (r[1] / 12) * 100).toFixed(0)}px"></div></div>`).join("")}</div>
      <div class="barlabels" style="grid-template-columns:repeat(${H.length},minmax(0,1fr));font-size:12px">${H.map((r) => `<span style="display:flex;flex-direction:column"><span>${r[4] ? shortOf(r[3]) : shortOf(r[3]).toLowerCase()}</span><b style="color:var(--ink)">${f1(r[5])}</b></span>`).join("")}</div>`;
    } else {
      hist = `<div class="note-blue" style="padding:14px 16px"><span>Per-match points and xG start with the next weekly run, which now saves each player's match history. The GW${D.meta.gw} run was made before that step existed.</span></div>`;
    }
    return `<div class="page gutter">
      ${back("dataroom", "Data room")}
      <header style="display:flex;flex-direction:column;gap:10px"><span class="cap">${POSNAME[p.pos]} · ${esc(t.name)} · £${f1(p.cost)}m</span><h1 class="t-h1x" tabindex="-1">${esc(p.n)}</h1><div class="row-wrap">${tags.join("")}</div></header>
      <section class="tiles">
        <div class="tile tile-w"><b>${p.pts}</b><span>Points, ${t.gp} games</span></div>
        <div class="tile tile-w"><b>${p.g} from ${f1(p.xg)}</b><span>Goals from xG</span></div>
        <div class="tile tile-w"><b>${xgi90.toFixed(2)}</b><span>xG + xA per 90</span></div>
        <div class="tile tile-w"><b>${p.bonus}</b><span>Bonus points</span></div>
        <div class="tile tile-w"><b>${Math.round(p.min / Math.max(1, t.gp))}</b><span>Minutes a game</span></div>
        ${p.pos === "GK" ? `<div class="tile tile-w"><b>${f2(p.min ? (p.saves * 90) / p.min : 0)}</b><span>Saves per 90</span></div>` : `<div class="tile tile-w"><b>${f1(p.dc90)}</b><span>DefCon per 90 (line ${line})</span></div>`}
      </section>
      <section class="card card-16"><h2 class="t-h2">What the numbers say</h2><p>${say}</p></section>
      <section class="card card-16" style="gap:12px">
        <div class="phead-row"><h2 class="t-h2">GW${gw} projection, broken down</h2><span style="font:800 22px/1 var(--font-display)">${f1(tot)}</span></div>
        ${PC.length ? `<div class="stack" role="img" aria-label="${PC.map(([k, l]) => l + " " + f1(parts[k])).join(", ")}">${PC.map(([k, , c]) => `<span class="${c}" style="width:${((parts[k] / posSum) * 100).toFixed(1)}%"></span>`).join("")}</div>
        <div class="parts">${PC.map(([k, l, c]) => `<span><span class="sq ${c}" aria-hidden="true"></span><span>${l}</span><b>${f1(parts[k])}</b></span>`).join("")}${conceded <= -0.05 ? `<span><span class="sq" aria-hidden="true"></span><span>Goals conceded</span><b>${sg(conceded)}</b></span>` : ""}</div>` : `<p class="muted">No GW${gw} fixture or no expected minutes, so nothing to break down.</p>`}
        ${p.haul != null ? `<div class="odds"><div class="good"><b>${p.haul}%</b><span>Chance of 10+ points</span></div><div class="bad"><b>${p.blank}%</b><span>Chance of 2 or fewer</span></div></div><span class="cap">From ${intl(D.meta.sims)} simulated games of the v0 model.</span>` : ""}
      </section>
      <section class="card card-16" style="gap:12px"><h2 class="t-h2">Every number</h2>
        <div role="group" aria-label="Metric group" class="row-wrap" style="gap:6px">${Object.keys(M).map((k) => `<button type="button" class="opt opt-sm opt-sunk" data-act="pmg" data-id="${k}" aria-pressed="${S.pmg === k}">${M[k][0]}</button>`).join("")}</div>
        <div class="kv">${mg[1].map(([k, v]) => `<div><span class="k">${k}</span><span class="v">${v}</span></div>`).join("")}</div>
        <span class="cap">Source: official FPL data, read ${pulledShort()}.</span>
      </section>
      <section class="card card-16"><div class="phead-row" style="align-items:center"><h2 class="t-h2">Where he plays</h2>${live("sofascore") ? "" : `<span class="tag tag-blue tag-sm">Connects in v1</span>`}</div>
        <div class="pitch" role="img" aria-label="Empty pitch: touch heatmap arrives in v1"><i class="mid"></i><i class="circ"></i><i class="boxl"></i><i class="boxr"></i><span class="txt">Season touch heatmap, attacking left to right</span></div>
        <span class="cap">From Sofascore, season and per match.</span></section>
      <section class="card card-16"><div class="phead-row" style="align-items:center"><h2 class="t-h2">Duels, dribbles and chances</h2>${live("fotmob") ? "" : `<span class="tag tag-blue tag-sm">Connects in v1</span>`}</div>
        ${kv(events.map(([k, s]) => [k, s, true]))}</section>
      <section class="card card-16"><div style="display:flex;flex-direction:column"><h2 class="t-h2">Points by gameweek</h2><span class="cap">Orange bars are 8 points or more. Under each bar: opponent, then that game's xG plus xA.</span></div>${hist}</section>
      <section class="card card-16" style="gap:8px"><h2 class="t-h2">Next six</h2>
        <table class="tbl tbl-full" style="white-space:normal"><thead><tr><th scope="col">GW</th><th scope="col" class="l">Opp</th><th scope="col">Projected</th><th scope="col">${t.short} goals</th><th scope="col">Clean sheet</th></tr></thead><tbody>
        ${next.map((n) => `<tr><td>${n.g}</td><td class="l">${n.opp}</td><td class="key">${n.xp}</td><td>${n.tg}</td><td>${n.cs}</td></tr>`).join("")}</tbody></table>
        <span class="cap">Capitals are home games. ${t.short} goals is the team's expected goals in that match. All projections, v0 model.</span></section>
      <section class="card card-16"><h2 class="t-h2">Ownership and price</h2>
        ${kv([["Top 10k", Math.round(p.o_top || 0) + "%"], ["Managers near your rank", Math.round(p.o_peer || 0) + "%"], ["Everyone", f1(p.sel) + "%"], ["Bought this gameweek", intl(p.tin)], ["Progress to a price " + (p.pcp < 0 ? "fall" : "rise"), prog]])}</section>
      <div class="btn-row"><a href="#planner" class="btn btn-primary">See him in the planner</a><a href="#ask" class="btn btn-ghost" data-act="ask-about" data-id="${id}">Ask</a></div>
      <span class="foot">Model ${esc(D.meta.model.version)} · data pulled ${pulled()}</span>
    </div>`;
  }
  function homeAway(h) {
    const hm = h.filter((r) => r[4] && r[2] > 0), aw = h.filter((r) => !r[4] && r[2] > 0);
    const a = (x) => (x.length ? f1(x.reduce((s, r) => s + r[1], 0) / x.length) : "–");
    return `${a(hm)} / ${a(aw)}`;
  }

  // ---------- Team profile ----------
  function vTeam(id) {
    const t = team(id);
    if (!t) return `<div class="page gutter">${back("dataroom", "Data room")}<h1 class="t-h1">Team not found</h1></div>`;
    const G = gws();
    const players = Object.values(D.players).filter((p) => p.tid === t.id && p.xm >= 45).sort((a, b) => b.h6 - a.h6).slice(0, 4);
    const all = Object.values(D.players).filter((p) => p.tid === t.id);
    const sp = (k) => all.find((p) => p[k] === 1);
    const cor = sp("cor"), pen = sp("pen");
    const dcMid = all.filter((p) => p.pos === "MID" && p.min >= 270 && p.dc90 >= 12).sort((a, b) => b.dc90 - a.dc90)[0];
    const xgd = t.xgf - t.xga;
    const xgdRank = Object.values(D.teams).filter((x) => x.xgf - x.xga > xgd).length + 1;
    const say = `${ord(t.pos)} on ${t.pts} points, ${ord(xgdRank)} on xG difference (${sg(xgd, 2)} a game). They create ${f2(t.xgf)} xG a game (${ord(t.xgf_rank)}) and allow ${f2(t.xga)} (${ord(t.xga_rank)}). ` +
      (t.pos - xgdRank >= 4 ? "The underlying numbers are better than the table suggests." : xgdRank - t.pos >= 4 ? "The table flatters them; the chances say they are weaker than their position." : "The table and the chances roughly agree.");
    const next = G.map((g) => { const fx = t.next[g] || []; const gg = fx.reduce((s, x) => s + x.g, 0); const cs = fx.length ? Math.round(fx.reduce((s, x) => s + x.cs, 0) / fx.length) : 0; const tt = (gg / Math.max(1, fx.length) - 1.1) / 1.0; return { g, opp: fx.map((x) => (x.home ? x.opp.toUpperCase() : x.opp.toLowerCase())).join("+") || "none", gg: fx.length ? f1(gg) : "–", cs, cls: tt > 0.66 ? "h-hot" : tt > 0.33 ? "h-warm" : "h-white" }; });
    const resName = { W: "won", D: "drawn", L: "lost" };
    return `<div class="page gutter">
      ${back("dataroom", "Data room")}
      <header style="display:flex;flex-direction:column;gap:8px"><span class="cap">${ord(t.pos)} · ${t.pts} points · won ${t.w}, drawn ${t.d}, lost ${t.l}</span><h1 class="t-h1x" tabindex="-1">${esc(t.name)}</h1>
        <div class="form5" aria-label="Last five results: ${t.form.split("").map((r) => resName[r]).join(", ")}"><span class="cap" style="margin-right:4px">Last five</span>${t.form.split("").map((r) => `<i class="f-${r}" aria-hidden="true">${r}</i>`).join("")}</div></header>
      <section class="navy" style="padding:16px;gap:6px;border-radius:18px"><span style="font:700 14px/1.3 var(--font-text);color:var(--accent-on-navy)">What the numbers say</span><p>${say}</p></section>
      <section style="display:flex;flex-direction:column;gap:8px"><h2 class="t-h2">This season</h2>
        <div class="scrollx"><table class="tbl tbl-full"><thead><tr><th scope="col">Per game</th><th scope="col">Season</th><th scope="col">League rank</th></tr></thead><tbody>
        <tr><td>xG for</td><td>${f2(t.xgf)}</td><td>${ord(t.xgf_rank)}</td></tr>
        <tr><td>xG against</td><td>${f2(t.xga)}</td><td>${ord(t.xga_rank)}</td></tr>
        <tr><td>Goals for</td><td>${f2(t.gf / t.gp)}</td><td>${t.gf} total</td></tr>
        <tr><td>Goals against</td><td>${f2(t.ga / t.gp)}</td><td>${t.ga} total</td></tr>
        <tr><td>Clean sheets</td><td>${t.cs} of ${t.gp}</td><td>–</td></tr>
        <tr><td>Points, home / away</td><td>${f2(t.hppg || 0)} / ${f2(t.appg || 0)}</td><td>–</td></tr></tbody></table></div>
        <span class="cap">Last-four splits appear from GW13, once the nightly archive holds four weeks of per-match xG.</span></section>
      <section style="display:flex;flex-direction:column;gap:8px"><h2 class="t-h2">Next ten</h2>
        <div class="next10">${next.map((n) => `<div class="${n.cls}"><span>GW${n.g}</span><b>${n.opp}</b><span>${n.gg} · ${n.cs}%</span></div>`).join("")}</div>
        <span class="cap">Each box: their expected goals · clean-sheet chance, from the v0 model. Darker is better.</span></section>
      <section style="display:flex;flex-direction:column;gap:8px"><h2 class="t-h2">Who to own</h2>
        <div class="scrollx"><table class="tbl tbl-full"><thead><tr><th scope="col">Player</th><th scope="col">£m</th><th scope="col">xGI</th><th scope="col">DefCon/90</th><th scope="col">xP 6 GW</th></tr></thead><tbody>
        ${players.map((p) => `<tr><td>${plink(p.id)}${mine(p.id) ? ` <span class="sub">· yours</span>` : ""}</td><td>${f1(p.cost)}</td><td>${f2(p.xgi)}</td><td>${f1(p.dc90)}</td><td class="key">${f1(p.h6)}</td></tr>`).join("")}</tbody></table></div>
        <span class="cap">${cor ? `Set pieces: ${esc(cor.n)} takes corners${pen ? ` and ${esc(pen.n)} is first on penalties` : ""}. ` : ""}${dcMid ? `${esc(dcMid.n)} averages ${f1(dcMid.dc90)} defensive actions per 90, over the midfield DefCon line of 12, and expects ${Math.round(dcMid.xm)} minutes.` : ""}</span></section>
      ${v1box("Connects in v1", "Shots and shots conceded, shots in the box, big chances, pressing (PPDA), deep completions and set-piece goals, from Understat and FotMob.")}
      <a href="#finder" class="btn btn-primary" data-act="finder-team">Find players to buy</a>
      <span class="foot">Model ${esc(D.meta.model.version)} · data pulled ${pulled()}</span>
    </div>`;
  }

  // ---------- Free Hit story ----------
  function vFreeHit() {
    const d = ED.data_room.find((x) => x.bottom_line) || {};
    const C = D.free_hit;
    const max = Math.max(...C.map((c) => c.gain), 1) * 1.12;
    return `<div class="page gutter" style="gap:20px;line-height:1.65">
      ${back("dataroom", "Data room")}
      <header style="display:flex;flex-direction:column;gap:10px"><span class="tag tag-orange">Story evidence · Free Hit</span><h1 class="t-h1" tabindex="-1">${esc(d.title || "Free Hit")}</h1><p class="lede">${esc(d.intro || "")}</p></header>
      <section class="navy" style="padding:18px;gap:6px;border-radius:18px"><span style="font:700 14px/1.3 var(--font-text);color:var(--accent-on-navy)">Bottom line</span><p style="font:700 19px/1.4 var(--font-display)">${esc(d.bottom_line || "")}</p></section>
      <section class="card" style="gap:12px"><div style="display:flex;flex-direction:column;gap:2px"><h2 class="t-h2">Projected gain by gameweek</h2><span class="cap">Free Hit team minus your current best XI, in points</span></div>
        <div role="img" aria-label="Gains: ${C.map((c) => "GW" + c.gw + " " + f1(c.gain)).join(", ")}" class="bars" style="grid-template-columns:repeat(${C.length},minmax(0,1fr));gap:4px;height:170px">
        ${C.map((c) => `<div><span>${f1(c.gain)}</span><div class="${c.gw === d.recommended ? "hi" : c.gw === d.fallback ? "fb" : ""}" style="height:${((c.gain / max) * 140).toFixed(0)}px"></div></div>`).join("")}</div>
        <div class="barlabels" style="grid-template-columns:repeat(${C.length},minmax(0,1fr))">${C.map((c) => `<span>${c.gw}</span>`).join("")}</div>
        <div class="legend"><span><i class="sw sw-hot" aria-hidden="true"></i>Recommended</span><span><i class="sw sw-light" aria-hidden="true"></i>Fallback</span><span><i class="sw sw-muted" aria-hidden="true"></i>Other weeks</span></div></section>
      <div class="md">${md(d.body)}</div>
      <section class="note-orange"><h2 class="t">How sure we are</h2><p>${esc(d.confidence || "")}</p></section>
      <span class="foot">Model ${esc(D.meta.model.version)} · data pulled ${pulled()}</span>
    </div>`;
  }

  // ---------- Alerts ----------
  function vAlerts() {
    const rows = D.alerts.map((a) => {
      const p = P(a.id);
      const why = a.selling ? "You own him · the call sells him" : a.buying ? `In the call · £${f1(p.cost)}m` : a.owned ? "You own him" : (D.template.includes(a.id) ? "Template target" : "Target") + ` · £${f1(p.cost)}m`;
      const when = a.tonight ? (a.dir === "up" ? "Rising tonight" : "Falling tonight") : "Building";
      const note = a.dir === "up"
        ? (a.tonight ? (a.buying ? "Buy before tonight's update to pay the current price." : "Not in this week's plan. Buying him now would cost a hit.") : "Not tonight. Buying before the deadline is fine.")
        : (a.selling ? (a.tonight ? "Falling tonight. You are selling him this week, so sell before the update." : "Heading down, but not tonight. You are selling him this week anyway.") : a.owned ? (a.tonight ? "Falling tonight. Sell before the update only if you planned to anyway." : "Slow drift down. No action needed this week.") : "Falling. Cheaper to buy later if you want him.");
      const cls = a.tonight ? (a.dir === "up" ? "tag-orange" : "tag-red") : "tag-sunk";
      return `<a href="#player-${a.id}" class="acard"><div class="acard-top"><span><span class="pname">${esc(p.n)}</span><span class="cap">${esc(why)}</span></span><span class="tag ${cls}" style="flex:none">${when}</span></div>
        <div class="prog" role="img" aria-label="${a.dir === "up" ? "Rise" : "Fall"} progress ${a.pct} percent"><div class="${a.dir}" style="width:${Math.min(100, a.pct)}%"></div></div><span class="muted" style="font-size:14px">${esc(note)}</span></a>`;
    }).join("");
    const flagged = D.squad.ids.map(P).filter((p) => p.status !== "a" || p.news);
    const dl = new Date(ED.deadline_utc);
    return `<header class="phead gutter"><h1 class="t-h1" tabindex="-1">Alerts</h1><p class="lede">Prices change every night at 05:30 IST. Only players you own or plan to buy. Tap one for the profile.</p></header>
    <section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:10px"><h2 class="t-h2">Progress toward the next price change</h2>${rows || `<p class="muted">Nothing close to a change.</p>`}
      <span class="cap">Progress figures come from the FPL feed, read ${pulledShort()}, and are provisional until we have logged a few weeks of real changes.</span></section>
    <section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:10px"><h2 class="t-h2">Injuries and news</h2>
      ${flagged.length ? flagged.map((p) => `<a href="#player-${p.id}" class="strip red" style="margin:0"><span class="dot" aria-hidden="true"></span><span><b>${esc(p.n)}</b>: ${esc(p.news || "flagged")}</span></a>`).join("") : `<div class="note-green" style="padding:14px 16px">No injury or suspension flags in your squad right now.</div>`}</section>
    <section class="gutter" style="padding-bottom:20px;display:flex;flex-direction:column;gap:10px"><h2 class="t-h2">Deadline</h2>
      <a href="#edition" class="dcard"><b>GW${ED.gw} locks ${ist(dl, { weekday: "short", day: "numeric", month: "short" })}, ${ist(dl, { hour: "2-digit", minute: "2-digit", hour12: false })} IST</b><span class="s">Final team-news check runs 3 hours before.</span><span class="go">Open this week's edition →</span></a></section>
    ${nav("alerts")}`;
  }

  // ---------- Archive ----------
  function vArchive() {
    const H = D.manager.history;
    let chart = "";
    if (H.length > 1) {
      const W = 310, x0 = 10, x1 = 300, yTop = 12, yBot = 112;
      const lg = (r) => Math.log10(r);
      const lo = lg(Math.min(...H.map((h) => h.rank))) - 0.05, hi = lg(Math.max(...H.map((h) => h.rank))) + 0.05;
      const pts = H.map((h, i) => [x0 + ((x1 - x0) * i) / (H.length - 1), yTop + ((lg(h.rank) - lo) / (hi - lo)) * (yBot - yTop)]);
      const worst = H.reduce((a, b) => (b.rank > a.rank ? b : a));
      const wi = H.indexOf(worst), last = pts[pts.length - 1];
      const k = (r) => (r >= 1e6 ? f1(r / 1e6) + "m" : r >= 1e4 ? Math.round(r / 1000) + "k" : intl(r));
      chart = `<svg viewBox="0 0 ${W} 140" width="100%" role="img" aria-label="Overall rank by gameweek: ${H.map((h) => "GW" + h.gw + " " + intl(h.rank)).join(", ")}">
        <line x1="10" y1="120" x2="300" y2="120" stroke="var(--line)" stroke-width="1"/>
        <polyline fill="none" stroke="var(--ink)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="${pts.map((p) => p.map((v) => v.toFixed(1)).join(",")).join(" ")}"/>
        <circle cx="${pts[wi][0]}" cy="${pts[wi][1]}" r="4" fill="var(--chart-muted)"/>
        <circle cx="${last[0]}" cy="${last[1]}" r="5" fill="var(--orange)"/>
        <text x="${pts[wi][0] + 10}" y="${Math.min(pts[wi][1] + 4, 116)}" font-size="13" fill="var(--ink-subtle)" font-family="Atkinson Hyperlegible Next, sans-serif">${k(worst.rank)} after GW${worst.gw}</text>
        <text x="${last[0] - 8}" y="${Math.max(last[1] + 18, 26)}" font-size="13" fill="var(--ink)" font-weight="700" text-anchor="end" font-family="Atkinson Hyperlegible Next, sans-serif">${k(H[H.length - 1].rank)} after GW${H[H.length - 1].gw}</text>
        <text x="10" y="136" font-size="12" fill="var(--ink-subtle)" font-family="Atkinson Hyperlegible Next, sans-serif">GW${H[0].gw}</text>
        <text x="300" y="136" font-size="12" fill="var(--ink-subtle)" text-anchor="end" font-family="Atkinson Hyperlegible Next, sans-serif">GW${H[H.length - 1].gw}</text></svg>
        <span class="cap">Higher on the chart is a better rank (log scale). From your FPL history.</span>`;
    }
    const eds = IDX.editions.slice().sort((a, b) => b.gw - a.gw);
    return `<div class="page gutter" style="gap:20px">
      ${back("edition", "This week's edition")}
      <header style="display:flex;flex-direction:column;gap:6px"><h1 class="t-h1" tabindex="-1">Past editions</h1><p class="lede">Every edition, and how its call turned out.</p></header>
      <section class="card"><div class="phead-row"><h2 class="t-h2">Your season so far</h2><span class="cap">Overall rank</span></div>${chart}</section>
      <section style="display:flex;flex-direction:column;gap:10px"><h2 class="t-h2">Editions</h2>
        ${eds.map((e) => `<a href="#edition-${e.gw}" class="ecard"><span class="phead-row" style="align-items:center"><span class="tag ${e.gw === IDX.current ? "tag-orange" : e.graded ? "tag-green" : "tag-sunk"}">${e.gw === IDX.current ? "This week" : e.graded ? "Graded" : "Awaiting grade"}</span><span class="cap">Edition ${e.edition} · GW${e.gw}</span></span><span class="t">${esc(e.title)}</span><span class="muted" style="font-size:15px">${e.graded ? esc(e.grade_summary || "Graded") : `Graded once GW${e.gw}'s last match is played.`}</span></a>`).join("")}
      </section>
      <section class="note-green"><h2 class="t">How grading works</h2><p>The week after each edition, we check the call against what happened: points from the players brought in against the players sold, the captain's return, and whether the model's projections were close. Over a season this shows how far to trust it.</p></section>
    </div>`;
  }

  // ---------- Ask ----------
  const ASKS = () => {
    const gw = D.meta.gw;
    const cap = P(ED.call.captain_id);
    const pool = D.captain_pool.map(P).sort((a, b) => weekXp(b, gw) - weekXp(a, gw));
    const top = pool.find((p) => p.id !== cap.id) || cap;
    const diffs = D.squad.after.ids.map(P).filter((p) => (p.o_top || 0) < 30 && p.pos !== "GK").sort((a, b) => b.h6 - a.h6);
    const dp = diffs[0];
    const posRank = Object.values(D.players).filter((x) => x.pos === dp.pos && x.h6 > dp.h6).length + 1;
    const wc = D.chip_plan.chips.find((c) => c.id === "wc2");
    return [
      { id: "cap", short: `Captain ${top.n}?`, q: `Should I captain ${top.n} over ${cap.n} this week?`, lead: `Keep the armband on ${cap.n}.`,
        body: `The model has ${top.n} at ${f1(weekXp(top, gw))} and ${cap.n} at ${f1(weekXp(cap, gw))} for GW${gw}, but it underrates premium forwards and the gap is under our 1.5 point bar. ${Math.round(cap.cap_top || 0)}% of the top 10k captained ${cap.n} in GW${D.ownership.sample_gw}, so if he hauls and you went elsewhere, you lose ground on almost everyone near you.`,
        src: `GW${gw} projections, ${D.ownership.n_top} sampled top 10k teams`, link: "#captain" },
      { id: "diff", short: `Keep ${dp.n}?`, q: `Is ${dp.n} a keeper or a sell?`, lead: `Keep him. He is one of your best differentials.`,
        body: `${dp.n} projects ${f1(dp.h6)} points over the next six gameweeks, ${ord(posRank)} among ${POSPL[dp.pos].toLowerCase()}. Only ${Math.round(dp.o_top || 0)}% of the top 10k own him, so his returns gain you ground.`,
        src: `GW${g0()} to GW${g1()} projections, ${D.ownership.n_top} sampled top 10k teams`, link: "#player-" + dp.id },
      { id: "wc", short: "Next Wildcard?", q: "When should I play my second Wildcard?", lead: "Most likely just before the second-half doubles.",
        body: `Your second Wildcard unlocks at GW20. Blanks and doubles are forecast for GW30, GW32, GW33 and GW35 or 36. ${wc ? wc.why : ""} We will firm this up once the cup draws set the doubles.`,
        src: "2026/27 rules, blank and double gameweek forecast", link: "#chips" }
    ];
  };
  function vAsk() {
    const qs = ASKS();
    const A = S.ask;
    if (!A.q && !A.custom) A.q = qs[0].id;
    let cur;
    if (A.custom) cur = A.answer ? Object.assign({ q: A.custom }, A.answer) : { q: A.custom, lead: A.busy ? "Thinking..." : "", body: A.busyText || "", src: "", link: null };
    else { const x = qs.find((y) => y.id === A.q) || qs[0]; cur = x; }
    return `<header class="phead gutter" style="padding-bottom:12px"><h1 class="t-h1" tabindex="-1">Ask the agent</h1><p class="lede">Answers come from this week's data and your squad.</p></header>
    <section class="row-wrap gutter" style="padding-bottom:16px">${qs.map((x) => `<button type="button" class="opt" data-act="ask-q" data-id="${x.id}" aria-pressed="${!A.custom && A.q === x.id}">${esc(x.short)}</button>`).join("")}</section>
    <section class="gutter" style="display:flex;flex-direction:column;gap:12px" aria-live="polite">
      <div class="bubble-q">${esc(cur.q)}</div>
      <div class="bubble-a"><p class="lead">${esc(cur.lead)}</p>${cur.body ? `<p class="muted">${esc(cur.body)}</p>` : ""}${cur.src ? `<span class="src">From: ${esc(cur.src)}</span>` : ""}
        ${cur.link ? `<a href="${cur.link.startsWith("#") ? cur.link : "#dataroom"}" class="textlink">See the evidence →</a>` : ""}
        ${A.busy ? `<button type="button" class="linkbtn" data-act="ask-stop">Stop</button>` : ""}</div>
    </section>
    <form class="askform" data-act="ask-form" novalidate>
      <label for="ask-input" class="sr">Your question</label>
      <input id="ask-input" type="text" value="${esc(A.draft)}" aria-describedby="ask-error" placeholder="Ask about a player, fixture or plan" autocomplete="off">
      <button type="submit"${A.busy ? " disabled" : ""}>Ask</button>
    </form>
    <p id="ask-error" class="askerr">${esc(A.err)}</p>
    ${nav("ask")}`;
  }

  let askCtl = null;
  function askContext() {
    const gw = D.meta.gw;
    const brief = (p) => ({ id: p.id, name: p.n, team: p.t, pos: p.pos, price: p.cost, proj_next6: p.h6, proj_gw: f1(weekXp(p, gw)), exp_mins: Math.round(p.xm),
      next3: gws().slice(0, 3).map((g) => oppLabel(p.w[g] ? p.w[g][1] : [])).join(", "), own_top10k: Math.round(p.o_top || 0), own_near_rank: Math.round(p.o_peer || 0), news: p.news || undefined });
    const best = {};
    ["GK", "DEF", "MID", "FWD"].forEach((pos) => { best[pos] = Object.values(D.players).filter((p) => p.pos === pos && !mine(p.id) && p.xm >= 60).sort((a, b) => b.h6 - a.h6).slice(0, 6).map(brief); });
    return {
      gameweek: gw, deadline_utc: ED.deadline_utc, horizon: `GW${g0()} to GW${g1()}`,
      manager: { rank: ED.status.overall_rank, gap_to_top10k: ED.status.gap_top10k, free_transfers: D.state.free_transfers, bank: D.state.bank, chips_left: ED.status.chips_left },
      the_call: { transfers: ED.call.transfers.map((t) => `${t.out} out, ${t.in} in: ${t.why}`), captain: ED.call.captain, vice: ED.call.vice, projected_gain: ED.call.projected_gain },
      plans: D.plans.map((p) => ({ name: p.name, gain: p.gain, hit: p.hits, verdict: p.verdict })),
      squad: D.squad.ids.map(P).map(brief),
      best_unowned_by_position: best,
      price_alerts: D.alerts.map((a) => ({ name: nm(a.id), direction: a.dir, progress_pct: a.pct, likely_tonight: a.tonight })),
      chip_plan: D.chip_plan.chips.map((c) => ({ chip: c.label, when: c.when })),
      headlines: ED.headlines.map((h) => h.title + ": " + h.dek)
    };
  }
  function findPlayer(name) {
    const q = String(name || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const hits = Object.values(D.players).filter((p) => norm(p.n).includes(q) || norm(p.first + " " + p.last).includes(q)).sort((a, b) => b.min - a.min).slice(0, 3);
    return hits.map((p) => ({ id: p.id, name: p.n, full_name: p.first + " " + p.last, team: p.t, pos: p.pos, price: p.cost, status: p.status, news: p.news,
      season: { minutes: p.min, starts: p.starts, goals: p.g, assists: p.a, xg: p.xg, xa: p.xa, points: p.pts, bonus: p.bonus, defcon_per90: p.dc90, form: p.form },
      projections: gws().slice(0, 6).map((g) => ({ gw: g, opp: oppLabel(p.w[g] ? p.w[g][1] : []), xp: weekXp(p, g) })), proj_next6: p.h6, exp_mins: Math.round(p.xm),
      haul_pct: p.haul, blank_pct: p.blank, own_top10k: p.o_top, own_near_rank: p.o_peer, eo_top10k: p.eo_top, price_progress_pct: Math.round(p.pcp), in_squad: mine(p.id) }));
  }
  function findTeam(name) {
    const q = String(name || "").toLowerCase();
    const t = Object.values(D.teams).find((x) => x.short.toLowerCase() === q || x.name.toLowerCase().includes(q));
    if (!t) return { error: "No team matches " + name };
    return { name: t.name, short: t.short, position: t.pos, points: t.pts, record: `${t.w}-${t.d}-${t.l}`, xg_for_per_game: t.xgf, xg_against_per_game: t.xga, form: t.form,
      next: gws().map((g) => ({ gw: g, fixtures: (t.next[g] || []).map((x) => ({ opp: x.opp, home: x.home, exp_goals: x.g, clean_sheet_pct: x.cs })) })) };
  }
  async function ask(text) {
    const A = S.ask;
    const sample = window.claude && window.claude.use ? await window.claude.use("sample").catch(() => null) : null;
    if (!sample) { A.answer = { lead: "Asking your own questions needs the Claude app.", body: "Open this page in Claude to ask anything. The suggested questions above work everywhere.", src: "", link: null }; A.busy = false; render(); return; }
    askCtl = new AbortController();
    const prompt = `You are the AlooSoul FPL agent, answering the manager's question from this week's data only.
Rules: plain, direct language, short sentences. Never use em dashes. Never say a player "will" score or rise; say "projects", "likely" or "the model expects". Label projections as projections. Give every number context (over how many gameweeks, against what). The v0 model underrates premium forwards' hauls and minutes are its weakest input; say so when it matters. If the data cannot answer, say what is missing. Use the lookup tools for any player or team not in the summary.
Answer as JSON only: {"lead": "one-sentence answer, 15 words or fewer", "body": "2 to 4 sentences of reasoning with numbers", "src": "which data you used, a few words", "player_id": number or null}

This week's data:
${JSON.stringify(askContext())}

Question: ${text}`;
    const tools = [
      { name: "lookup_player", description: "Season stats, projections for the next six gameweeks, ownership and price progress for players matching a name.", inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] }, execute: (i) => findPlayer(i.name) },
      { name: "lookup_team", description: "League position, xG for and against, and the next ten fixtures for a team (name or three-letter code).", inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] }, execute: (i) => findTeam(i.name) }
    ];
    try {
      const { text: out } = await sample(prompt, { tools, signal: askCtl.signal, cache: false, onText: () => { if (A.busyText !== "Writing the answer...") { A.busyText = "Writing the answer..."; render(); } } });
      const m = out.match(/\{[\s\S]*\}/);
      let j = null;
      try { j = m ? JSON.parse(m[0]) : null; } catch (e) { j = null; }
      A.answer = j ? { lead: j.lead || "", body: j.body || "", src: j.src || "this week's data", link: j.player_id ? "#player-" + j.player_id : "#dataroom" } : { lead: out.slice(0, 200), body: "", src: "this week's data", link: "#dataroom" };
    } catch (e) {
      const copy = { not_granted: "Claude was not allowed to answer. The suggested questions above still work.", rate_limited: "Too many questions at once. Wait a minute, then ask again.", aborted: "Stopped." };
      A.answer = { lead: copy[e && e.code] || "Could not get an answer this time.", body: e && e.text ? e.text : "", src: "", link: null };
    } finally { A.busy = false; A.busyText = ""; askCtl = null; render(); }
  }

  // ---------- router ----------
  function route() {
    const h = (location.hash || "#edition").slice(1);
    const [name, ...rest] = h.split("-");
    const arg = rest.join("-");
    return { name, arg, raw: h };
  }
  let lastRoute = null;
  async function render(scrollTop) {
    const r = route();
    let html;
    if (r.name === "edition" && r.arg && Number(r.arg) !== ED.gw) {
      const e = IDX.editions.find((x) => x.gw === Number(r.arg));
      if (e) { ED = await getJSON(e.file); D = await getJSON(e.data); }
    } else if ((r.name === "edition" && !r.arg) && ED.gw !== IDX.current) {
      const e = IDX.editions.find((x) => x.gw === IDX.current); ED = await getJSON(e.file); D = await getJSON(e.data);
    }
    switch (r.name) {
      case "squad": html = vSquad(); break;
      case "planner": html = vPlanner(); break;
      case "captain": html = vCaptain(); break;
      case "chips": html = vChips(); break;
      case "finder": html = vFinder(); break;
      case "dataroom": html = vDataRoom(r.arg); break;
      case "player": html = vPlayer(r.arg); break;
      case "team": html = vTeam(r.arg); break;
      case "freehit": html = vFreeHit(); break;
      case "ask": html = vAsk(); break;
      case "alerts": html = vAlerts(); break;
      case "archive": html = vArchive(); break;
      default: html = vEdition();
    }
    const app = $("#app");
    const active = document.activeElement && document.activeElement.id;
    app.innerHTML = html;
    const titles = { edition: "Edition", squad: "Squad", planner: "Planner", captain: "Captain", chips: "Chips", finder: "Finder", dataroom: "Data room", player: r.arg && P(r.arg) ? P(r.arg).n : "Player", team: r.arg && team(r.arg) ? team(r.arg).name : "Team", freehit: "Free Hit", ask: "Ask", alerts: "Alerts", archive: "Archive" };
    document.title = "AlooSoul FPL · " + (titles[r.name] || "Edition");
    if (scrollTop) {
      if (r.arg && r.arg.startsWith("story-")) { const el = document.getElementById("dr-" + r.arg.slice(6)); if (el) { el.scrollIntoView(); el.setAttribute("tabindex", "-1"); el.focus({ preventScroll: true }); } }
      else { window.scrollTo(0, 0); const h1 = app.querySelector("h1"); if (h1 && lastRoute !== null) { h1.setAttribute("tabindex", "-1"); h1.focus({ preventScroll: true }); } }
    } else if (active) { const el = document.getElementById(active); if (el) { el.focus(); if (el.setSelectionRange) el.setSelectionRange(el.value.length, el.value.length); } }
    lastRoute = r.raw;
  }

  window.addEventListener("hashchange", () => {
    const r = route().raw;
    if (trail[trail.length - 2] === r) trail.pop(); else trail.push(r);
    render(true);
  });

  // ---------- events ----------
  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-act]");
    if (!el) return;
    const a = el.dataset.act;
    const id = el.dataset.id;
    const keep = (fn) => { fn(); render(false); };
    switch (a) {
      case "depth": depth[id] = Number(el.dataset.n); store.set("depth-gw" + ED.gw, depth); keep(() => {}); break;
      case "plan-call": S.plan = "call"; break;
      case "sq-view": keep(() => (S.squadView = el.dataset.v)); break;
      case "sq-mode": keep(() => (S.squadMode = el.dataset.v)); break;
      case "plan": keep(() => (S.plan = id)); break;
      case "build": keep(() => (S.build = !S.build)); break;
      case "b-out": keep(() => { S.bOut = Number(id); S.bIn = null; }); break;
      case "b-in": keep(() => (S.bIn = Number(id))); break;
      case "cap": keep(() => (S.cap = Number(id))); break;
      case "chip": keep(() => (S.chip = id)); break;
      case "f-pos": keep(() => (S.fPos = el.dataset.v)); break;
      case "f-cap": keep(() => (S.fCap = el.dataset.v)); break;
      case "tab": ev.preventDefault(); if (location.hash !== "#dataroom-" + id) { history.replaceState(null, "", "#dataroom-" + id); } keep(() => (S.tab = id)); break;
      case "pgroup": keep(() => (S.pgroup = id)); break;
      case "tgroup": keep(() => (S.tgroup = id)); break;
      case "tick": keep(() => (S.tick = el.dataset.v)); break;
      case "run": keep(() => (S.run = Number(el.dataset.v))); break;
      case "gw9": keep(() => (S.gw9 = !S.gw9)); break;
      case "to-own": S.tab = "players"; S.pgroup = "own"; history.replaceState(null, "", "#dataroom-players"); render(true); break;
      case "pmg": keep(() => (S.pmg = id)); break;
      case "finder-team": break;
      case "ask-about": S.ask.draft = `Is ${nm(id)} worth it for my squad?`; S.ask.err = ""; break;
      case "ask-q": keep(() => { S.ask.q = id; S.ask.custom = null; S.ask.answer = null; S.ask.err = ""; }); break;
      case "ask-stop": if (askCtl) askCtl.abort(); break;
      case "back": {
        ev.preventDefault();
        if (trail.length > 1) history.back(); else location.hash = "#" + el.dataset.fallback;
        break;
      }
    }
  });
  document.addEventListener("input", (ev) => { if (ev.target.id === "ask-input") { S.ask.draft = ev.target.value; if (S.ask.err) { S.ask.err = ""; const e = $("#ask-error"); if (e) e.textContent = ""; } } });
  document.addEventListener("submit", (ev) => {
    const f = ev.target.closest("[data-act='ask-form']");
    if (!f) return;
    ev.preventDefault();
    const t = S.ask.draft.trim();
    if (!t) { S.ask.err = "Type a question first."; render(false); const i = $("#ask-input"); if (i) i.focus(); return; }
    Object.assign(S.ask, { custom: t, draft: "", err: "", busy: true, answer: null, busyText: "" });
    render(false);
    ask(t);
  });

  // ---------- boot ----------
  async function boot() {
    try {
      IDX = await findBase();
      const cur = IDX.editions.find((e) => e.gw === IDX.current);
      [ED, D] = await Promise.all([getJSON(cur.file), getJSON(cur.data)]);
      SRC = await getJSON("data/sources.json").catch(() => null);
      trail.push(route().raw);
      render(true);
    } catch (e) {
      $("#app").innerHTML = `<div class="loading gutter"><h1 class="t-h1">Could not load this week's edition</h1><p>${esc(e.message)}</p></div>`;
    }
  }
  boot();
})();
