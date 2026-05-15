// ── Chart.js theme tokens ───────────────────────────────────────
const COLOR = {
  text: "#e6edf6",
  muted: "#7f8cab",
  grid: "rgba(148, 163, 184, 0.07)",
  border: "rgba(148, 163, 184, 0.18)",
  bg: "#0a0f1c",
  accent: "#4ec9ff",
  cyan: "#22d3ee",
  purple: "#a78bfa",
  teal: "#2dd4bf",
  green: "#34d399",
  success: "#22c55e",
  warning: "#f59e0b",
  orange: "#fb923c",
  danger: "#ef4444",
  pink: "#f472b6",
};

if (window.Chart) {
  Chart.defaults.color = COLOR.muted;
  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.borderColor = COLOR.grid;
}

// ── DOM refs ────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const alertsBody = $("alertsBody");
const sourceFilter = $("sourceFilter");
const severityFilter = $("severityFilter");
const statusFilter = $("statusFilter");
const searchInput = $("searchInput");
const refreshBtn = $("refreshBtn");
const newAlertForm = $("newAlertForm");
const formMessage = $("formMessage");
const newAlertToggle = $("newAlertToggle");
const newAlertPanel = $("newAlertPanel");
const closeNewAlert = $("closeNewAlert");
const overlay = $("overlay");
const lastUpdate = $("lastUpdate");
const connStatus = $("connStatus");
const detailDrawer = $("detailDrawer");
const drawerBody = $("drawerBody");
const drawerTitle = $("drawerTitle");
const drawerSub = $("drawerSub");
const closeDrawer = $("closeDrawer");
const rowCountEl = $("rowCount");
const pageInfoEl = $("pageInfo");
const prevPageBtn = $("prevPage");
const nextPageBtn = $("nextPage");
const retryAllErrorsBtn = $("retryAllErrorsBtn");
const patternsTableBody = document.querySelector("#patternsTable tbody");
const artifactsTableBody = document.querySelector("#artifactsTable tbody");

// ── State ───────────────────────────────────────────────────────
let allAlerts = [];
let filteredAlerts = [];
let currentPage = 1;
const PAGE_SIZE = 15;
const charts = {};

const SVG_NS = "http://www.w3.org/2000/svg";

