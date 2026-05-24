/* ===========================================================================
 * Banking Client Sector Intelligence — dashboard front-end
 * Progressive-disclosure design: BCSI is the headline number; detail
 * sections expand/collapse so analysts see signal first, depth on demand.
 * Talks to the FastAPI backend mounted under /api/v1.
 * ======================================================================== */

const API = "/api/v1";
let allCompanies = [];          // last full fetch, used for client-side filtering

/* ── tiny helpers ─────────────────────────────────────────────────────────── */
const $ = (id) => document.getElementById(id);

function showLoader(on) {
  $("loader").classList.toggle("hidden", !on);
}

let _toastTimer = null;
function toast(msg, type = "") {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast " + type;
  el.classList.remove("hidden");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
}

function num(v, dec = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, {
    minimumFractionDigits: dec, maximumFractionDigits: dec,
  });
}

function pct(v, dec = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = Number(v).toFixed(dec);
  return (v > 0 ? "+" : "") + s + "%";
}

function compact(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (a >= 1e9)  return (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6)  return (v / 1e6).toFixed(2) + "M";
  return num(v, 0);
}

/** CSS modifier for Risk label chips / badges. */
function riskClass(label) {
  if (label === "High Risk")   return "high";
  if (label === "Medium Risk") return "medium";
  if (label === "Low Risk")    return "low";
  return "";
}

/** CSS modifier for BCSI label chips. */
function bcsiClass(label) {
  if (label === "Strong") return "bcsi-strong";
  if (label === "Fair")   return "bcsi-fair";
  if (label === "Watch")  return "bcsi-watch";
  if (label === "Weak")   return "bcsi-weak";
  return "";
}

/* ── API wrapper ──────────────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ── companies table ──────────────────────────────────────────────────────── */
async function loadCompanies() {
  try {
    allCompanies = await api("/companies");
    populateSectorFilter(allCompanies);
    filterCompanies();
  } catch (e) {
    toast(e.message, "error");
  }
}

function filterCompanies() {
  const bcsiF   = $("bcsiFilter").value;
  const risk    = $("riskFilter").value;
  const sector  = $("sectorFilter").value;
  const list = allCompanies.filter((c) =>
    (!bcsiF  || c.bcsi_label   === bcsiF) &&
    (!risk   || c.risk_label   === risk)  &&
    (!sector || c.sector       === sector)
  );
  renderTable(list);
  updateStats(allCompanies);
}

function renderTable(list) {
  const body = $("companiesBody");
  if (!list.length) {
    body.innerHTML =
      '<tr><td colspan="7" class="empty">No companies match. Enter a ticker above.</td></tr>';
    return;
  }
  body.innerHTML = list
    .map((c) => {
      const bcsiLbl = c.bcsi_label ?? "—";
      const bcsiScr = c.bcsi_score != null ? num(c.bcsi_score, 1) : "—";
      return `
      <tr data-ticker="${c.ticker}">
        <td><strong>${c.ticker}</strong></td>
        <td>${c.name ?? "—"}</td>
        <td>${c.sector ?? "—"}</td>
        <td>
          <span class="bcsi-chip ${bcsiClass(c.bcsi_label)}">${bcsiScr}</span>
          <span class="bcsi-lbl-sm ${bcsiClass(c.bcsi_label)}">${bcsiLbl}</span>
        </td>
        <td>${pct(c.revenue_growth_yoy)}</td>
        <td>${pct(c.net_margin)}</td>
        <td><span class="risk-chip ${riskClass(c.risk_label)}">${c.risk_label ?? "—"}</span></td>
      </tr>`;
    })
    .join("");
  body.querySelectorAll("tr[data-ticker]").forEach((tr) =>
    tr.addEventListener("click", () => showDetail(tr.dataset.ticker))
  );
}

function updateStats(list) {
  $("totalCompanies").textContent = list.length;
  $("bcsiStrong").textContent   = list.filter((c) => c.bcsi_label === "Strong").length;
  $("bcsiFair").textContent     = list.filter((c) => c.bcsi_label === "Fair").length;
  $("bcsiWatchWeak").textContent = list.filter(
    (c) => c.bcsi_label === "Watch" || c.bcsi_label === "Weak"
  ).length;
}

