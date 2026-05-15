// ── DOM refs ────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const runBtn = $("runTestsBtn");
const suiteStatus = $("suiteStatus");
const suiteSub = $("suiteSub");
const lastRun = $("lastRun");
const healthBody = $("healthBody");
const healthSearch = $("healthSearch");
const outcomeFilter = $("outcomeFilter");
const healthRowCount = $("healthRowCount");
const healthFootMeta = $("healthFootMeta");

const kpi = {
  total:    $("kpiTotal"),
  passed:   $("kpiPassed"),
  failed:   $("kpiFailed"),
  errors:   $("kpiErrors"),
  skipped:  $("kpiSkipped"),
  duration: $("kpiDuration"),
  passedPct: $("kpiPassedPct"),
  totalSub:  $("kpiTotalSub"),
};

// ── State ───────────────────────────────────────────────────────
let lastResult = null;

// ── Utils ───────────────────────────────────────────────────────
function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.className) node.className = opts.className;
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.title) node.title = opts.title;
  if (opts.attrs) Object.entries(opts.attrs).forEach(([k, v]) => node.setAttribute(k, v));
  (Array.isArray(children) ? children : [children]).forEach((c) => {
    if (c == null) return;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return node;
}

function fmtDuration(seconds) {
  if (seconds == null) return "—";
  if (seconds < 0.001) return "<1ms";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(2)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return `${m}m ${s}s`;
}

function setSuiteStatus(state, label) {
  suiteStatus.classList.remove("ok", "fail", "running", "offline");
  if (state) suiteStatus.classList.add(state);
  const txt = suiteStatus.querySelector(".status-text");
  if (txt) txt.textContent = label;
}

function outcomePill(outcome) {
  return el("span", { className: `pill outcome-${outcome}`, text: outcome });
}

// ── Render ──────────────────────────────────────────────────────
function renderSummary(data) {
  const s = data.summary || {};
  kpi.total.textContent = (s.total || 0).toLocaleString();
  kpi.passed.textContent = (s.passed || 0).toLocaleString();
  kpi.failed.textContent = (s.failed || 0).toLocaleString();
  kpi.errors.textContent = (s.error || 0).toLocaleString();
  kpi.skipped.textContent = (s.skipped || 0).toLocaleString();
  kpi.duration.textContent = fmtDuration(s.duration || 0);

  const pct = s.total ? Math.round((s.passed / s.total) * 100) : 0;
  kpi.passedPct.textContent = `${pct}%`;
  kpi.passedPct.className = "kpi-delta " + (pct === 100 ? "down" : pct >= 80 ? "zero" : "up");

  kpi.totalSub.textContent = `wall ${fmtDuration(data.duration || s.duration || 0)}`;

  if (s.failed > 0 || s.error > 0) {
    setSuiteStatus("fail", `${s.failed + s.error} failing`);
    suiteSub.textContent = `${s.failed} failed · ${s.error} errored · ${s.passed} passed`;
  } else if (s.total === 0) {
    setSuiteStatus("offline", "no tests");
    suiteSub.textContent = "no tests collected";
  } else {
    setSuiteStatus("ok", "all green");
    suiteSub.textContent = `all ${s.total} tests passed in ${fmtDuration(s.duration || 0)}`;
  }

  if (data.ran_at) {
    const d = new Date(data.ran_at);
    lastRun.textContent = `last run · ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  }
}

function applyAndRenderTable() {
  if (!lastResult) return;
  const tests = lastResult.tests || [];
  const q = (healthSearch.value || "").trim().toLowerCase();
  const oc = outcomeFilter.value;
  const filtered = tests.filter((t) => {
    if (oc && t.outcome !== oc) return false;
    if (!q) return true;
    return (t.nodeid || "").toLowerCase().includes(q) ||
           (t.name || "").toLowerCase().includes(q);
  });

  healthBody.textContent = "";
  healthRowCount.textContent = `${filtered.length.toLocaleString()} of ${tests.length} test${tests.length === 1 ? "" : "s"}`;
  healthFootMeta.textContent = `exit code ${lastResult.exit_code}`;

  if (filtered.length === 0) {
    const tr = el("tr", { className: "empty-row" });
    tr.appendChild(el("td", { attrs: { colspan: "5" }, text: tests.length === 0 ? "No tests collected." : "No tests match the current filters." }));
    healthBody.appendChild(tr);
    return;
  }

  filtered.forEach((t) => {
    const tr = el("tr", { className: "expandable" });
    tr.appendChild(el("td", {}, outcomePill(t.outcome)));
    tr.appendChild(el("td", { className: "mono-cell" }, [
      el("span", { className: "truncate", text: t.module || "—", title: t.module || "" }),
    ]));
    tr.appendChild(el("td", { className: "mono-cell" }, [
      el("span", { className: "truncate", text: t.name || "—", title: t.name || "" }),
    ]));
    tr.appendChild(el("td", { className: "mono-cell col-num", text: fmtDuration(t.duration) }));
    const actionCell = el("td", { className: "col-action" });
    if (t.longrepr) {
      const btn = el("button", { className: "retry-btn", text: "View trace" });
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleTrace(tr, t.longrepr);
      });
      actionCell.appendChild(btn);
    }
    tr.appendChild(actionCell);
    tr.addEventListener("click", () => {
      if (t.longrepr) toggleTrace(tr, t.longrepr);
    });
    healthBody.appendChild(tr);
  });
}

function toggleTrace(tr, trace) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("trace-row")) {
    next.remove();
    return;
  }
  const traceTr = el("tr", { className: "trace-row" });
  const td = el("td", { attrs: { colspan: "5" } });
  td.appendChild(el("pre", { className: "trace-block", text: trace }));
  traceTr.appendChild(td);
  tr.after(traceTr);
}

// ── Run ─────────────────────────────────────────────────────────
async function runTests() {
  if (runBtn.disabled) return;
  runBtn.disabled = true;
  const originalText = runBtn.textContent;
  runBtn.textContent = "Running…";
  setSuiteStatus("running", "running");
  suiteSub.textContent = "pytest is running…";

  try {
    const res = await fetch("/health/run");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    lastResult = data;
    renderSummary(data);
    applyAndRenderTable();
  } catch (err) {
    setSuiteStatus("fail", "request failed");
    suiteSub.textContent = err.message || "Failed to run tests";
    healthBody.textContent = "";
    const tr = el("tr", { className: "empty-row" });
    tr.appendChild(el("td", { attrs: { colspan: "5" }, text: `Error: ${err.message || "unknown"}` }));
    healthBody.appendChild(tr);
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "";
    runBtn.appendChild(el("span", { text: originalText.trim() || "Run Tests" }));
  }
}

runBtn.addEventListener("click", runTests);
healthSearch.addEventListener("input", () => {
  clearTimeout(healthSearch._t);
  healthSearch._t = setTimeout(applyAndRenderTable, 120);
});
outcomeFilter.addEventListener("change", applyAndRenderTable);

// Auto-run on page load so the user sees fresh results immediately.
runTests();