// ── Utils ───────────────────────────────────────────────────────
function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.className) node.className = opts.className;
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.title) node.title = opts.title;
  if (opts.attrs) Object.entries(opts.attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (opts.style) Object.assign(node.style, opts.style);
  (Array.isArray(children) ? children : [children]).forEach((c) => {
    if (c == null) return;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return node;
}

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

function fmtTime(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function fmtDateTime(date) {
  return date.toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function relTime(date) {
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── Sparkline (DOM-built SVG) ───────────────────────────────────
function sparklineEl(values, severityClass = "") {
  const w = 120, h = 24, pad = 1.5;
  if (!values || values.length === 0) values = [0];
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? (w - pad * 2) / (values.length - 1) : 0;
  const points = values.map((v, i) => {
    const x = pad + i * step;
    const y = h - pad - (v / max) * (h - pad * 2);
    return [x, y];
  });
  const linePath = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const fillPath = `${linePath} L${(w - pad).toFixed(1)},${(h - pad).toFixed(1)} L${pad},${(h - pad).toFixed(1)} Z`;

  const svg = svgEl("svg", {
    class: `sparkline ${severityClass}`.trim(),
    viewBox: `0 0 ${w} ${h}`,
    preserveAspectRatio: "none",
  });
  svg.appendChild(svgEl("path", { class: "sparkline-path-fill", d: fillPath }));
  svg.appendChild(svgEl("path", { class: "sparkline-path", d: linePath }));
  return svg;
}

// ── Slide panel for new alerts ──────────────────────────────────
function openNewAlert() {
  newAlertPanel.classList.add("active");
  overlay.classList.add("active");
  newAlertPanel.setAttribute("aria-hidden", "false");
}
function closeNewAlertPanel() {
  newAlertPanel.classList.remove("active");
  overlay.classList.remove("active");
  newAlertPanel.setAttribute("aria-hidden", "true");
}
newAlertToggle.addEventListener("click", openNewAlert);
closeNewAlert.addEventListener("click", closeNewAlertPanel);

// ── Drawer for alert detail ────────────────────────────────────
function openDrawer(alert) {
  drawerTitle.textContent = `Alert #${alert.id}`;
  drawerSub.textContent = `${alert.source} · ${alert.severity} · ${fmtDateTime(new Date(alert.created_at))}`;
  drawerBody.textContent = "";

  const meta = el("div", { className: "kv-grid" });
  const addRow = (k, v, mono) => {
    meta.appendChild(el("div", { className: "k", text: k }));
    meta.appendChild(el("div", { className: "v" + (mono ? " mono" : ""), text: v }));
  };
  addRow("source", alert.source);
  addRow("severity", alert.severity);
  addRow("status", alert.status);
  addRow("created", fmtDateTime(new Date(alert.created_at)), true);
  addRow("updated", fmtDateTime(new Date(alert.updated_at)), true);
  if (alert.queue_position) addRow("queue", `#${alert.queue_position}`, true);
  drawerBody.appendChild(meta);

  drawerBody.appendChild(el("span", { className: "section-label", text: "description" }));
  drawerBody.appendChild(el("div", { className: "kv-grid" }, [
    el("div", { className: "k", text: "text" }),
    el("div", { className: "v", text: alert.description || "—" }),
  ]));

  const artifacts = alert.artifacts || [];
  drawerBody.appendChild(el("span", { className: "section-label", text: `artifacts (${artifacts.length})` }));
  const artBlock = el("div", { className: "kv-grid" });
  if (artifacts.length === 0) {
    artBlock.appendChild(el("div", { className: "v", text: "—" }));
  } else {
    artifacts.forEach((a, i) => {
      artBlock.appendChild(el("div", { className: "k", text: `#${i + 1}` }));
      artBlock.appendChild(el("div", { className: "v mono", text: a }));
    });
  }
  drawerBody.appendChild(artBlock);

  drawerBody.appendChild(el("span", { className: "section-label", text: "llm analysis" }));
  drawerBody.appendChild(renderAnalysisDetailed(alert.analysis_result, alert.status));

  if (alert.status !== "PENDING" && alert.status !== "PROCESSING") {
    const retry = el("button", { className: "primary-btn full-width", text: "↻ Re-analyze with LLM" });
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      retry.textContent = "Re-queuing…";
      try {
        const res = await fetch(`/alerts/${alert.id}/retry`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Failed");
        retry.textContent = "Re-queued";
        loadAlerts();
        setTimeout(closeDrawerPanel, 600);
      } catch (e) {
        retry.disabled = false;
        retry.textContent = "↻ Re-analyze with LLM";
        retry.title = e.message;
      }
    });
    drawerBody.appendChild(retry);
  }

  detailDrawer.classList.add("active");
  overlay.classList.add("active");
  detailDrawer.setAttribute("aria-hidden", "false");
}
function closeDrawerPanel() {
  detailDrawer.classList.remove("active");
  overlay.classList.remove("active");
  detailDrawer.setAttribute("aria-hidden", "true");
}
closeDrawer.addEventListener("click", closeDrawerPanel);

overlay.addEventListener("click", () => {
  closeNewAlertPanel();
  closeDrawerPanel();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (newAlertPanel.classList.contains("active")) closeNewAlertPanel();
  if (detailDrawer.classList.contains("active")) closeDrawerPanel();
});

// ── Analysis renderer (drawer) ──────────────────────────────────
function renderAnalysisDetailed(result, status) {
  const wrapper = el("div", { className: "analysis-card" });
  if (!result || result.status) {
    wrapper.appendChild(el("p", {
      className: "analysis-pending",
      text: status === "PENDING" ? "Waiting for LLM analysis…" : "Processing…",
    }));
    return wrapper;
  }

  const riskRow = el("div", { className: "analysis-row" });
  riskRow.appendChild(el("span", { className: "label", text: "Risk" }));
  const riskLevel = (result.risk_assessment || "").toUpperCase();
  riskRow.appendChild(el("span", { className: `pill risk-${riskLevel}`, text: riskLevel || "—" }));
  wrapper.appendChild(riskRow);

  if (result.summary) {
    const sumRow = el("div", { className: "analysis-row" });
    sumRow.appendChild(el("span", { className: "label", text: "Summary" }));
    sumRow.appendChild(el("span", { className: "summary", text: result.summary }));
    wrapper.appendChild(sumRow);
  }

  if (typeof result.confidence === "number") {
    const pct = Math.round(result.confidence * 100);
    const tier = pct >= 70 ? "high" : pct >= 40 ? "medium" : "low";
    const confRow = el("div", { className: "analysis-row" });
    confRow.appendChild(el("span", { className: "label", text: "Confidence" }));
    const cell = el("div", { className: "conf-cell" });
    const bar = el("div", { className: "conf-bar" });
    bar.appendChild(el("div", { className: `conf-fill ${tier}`, style: { width: `${pct}%` } }));
    cell.appendChild(bar);
    cell.appendChild(el("span", { className: "conf-text", text: `${pct}%` }));
    confRow.appendChild(cell);
    wrapper.appendChild(confRow);
  }

  const actions = result.recommended_actions || [];
  if (actions.length > 0) {
    const actRow = el("div", { className: "analysis-row" });
    actRow.appendChild(el("span", { className: "label", text: "Actions" }));
    const actBox = el("div", { className: "analysis-actions" });
    const ul = el("ul");
    actions.forEach((a) => ul.appendChild(el("li", { text: a })));
    actBox.appendChild(ul);
    actRow.appendChild(actBox);
    wrapper.appendChild(actRow);
  }

  if (result.error) {
    wrapper.appendChild(el("div", { className: "analysis-error", text: result.error }));
  }
  return wrapper;
}

// ── Status / pill builders ──────────────────────────────────────
function statusBadge(status) {
  const badge = el("span", { className: `status-badge ${status.toLowerCase()}` });
  if (status === "PENDING") {
    badge.appendChild(el("span", { className: "spinner-inline" }));
    badge.appendChild(document.createTextNode(" pending"));
  } else if (status === "PROCESSING") {
    badge.appendChild(el("span", { className: "spinner-inline accent" }));
    badge.appendChild(document.createTextNode(" processing"));
  } else if (status === "COMPLETE") {
    badge.textContent = "complete";
  } else {
    badge.textContent = "error";
  }
  return badge;
}

function pill(cls, text) {
  return el("span", { className: `pill ${cls}`, text });
}

function confCell(value) {
  if (typeof value !== "number") {
    return el("span", { className: "conf-text", text: "—" });
  }
  const pct = Math.round(value * 100);
  const tier = pct >= 70 ? "high" : pct >= 40 ? "medium" : "low";
  const cell = el("div", { className: "conf-cell" });
  const bar = el("div", { className: "conf-bar" });
  bar.appendChild(el("div", { className: `conf-fill ${tier}`, style: { width: `${pct}%` } }));
  cell.appendChild(bar);
  cell.appendChild(el("span", { className: "conf-text", text: `${pct}%` }));
  return cell;
}

// ── Filtering & search ──────────────────────────────────────────
function applyFilters(alerts) {
  const src = sourceFilter.value;
  const sev = severityFilter.value;
  const st = statusFilter.value;
  const q = (searchInput.value || "").trim().toLowerCase();
  return alerts.filter((a) => {
    if (src && a.source !== src) return false;
    if (sev && a.severity !== sev) return false;
    if (st && a.status !== st) return false;
    if (!q) return true;
    if ((a.description || "").toLowerCase().includes(q)) return true;
    if ((a.artifacts || []).some((art) => String(art).toLowerCase().includes(q))) return true;
    return false;
  });
}

// ── Alerts table rendering ──────────────────────────────────────
function renderAlertsTable() {
  alertsBody.textContent = "";

  const total = filteredAlerts.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * PAGE_SIZE;
  const page = filteredAlerts.slice(start, start + PAGE_SIZE);

  rowCountEl.textContent = `${total.toLocaleString()} row${total === 1 ? "" : "s"}`;
  pageInfoEl.textContent = `page ${currentPage} of ${totalPages}`;
  prevPageBtn.disabled = currentPage <= 1;
  nextPageBtn.disabled = currentPage >= totalPages;

  if (page.length === 0) {
    const tr = el("tr", { className: "empty-row" });
    tr.appendChild(el("td", { attrs: { colspan: "9" } }, [
      el("span", { className: "empty-icon", text: "∅" }),
      "No alerts match the current filters.",
    ]));
    alertsBody.appendChild(tr);
    return;
  }

  page.forEach((alert) => {
    const tr = el("tr", { className: "expandable" });

    const idCell = el("td", {}, [
      el("a", { className: "link-cell", text: `#${alert.id}` }),
      alert.queue_position
        ? el("span", { className: "queue-tag", text: `Q${alert.queue_position}`, title: `Position ${alert.queue_position} in queue` })
        : null,
    ]);
    tr.appendChild(idCell);

    const created = new Date(alert.created_at);
    tr.appendChild(el("td", { className: "mono-cell", title: created.toLocaleString() }, [relTime(created)]));

    tr.appendChild(el("td", {}, pill(`src-${alert.source}`, alert.source)));
    tr.appendChild(el("td", {}, pill(`sev-${alert.severity.toLowerCase()}`, alert.severity)));

    tr.appendChild(el("td", { className: "col-desc" }, [
      el("span", { className: "truncate", text: alert.description || "—", title: alert.description || "" }),
    ]));

    const risk = alert.analysis_result && alert.analysis_result.risk_assessment;
    tr.appendChild(el("td", {}, risk ? pill(`risk-${risk}`, risk) : pill("dim", "—")));

    const conf = alert.analysis_result && alert.analysis_result.confidence;
    tr.appendChild(el("td", {}, confCell(conf)));

    tr.appendChild(el("td", {}, statusBadge(alert.status)));

    const actionCell = el("td", { className: "col-action" });
    if (alert.status !== "PENDING" && alert.status !== "PROCESSING") {
      const btn = el("button", { className: "retry-btn", text: "↻ Reanalyze" });
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        btn.disabled = true;
        btn.textContent = "Re-queuing…";
        try {
          const res = await fetch(`/alerts/${alert.id}/retry`, { method: "POST" });
          if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || "Failed");
          }
          loadAlerts();
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "↻ Reanalyze";
          btn.title = err.message;
        }
      });
      actionCell.appendChild(btn);
    }
    tr.appendChild(actionCell);

    tr.addEventListener("click", () => openDrawer(alert));
    alertsBody.appendChild(tr);
  });
}

