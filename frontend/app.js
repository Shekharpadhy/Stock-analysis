/* ===========================================================================
 * Banking Client Sector Intelligence — dashboard front-end
 * Talks to the FastAPI backend mounted under /api/v1.
 * Exposes analyzeCompany() and filterCompanies() globally (referenced inline
 * from index.html).
 * ======================================================================== */

const API = "/api/v1";
let allCompanies = [];          // last full fetch, used for client-side filtering

/* ---- tiny helpers ------------------------------------------------------- */
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

/** Map a risk label to the CSS modifier used by .risk-chip / badges. */
function riskClass(label) {
  if (label === "High Risk")   return "high";
  if (label === "Medium Risk") return "medium";
  if (label === "Low Risk")    return "low";
  return "";
}

/* ---- API wrapper -------------------------------------------------------- */
async function api(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ---- companies table ---------------------------------------------------- */
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
  const risk   = $("riskFilter").value;
  const sector = $("sectorFilter").value;
  const list = allCompanies.filter(
    (c) => (!risk || c.risk_label === risk) && (!sector || c.sector === sector)
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
    .map(
      (c) => `
      <tr data-ticker="${c.ticker}">
        <td><strong>${c.ticker}</strong></td>
        <td>${c.name ?? "—"}</td>
        <td>${c.sector ?? "—"}</td>
        <td>${pct(c.revenue_growth_yoy)}</td>
        <td>${pct(c.net_margin)}</td>
        <td>${num(c.risk_score, 1)}</td>
        <td><span class="risk-chip ${riskClass(c.risk_label)}">${c.risk_label ?? "—"}</span></td>
      </tr>`
    )
    .join("");
  body.querySelectorAll("tr[data-ticker]").forEach((tr) =>
    tr.addEventListener("click", () => showDetail(tr.dataset.ticker))
  );
}

function updateStats(list) {
  $("totalCompanies").textContent = list.length;
  $("highRisk").textContent = list.filter((c) => c.risk_label === "High Risk").length;
  $("medRisk").textContent  = list.filter((c) => c.risk_label === "Medium Risk").length;
  $("lowRisk").textContent  = list.filter((c) => c.risk_label === "Low Risk").length;
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

/* ---- sector benchmark bars --------------------------------------------- */
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
        const cls = score >= 60 ? "risk-high" : score >= 35 ? "risk-med" : "risk-low";
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

/* ---- company detail panel ---------------------------------------------- */
async function showDetail(ticker) {
  showLoader(true);
  try {
    const [company, peers, risk] = await Promise.all([
      api(`/companies/${ticker}`),
      api(`/companies/${ticker}/peers`).catch(() => null),
      api(`/companies/${ticker}/risk`).catch(() => null),
    ]);
    renderDetail(company, peers, risk);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    showLoader(false);
  }
}

function subhead(text) {
  return `<div class="metric-label" style="grid-column:1/-1;margin-top:8px;
          font-size:12px;color:var(--accent);font-weight:600">${text}</div>`;
}

function card(label, value, cls = "neutral") {
  return `
    <div class="metric-card">
      <div class="metric-label">${label}</div>
      <div class="metric-value ${cls}">${value}</div>
    </div>`;
}

function renderDetail(c, peers, risk) {
  $("detailName").textContent   = c.name ?? c.ticker;
  $("detailTicker").textContent = c.ticker;
  $("detailSector").textContent = c.sector ?? "—";

  const badge = $("detailRiskBadge");
  badge.className = "risk-badge-large " + riskClass(c.risk_label);
  badge.textContent = `${c.risk_label ?? "—"} · ${num(c.risk_score, 1)}`;

  const upsideCls = c.upside_pct > 0 ? "positive" : c.upside_pct < 0 ? "negative" : "neutral";
  const z = risk?.altman || {};
  const m = risk?.beneish || {};

  $("metricsGrid").innerHTML = [
    subhead("Snapshot"),
    card("Current Price", num(c.current_price)),
    card("Fair Value (DCF)", num(c.composite_fair_value)),
    card("Upside vs Price", pct(c.upside_pct), upsideCls),
    card("Valuation", c.valuation_label ?? "—"),
    card("Risk Confidence", c.risk_confidence != null ? c.risk_confidence + "%" : "—"),
    card("Valuation Confidence", c.valuation_confidence != null ? c.valuation_confidence + "%" : "—"),

    subhead("Risk models"),
    card("Altman Z-Score", z.z_score != null ? `${num(z.z_score)} (${z.zone})` : (c.altman_zone ?? "—")),
    card("Beneish M-Score", m.m_score != null ? `${num(m.m_score)} (${m.flag})` : (c.beneish_flag ?? "—")),
    card("Market Cap", compact(c.market_cap)),
    card("P/E Ratio", num(c.pe_ratio)),
    card("Net Margin", pct(c.net_margin)),
    card("Revenue Growth", pct(c.revenue_growth_yoy)),
    card("Return on Equity", pct(c.roe)),
    card("Debt / Equity", num(c.debt_to_equity, 0)),

    subhead("Price targets — Bear / Base / Bull"),
    card("Bear", num(c.bear_target), "negative"),
    card("Base", num(c.base_target), "neutral"),
    card("Bull", num(c.bull_target), "positive"),
    card("Stretched Bull", num(c.stretched_bull_target), "positive"),

    subhead("Action levels"),
    card("Entry Zone", `${num(c.entry_zone_low)} – ${num(c.entry_zone_high)}`, "positive"),
    card("Trim Level", num(c.trim_level), "neutral"),
    card("Hard Stop", num(c.hard_stop), "negative"),
    card("52-Week Range", `${num(c.fifty_two_week_low)} – ${num(c.fifty_two_week_high)}`),
  ].join("");

  // Risk flags
  const flags = c.risk_flags || [];
  $("flagsSection").innerHTML =
    "<h3>Risk Flags</h3>" +
    (flags.length
      ? flags.map((f) => `<div class="flag-item">${f}</div>`).join("")
      : '<p class="empty" style="padding:8px 0">No risk flags raised.</p>');

  // Peer comparison
  const peerList = peers?.peers || [];
  $("peersTable").innerHTML = peerList.length
    ? `<table>
         <thead><tr><th>Ticker</th><th>Name</th><th>Risk</th><th>Upside</th></tr></thead>
         <tbody>${peerList
           .map(
             (p) => `<tr data-ticker="${p.ticker}">
               <td><strong>${p.ticker}</strong></td>
               <td>${p.name ?? "—"}</td>
               <td><span class="risk-chip ${riskClass(p.risk_label)}">${num(p.risk_score, 1)}</span></td>
               <td>${pct(p.upside_pct)}</td></tr>`
           )
           .join("")}</tbody>
       </table>`
    : '<p class="empty" style="padding:8px 0">No peers tracked in this sector yet.</p>';
  $("peersTable")
    .querySelectorAll("tr[data-ticker]")
    .forEach((tr) => tr.addEventListener("click", () => showDetail(tr.dataset.ticker)));

  $("companyDetail").classList.remove("hidden");
  $("companyDetail").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---- analyze action ----------------------------------------------------- */
async function analyzeCompany() {
  const input = $("tickerInput");
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
    toast(`${company.ticker} analysed — ${company.risk_label}.`, "success");
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

/* ---- init --------------------------------------------------------------- */
function init() {
  $("tickerInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyzeCompany();
  });
  loadCompanies();
  loadSectorChart();
}

// expose the inline-referenced handlers
window.analyzeCompany = analyzeCompany;
window.filterCompanies = filterCompanies;

document.addEventListener("DOMContentLoaded", init);