function populateSectorFilter(list) {
  const sel = $("sectorFilter");
  const current = sel.value;
  const sectors = [...new Set(list.map((c) => c.sector).filter(Boolean))].sort();
  sel.innerHTML =
    '<option value="">All Sectors</option>' +
    sectors.map((s) => `<option value="${s}">${s}</option>`).join("");
  sel.value = current;
}

/* ── sector benchmark bars ────────────────────────────────────────────────── */
async function loadSectorChart() {
  try {
    const rows = await api("/sectors/summary");
    const chart = $("sectorChart");
    if (!rows.length) {
      chart.innerHTML = '<p class="empty">No sectors yet.</p>';
      return;
    }
    rows.sort((a, b) => b.avg_risk_score - a.avg_risk_score);
    chart.innerHTML = rows
      .map((r) => {
        const score = r.avg_risk_score || 0;
        const cls   = score >= 60 ? "risk-high" : score >= 35 ? "risk-med" : "risk-low";
        return `
        <div class="sector-bar-item">
          <div class="sector-bar-label">
            <span>${r.sector} (${r.company_count})</span>
            <span>${num(score, 1)} avg risk</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${cls}" style="width:${Math.min(score, 100)}%"></div>
          </div>
        </div>`;
      })
      .join("");
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ── accordion ────────────────────────────────────────────────────────────── */
function toggleSection(name) {
  const section = document.querySelector(`[data-section="${name}"]`);
  if (section) section.classList.toggle("open");
}

/* ── company detail panel ─────────────────────────────────────────────────── */
async function showDetail(ticker) {
  showLoader(true);
  try {
    const [company, peers, risk, bcsiData] = await Promise.all([
      api(`/companies/${ticker}`),
      api(`/companies/${ticker}/peers`).catch(() => null),
      api(`/companies/${ticker}/risk`).catch(() => null),
      api(`/companies/${ticker}/bcsi`).catch(() => null),
    ]);
    renderDetail(company, peers, risk, bcsiData);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    showLoader(false);
  }
}

/* ── metric card helpers ──────────────────────────────────────────────────── */
function subhead(text) {
  return `<div class="metric-subhead">${text}</div>`;
}

function card(label, value, cls = "neutral") {
  return `
    <div class="metric-card">
      <div class="metric-label">${label}</div>
      <div class="metric-value ${cls}">${value}</div>
    </div>`;
}

/* ── BCSI hero renderer ───────────────────────────────────────────────────── */
function renderBcsiHero(c, bcsiData) {
  // Score + label — prefer dedicated bcsi endpoint data, fall back to company
  const score  = bcsiData?.bcsi_score  ?? c.bcsi_score;
  const label  = bcsiData?.bcsi_label  ?? c.bcsi_label  ?? "—";
  const conf   = bcsiData?.bcsi_confidence ?? c.bcsi_confidence;
  const dims   = bcsiData?.dimensions  ?? (c.bcsi_dimensions || {});

  $("bcsiScoreBig").textContent = score != null ? num(score, 1) : "—";

  const chip = $("bcsiLabelChip");
  chip.textContent  = label;
  chip.className    = `bcsi-label-chip ${bcsiClass(label)}`;

  $("bcsiConfidence").textContent =
    conf != null ? `${conf}% coverage` : "Coverage unknown";

  // Dimension bars
  const DIM_LABELS = {
    risk:       "Risk (inverted)",
    quality:    "Quality",
    valuation:  "Valuation",
    governance: "Governance",
    momentum:   "Momentum",
  };

  const dimEntries = Object.entries(dims);
  if (dimEntries.length === 0) {
    $("bcsiDims").innerHTML =
      '<p class="dim-empty">Run analysis to populate dimensions.</p>';
  } else {
    $("bcsiDims").innerHTML = dimEntries
      .map(([key, d]) => {
        const w   = d.weight != null ? Math.round(d.weight * 100) : "?";
        const pct = d.score != null ? Math.min(100, Math.max(0, d.score)) : 0;
        const col = pct >= 65 ? "var(--green)"
                  : pct >= 45 ? "var(--accent)"
                  : pct >= 30 ? "var(--yellow)"
                  :             "var(--red)";
        return `
          <div class="bcsi-dim-row">
            <div class="bcsi-dim-label">
              <span>${DIM_LABELS[key] ?? key}</span>
              <span class="bcsi-dim-score">${d.score != null ? num(d.score, 1) : "—"}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill bcsi-dim-bar" style="width:${pct}%;background:${col}"></div>
            </div>
            <div class="bcsi-dim-weight">${w}% weight</div>
          </div>`;
      })
      .join("") +
      `<div class="bcsi-momentum-note">
         Momentum: <em>pending — Phase 7 (sentiment + technicals + signals)</em>
       </div>`;
  }
}

/* ── main detail renderer ─────────────────────────────────────────────────── */
function renderDetail(c, peers, risk, bcsiData) {
  $("detailName").textContent   = c.name ?? c.ticker;
  $("detailTicker").textContent = c.ticker;
  $("detailSector").textContent = c.sector ?? "—";

  const badge = $("detailRiskBadge");
  badge.className = "risk-badge-large " + riskClass(c.risk_label);
  badge.textContent = `${c.risk_label ?? "—"} · ${num(c.risk_score, 1)}`;

  // ── BCSI hero ─────────────────────────────────────────────────────────────
  renderBcsiHero(c, bcsiData);

  // ── Market Snapshot ───────────────────────────────────────────────────────
  const upsideCls = c.upside_pct > 0 ? "positive" : c.upside_pct < 0 ? "negative" : "neutral";
  $("metricsSnapshot").innerHTML = [
    card("Current Price",  num(c.current_price)),
    card("Fair Value",     num(c.composite_fair_value)),
    card("Upside vs Price", pct(c.upside_pct), upsideCls),
    card("Valuation",      c.valuation_label ?? "—"),
    card("Market Cap",     compact(c.market_cap)),
    card("Revenue Growth", pct(c.revenue_growth_yoy), c.revenue_growth_yoy > 0 ? "positive" : "negative"),
    card("Net Margin",     pct(c.net_margin)),
    card("Return on Equity", pct(c.roe)),
    card("P/E Ratio",      num(c.pe_ratio)),
    card("Debt / Equity",  num(c.debt_to_equity, 0)),
    card("Analyst Target", num(c.analyst_target_mean)),
    card("Analyst Count",  c.analyst_count != null ? String(c.analyst_count) : "—"),
  ].join("");

  // ── Risk Analysis ─────────────────────────────────────────────────────────
  const z = risk?.altman   || {};
  const m = risk?.beneish  || {};
  const cf = risk?.cashflow || {};
  $("metricsRisk").innerHTML = [
    card("Risk Score",         `${num(c.risk_score, 1)} ${c.risk_label ? `(${c.risk_label})` : ""}`),
    card("Confidence",         c.risk_confidence != null ? c.risk_confidence + "%" : "—"),
    card("Altman Z-Score",     z.z_score  != null ? `${num(z.z_score)} (${z.zone})` : (c.altman_zone ?? "—")),
    card("Beneish M-Score",    m.m_score  != null ? `${num(m.m_score)} (${m.flag})` : (c.beneish_flag ?? "—")),
    card("Interest Coverage",  cf.icr     != null ? `${num(cf.icr)} (${cf.icr_label ?? ""})` : "—"),
    card("FCF Margin",         cf.fcf_margin != null ? pct(cf.fcf_margin) : "—"),
    card("Beta",               num(c.beta)),
  ].join("");

  const flags = c.risk_flags || [];
  $("flagsSection").innerHTML =
    "<h4 class='section-subhead'>Risk Flags</h4>" +
    (flags.length
      ? flags.map((f) => `<div class="flag-item">${f}</div>`).join("")
      : '<p class="empty" style="padding:8px 0">No risk flags raised.</p>');

  // ── Quality ───────────────────────────────────────────────────────────────
  const pScore = c.piotroski_f_score;
  $("metricsQuality").innerHTML = [
    card("BCSI Quality Score",   c.quality_score != null ? `${num(c.quality_score, 1)} (${c.quality_label ?? ""})` : "—"),
    card("Piotroski F-Score",    pScore != null ? `${pScore} / 9` : "—",
         pScore >= 7 ? "positive" : pScore >= 4 ? "neutral" : "negative"),
    card("Graham Number",        c.graham_number != null ? num(c.graham_number) : "—"),
    card("Dividend Yield",       pct(c.dividend_yield)),
    card("Payout Ratio",         pct(c.payout_ratio)),
    card("EPS (TTM)",            num(c.eps_ttm)),
    card("EPS (Forward)",        num(c.eps_forward)),
    card("ROA",                  pct(c.roa)),
  ].join("");

  // ── Price Targets ─────────────────────────────────────────────────────────
  $("metricsTargets").innerHTML = [
    card("Bear Target",          num(c.bear_target),           "negative"),
    card("Base Target",          num(c.base_target),           "neutral"),
    card("Bull Target",          num(c.bull_target),           "positive"),
    card("Stretched Bull",       num(c.stretched_bull_target), "positive"),
    card("52-Wk High",           num(c.fifty_two_week_high)),
    card("52-Wk Low",            num(c.fifty_two_week_low)),
    card("Val. Confidence",      c.valuation_confidence != null ? c.valuation_confidence + "%" : "—"),
  ].join("");

  // ── Action Levels ─────────────────────────────────────────────────────────
  $("metricsAction").innerHTML = [
    card("Entry Zone",
      `${num(c.entry_zone_low)} – ${num(c.entry_zone_high)}`, "positive"),
    card("Entry Note", "9–18% below base fair value"),
    card("Trim Level",   num(c.trim_level), "neutral"),
    card("Trim Note",    "Within 4% of bull target"),
    card("Hard Stop",    num(c.hard_stop),  "negative"),
    card("Stop Note",    "Max(52-wk low × 0.97, entry × 0.83)"),
  ].join("");

  // ── Peers ─────────────────────────────────────────────────────────────────
  const peerList = peers?.peers || [];
  $("peersTable").innerHTML = peerList.length
    ? `<table>
         <thead>
           <tr>
             <th>Ticker</th><th>Name</th>
             <th>BCSI</th><th>Risk</th><th>Upside</th>
           </tr>
         </thead>
         <tbody>${peerList
           .map((p) => `
             <tr data-ticker="${p.ticker}">
               <td><strong>${p.ticker}</strong></td>
               <td>${p.name ?? "—"}</td>
               <td>
                 <span class="bcsi-chip ${bcsiClass(p.bcsi_label)}">
                   ${p.bcsi_score != null ? num(p.bcsi_score, 1) : "—"}
                 </span>
               </td>
               <td><span class="risk-chip ${riskClass(p.risk_label)}">${num(p.risk_score, 1)}</span></td>
               <td>${pct(p.upside_pct)}</td>
             </tr>`)
           .join("")}
         </tbody>
       </table>`
    : '<p class="empty" style="padding:8px 0">No peers tracked in this sector yet.</p>';
  $("peersTable")
    .querySelectorAll("tr[data-ticker]")
    .forEach((tr) => tr.addEventListener("click", () => showDetail(tr.dataset.ticker)));

  // Show panel and open default sections
  $("companyDetail").classList.remove("hidden");
  // Ensure snapshot is open; close others that may be open from a prev render
  document.querySelectorAll(".accordion-section").forEach((s) => {
    s.classList.toggle("open", s.dataset.section === "snapshot");
  });
  $("companyDetail").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ── analyze action ───────────────────────────────────────────────────────── */
async function analyzeCompany() {
  const input  = $("tickerInput");
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) {
    toast("Enter a ticker symbol first.", "error");
    return;
  }
  showLoader(true);
  try {
    const company = await api(
      `/companies/analyze?ticker=${encodeURIComponent(ticker)}`,
      { method: "POST" }
    );
    const lbl = company.bcsi_label ?? company.risk_label ?? "analyzed";
    toast(`${company.ticker} analyzed — BCSI: ${lbl}.`, "success");
    input.value = "";
    await loadCompanies();
    await loadSectorChart();
    await showDetail(company.ticker);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    showLoader(false);
  }
}

/* ── init ─────────────────────────────────────────────────────────────────── */
function init() {
  $("tickerInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyzeCompany();
  });
  loadCompanies();
  loadSectorChart();
}

// expose inline-referenced handlers
window.analyzeCompany = analyzeCompany;
window.filterCompanies = filterCompanies;
window.toggleSection = toggleSection;

document.addEventListener("DOMContentLoaded", init);