prevPageBtn.addEventListener("click", () => {
  if (currentPage > 1) { currentPage--; renderAlertsTable(); }
});
nextPageBtn.addEventListener("click", () => {
  const totalPages = Math.max(1, Math.ceil(filteredAlerts.length / PAGE_SIZE));
  if (currentPage < totalPages) { currentPage++; renderAlertsTable(); }
});

// ── Metrics aggregation ────────────────────────────────────────
function buildBuckets(hours = 24) {
  const now = new Date();
  const out = [];
  for (let i = hours - 1; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 3600 * 1000);
    d.setMinutes(0, 0, 0);
    out.push(d.toISOString());
  }
  return out;
}
function bucketKeyFor(dateIso) {
  const d = new Date(dateIso);
  d.setMinutes(0, 0, 0);
  return d.toISOString();
}

function computeMetrics(alerts) {
  const m = {
    total: alerts.length,
    bySource: { SIEM: 0, EDR: 0, API: 0 },
    bySeverity: { HIGH: 0, MEDIUM: 0, LOW: 0 },
    byStatus: { PENDING: 0, PROCESSING: 0, COMPLETE: 0, ERROR: 0 },
    byRisk: { HIGH: 0, MEDIUM: 0, LOW: 0, ERROR: 0 },
    overTime: {},
  };

  const buckets = buildBuckets(24);
  buckets.forEach((k) => {
    m.overTime[k] = { SIEM: 0, EDR: 0, API: 0, HIGH: 0, total: 0, pending: 0, errors: 0 };
  });

  alerts.forEach((a) => {
    m.bySource[a.source] = (m.bySource[a.source] || 0) + 1;
    m.bySeverity[a.severity] = (m.bySeverity[a.severity] || 0) + 1;
    m.byStatus[a.status] = (m.byStatus[a.status] || 0) + 1;
    if (a.analysis_result && a.analysis_result.risk_assessment) {
      const r = a.analysis_result.risk_assessment;
      m.byRisk[r] = (m.byRisk[r] || 0) + 1;
    }
    const key = bucketKeyFor(a.created_at);
    if (m.overTime[key]) {
      const b = m.overTime[key];
      b[a.source] = (b[a.source] || 0) + 1;
      b.total += 1;
      if (a.severity === "HIGH") b.HIGH += 1;
      if (a.status === "PENDING" || a.status === "PROCESSING") b.pending += 1;
      if (a.status === "ERROR") b.errors += 1;
    }
  });

  m.timeBuckets = buckets;
  m.totalLast24h = buckets.reduce((s, k) => s + m.overTime[k].total, 0);
  return m;
}

// ── Top patterns / artifacts ────────────────────────────────────
function topPatterns(alerts, limit = 6) {
  const groups = new Map();
  alerts.forEach((a) => {
    const key = (a.description || "—").trim().slice(0, 80) || "—";
    if (!groups.has(key)) {
      groups.set(key, { key, count: 0, sev: { HIGH: 0, MEDIUM: 0, LOW: 0 }, alerts: [] });
    }
    const g = groups.get(key);
    g.count += 1;
    g.sev[a.severity] = (g.sev[a.severity] || 0) + 1;
    g.alerts.push(a);
  });
  return [...groups.values()].sort((a, b) => b.count - a.count).slice(0, limit);
}
function topArtifacts(alerts, limit = 6) {
  const counts = new Map();
  alerts.forEach((a) => {
    (a.artifacts || []).forEach((art) => {
      const key = String(art).trim();
      if (!key) return;
      if (!counts.has(key)) counts.set(key, { key, count: 0, high: 0, alerts: [] });
      const g = counts.get(key);
      g.count += 1;
      if (a.severity === "HIGH") g.high += 1;
      g.alerts.push(a);
    });
  });
  return [...counts.values()].sort((a, b) => b.count - a.count).slice(0, limit);
}
function sparkValuesFor(alerts, buckets) {
  const map = Object.fromEntries(buckets.map((k) => [k, 0]));
  alerts.forEach((a) => {
    const k = bucketKeyFor(a.created_at);
    if (k in map) map[k] += 1;
  });
  return buckets.map((k) => map[k]);
}
function dominantSeverityClass(sev) {
  let max = ["LOW", 0];
  Object.entries(sev).forEach(([k, v]) => { if (v > max[1]) max = [k, v]; });
  return `sev-${max[0].toLowerCase()}`;
}

function renderPatternsTable(metrics) {
  patternsTableBody.textContent = "";
  const rows = topPatterns(allAlerts, 6);
  if (rows.length === 0) {
    const tr = el("tr", { className: "empty-row" });
    tr.appendChild(el("td", { attrs: { colspan: "4" }, text: "No alert patterns yet." }));
    patternsTableBody.appendChild(tr);
    return;
  }
  rows.forEach((row) => {
    const tr = el("tr", { className: "expandable" });
    tr.appendChild(el("td", { className: "col-pattern" }, [
      el("span", { className: "truncate", text: row.key, title: row.key }),
    ]));
    const spark = sparkValuesFor(row.alerts, metrics.timeBuckets);
    tr.appendChild(el("td", { className: "col-spark" }, [sparklineEl(spark, dominantSeverityClass(row.sev))]));
    const topSev = Object.entries(row.sev).sort((a, b) => b[1] - a[1])[0][0];
    tr.appendChild(el("td", {}, pill(`sev-${topSev.toLowerCase()}`, topSev)));
    tr.appendChild(el("td", { className: "col-num", text: row.count.toLocaleString() }));
    tr.addEventListener("click", () => {
      searchInput.value = row.key.slice(0, 30);
      applyAndRender();
    });
    patternsTableBody.appendChild(tr);
  });
}

function renderArtifactsTable(metrics) {
  artifactsTableBody.textContent = "";
  const rows = topArtifacts(allAlerts, 6);
  if (rows.length === 0) {
    const tr = el("tr", { className: "empty-row" });
    tr.appendChild(el("td", { attrs: { colspan: "4" }, text: "No artifacts seen yet." }));
    artifactsTableBody.appendChild(tr);
    return;
  }
  rows.forEach((row) => {
    const tr = el("tr", { className: "expandable" });
    tr.appendChild(el("td", { className: "col-artifact" }, [
      el("span", { className: "truncate mono-cell", text: row.key, title: row.key }),
    ]));
    const spark = sparkValuesFor(row.alerts, metrics.timeBuckets);
    const sevClass = row.high > 0 ? "sev-high" : "";
    tr.appendChild(el("td", { className: "col-spark" }, [sparklineEl(spark, sevClass)]));
    tr.appendChild(el("td", { className: "col-num", text: row.count.toLocaleString() }));
    tr.appendChild(el("td", { className: "col-num", text: row.high.toLocaleString() }));
    tr.addEventListener("click", () => {
      searchInput.value = row.key;
      applyAndRender();
    });
    artifactsTableBody.appendChild(tr);
  });
}

// ── KPI rendering ───────────────────────────────────────────────
function kpiSpark(buckets, overTime, field) {
  return buckets.map((k) => {
    const b = overTime[k];
    if (field === "total") return b.total;
    if (field === "high") return b.HIGH;
    if (field === "pending") return b.pending;
    if (field === "errors") return b.errors;
    if (field === "SIEM" || field === "EDR" || field === "API") return b[field] || 0;
    return 0;
  });
}

function renderKPIs(metrics) {
  const map = {
    total:   { value: metrics.total, field: "total" },
    siem:    { value: metrics.bySource.SIEM, field: "SIEM" },
    edr:     { value: metrics.bySource.EDR, field: "EDR" },
    api:     { value: metrics.bySource.API, field: "API" },
  };

  const errorCount = metrics.byStatus.ERROR || 0;
  retryAllErrorsBtn.disabled = errorCount === 0;
  retryAllErrorsBtn.textContent = errorCount > 0
    ? `↻ Retry All Errors (${errorCount})`
    : "↻ Retry All Errors";

  Object.entries(map).forEach(([key, cfg]) => {
    const card = document.querySelector(`.kpi[data-key="${key}"]`);
    if (!card) return;
    const valueEl = card.querySelector('[data-field="value"]');
    const deltaEl = card.querySelector('[data-field="delta"]');
    const sparkEl = card.querySelector('[data-field="spark"]');

    if (valueEl) valueEl.textContent = cfg.value.toLocaleString();

    const values = kpiSpark(metrics.timeBuckets, metrics.overTime, cfg.field);

    if (deltaEl) {
      const half = Math.floor(values.length / 2);
      const recent = values.slice(half).reduce((s, v) => s + v, 0);
      const prior = values.slice(0, half).reduce((s, v) => s + v, 0);
      const diff = recent - prior;
      let cls = "zero";
      let txt = "0";
      let arrow = "→";
      if (diff > 0) {
        cls = "up";
        arrow = "↑";
        txt = `+${diff}`;
      } else if (diff < 0) {
        cls = "down";
        arrow = "↓";
        txt = `${diff}`;
      }
      deltaEl.className = `kpi-delta ${cls}`;
      deltaEl.textContent = "";
      deltaEl.appendChild(el("span", { className: "arrow", text: arrow }));
      deltaEl.appendChild(document.createTextNode(` ${txt}`));
    }

    if (sparkEl) {
      sparkEl.textContent = "";
      const max = Math.max(1, ...values);
      values.forEach((v) => {
        sparkEl.appendChild(el("div", { className: "bar", style: { height: `${(v / max) * 100}%` } }));
      });
    }
  });
}

// ── Charts ──────────────────────────────────────────────────────
function gridStyle() {
  return { color: COLOR.grid, drawBorder: false };
}
const tooltipDefaults = {
  backgroundColor: "#0a0f1c",
  borderColor: COLOR.border,
  borderWidth: 1,
  titleColor: COLOR.text,
  bodyColor: COLOR.text,
  padding: 10,
  cornerRadius: 6,
  displayColors: true,
};

function renderSeverityChart(metrics) {
  const ctx = document.getElementById("severityChart");
  if (!ctx) return;
  const data = {
    labels: ["HIGH", "MEDIUM", "LOW"],
    datasets: [{
      data: [metrics.bySeverity.HIGH, metrics.bySeverity.MEDIUM, metrics.bySeverity.LOW],
      backgroundColor: [COLOR.danger, COLOR.warning, COLOR.success],
      borderRadius: 4,
      borderSkipped: false,
      barThickness: 22,
    }],
  };
  const meta = $("severityMeta");
  if (meta) meta.textContent = `${metrics.total} total · ${metrics.bySeverity.HIGH} high`;

  if (charts.severity) { charts.severity.data = data; charts.severity.update(); return; }
  charts.severity = new Chart(ctx, {
    type: "bar",
    data,
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: tooltipDefaults },
      scales: {
        x: { grid: gridStyle(), ticks: { precision: 0 } },
        y: { grid: { display: false }, ticks: { font: { weight: 700 } } },
      },
    },
  });
}

function renderSourceChart(metrics) {
  const ctx = document.getElementById("sourceChart");
  if (!ctx) return;
  const data = {
    labels: ["SIEM", "EDR", "API"],
    datasets: [{
      data: [metrics.bySource.SIEM, metrics.bySource.EDR, metrics.bySource.API],
      backgroundColor: [COLOR.cyan, COLOR.purple, COLOR.teal],
      borderColor: COLOR.bg,
      borderWidth: 2,
      hoverOffset: 6,
    }],
  };
  if (charts.source) { charts.source.data = data; charts.source.update(); return; }
  charts.source = new Chart(ctx, {
    type: "doughnut",
    data,
    options: {
      maintainAspectRatio: false,
      cutout: "65%",
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 8, boxHeight: 8, padding: 12, color: COLOR.muted } },
        tooltip: tooltipDefaults,
      },
    },
  });
}

function renderRiskChart(metrics) {
  const ctx = document.getElementById("riskChart");
  if (!ctx) return;
  const total = metrics.byRisk.HIGH + metrics.byRisk.MEDIUM + metrics.byRisk.LOW + metrics.byRisk.ERROR;
  const meta = $("riskMeta");
  if (meta) meta.textContent = `${total} analyzed`;
  const data = {
    labels: ["HIGH", "MEDIUM", "LOW", "ERROR"],
    datasets: [{
      data: [metrics.byRisk.HIGH, metrics.byRisk.MEDIUM, metrics.byRisk.LOW, metrics.byRisk.ERROR],
      backgroundColor: [COLOR.danger, COLOR.warning, COLOR.success, COLOR.muted],
      borderColor: COLOR.bg,
      borderWidth: 2,
      hoverOffset: 6,
    }],
  };
  if (charts.risk) { charts.risk.data = data; charts.risk.update(); return; }
  charts.risk = new Chart(ctx, {
    type: "doughnut",
    data,
    options: {
      maintainAspectRatio: false,
      cutout: "65%",
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 8, boxHeight: 8, padding: 12, color: COLOR.muted } },
        tooltip: tooltipDefaults,
      },
    },
  });
}

function renderStatusChart(metrics) {
  const ctx = document.getElementById("statusChart");
  if (!ctx) return;
  const data = {
    labels: ["PENDING", "PROCESSING", "COMPLETE", "ERROR"],
    datasets: [{
      data: [metrics.byStatus.PENDING, metrics.byStatus.PROCESSING, metrics.byStatus.COMPLETE, metrics.byStatus.ERROR],
      backgroundColor: [COLOR.warning, COLOR.accent, COLOR.success, COLOR.danger],
      borderRadius: 4,
      borderSkipped: false,
      barThickness: 18,
    }],
  };
  if (charts.status) { charts.status.data = data; charts.status.update(); return; }
  charts.status = new Chart(ctx, {
    type: "bar",
    data,
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: tooltipDefaults },
      scales: {
        x: { grid: gridStyle(), ticks: { precision: 0 } },
        y: { grid: { display: false }, ticks: { font: { size: 10, weight: 700 } } },
      },
    },
  });
}

// ── Retry all errors ───────────────────────────────────────────
retryAllErrorsBtn.addEventListener("click", async () => {
  retryAllErrorsBtn.disabled = true;
  const original = retryAllErrorsBtn.textContent;
  retryAllErrorsBtn.textContent = "Re-queuing…";
  try {
    const res = await fetch("/alerts/retry-errors", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed");
    retryAllErrorsBtn.textContent = `Queued ${data.count}`;
    loadAlerts();
    setTimeout(() => {
      retryAllErrorsBtn.textContent = original;
    }, 2000);
  } catch (err) {
    retryAllErrorsBtn.textContent = original;
    retryAllErrorsBtn.title = err.message;
  }
});

// ── Update orchestration ────────────────────────────────────────
function applyAndRender() {
  filteredAlerts = applyFilters(allAlerts);
  renderAlertsTable();
}

function updateDashboard() {
  const metrics = computeMetrics(allAlerts);
  renderKPIs(metrics);
  renderSeverityChart(metrics);
  renderSourceChart(metrics);
  renderRiskChart(metrics);
  renderStatusChart(metrics);
  renderPatternsTable(metrics);
  renderArtifactsTable(metrics);
  applyAndRender();

  const now = new Date();
  lastUpdate.textContent = `updated ${fmtTime(now)}`;
}

// ── Data fetching ──────────────────────────────────────────────
async function loadAlerts() {
  try {
    const res = await fetch("/alerts");
    if (!res.ok) throw new Error("Failed to load alerts");
    allAlerts = await res.json();
    updateDashboard();
  } catch (error) {
    alertsBody.textContent = "";
    const tr = el("tr", { className: "empty-row" });
    tr.appendChild(el("td", { attrs: { colspan: "9" }, style: { color: COLOR.danger }, text: error.message }));
    alertsBody.appendChild(tr);
  }
}

// ── New alert form ─────────────────────────────────────────────
newAlertForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  formMessage.textContent = "Submitting alert…";
  formMessage.className = "form-message";

  const form = new FormData(newAlertForm);
  const payload = {
    source: form.get("source"),
    severity: form.get("severity"),
    description: String(form.get("description") || "").trim(),
    artifacts: String(form.get("artifacts") || "")
      .split(",").map((s) => s.trim()).filter(Boolean),
  };

  try {
    const res = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Submission failed");
    formMessage.textContent = "Alert submitted successfully.";
    formMessage.className = "form-message success";
    newAlertForm.reset();
    loadAlerts();
    setTimeout(closeNewAlertPanel, 700);
  } catch (error) {
    formMessage.textContent = error && error.message ? error.message : "Submission failed";
    formMessage.className = "form-message error";
  }
});

// ── Wiring ─────────────────────────────────────────────────────
refreshBtn.addEventListener("click", loadAlerts);
[sourceFilter, severityFilter, statusFilter].forEach((s) => s.addEventListener("change", () => {
  currentPage = 1;
  applyAndRender();
}));
let searchDebounce;
searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    currentPage = 1;
    applyAndRender();
  }, 120);
});

// ── SSE live updates ───────────────────────────────────────────
function setConnState(online) {
  const textEl = connStatus.querySelector(".status-text");
  if (online) {
    connStatus.classList.remove("offline");
    if (textEl) textEl.textContent = "live";
  } else {
    connStatus.classList.add("offline");
    if (textEl) textEl.textContent = "offline";
  }
}
const eventSource = new EventSource("/stream");
eventSource.onopen = () => setConnState(true);
eventSource.onerror = () => setConnState(false);
eventSource.onmessage = (event) => {
  try {
    const payload = JSON.parse(event.data);
    if (["new_alert", "status", "analysis"].includes(payload.type)) {
      loadAlerts();
    }
  } catch (err) {
    console.warn("SSE parse error", err);
  }
};

loadAlerts();
