const state = {
  events: [],
  source: "all",
  hideChecks: true,
  token: sessionStorage.getItem("reg4rwe-usage-token") || "",
};

const gate = document.getElementById("gate");
const tokenInput = document.getElementById("token");
const summary = document.getElementById("summary");
const filters = document.getElementById("filters");
const main = document.getElementById("main");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function when(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso || "";
  return date.toLocaleString(undefined, {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function isCheck(event) {
  return (event.design || "").startsWith("Usage log check");
}

function visible() {
  return state.events.filter((event) => {
    if (state.source !== "all" && event.source !== state.source) return false;
    if (state.hideChecks && isCheck(event)) return false;
    return true;
  });
}

function counts(events, key) {
  const tally = {};
  for (const event of events) {
    const name = event[key] || "unknown";
    tally[name] = (tally[name] || 0) + 1;
  }
  return Object.entries(tally).sort((a, b) => b[1] - a[1]);
}

function renderSummary(shown) {
  const designs = new Set(shown.map((event) => event.design));
  const sources = counts(shown, "source");
  const precedents = {};
  for (const event of shown) {
    for (const name of event.precedents || []) {
      precedents[name] = (precedents[name] || 0) + 1;
    }
  }
  const top = Object.entries(precedents).sort((a, b) => b[1] - a[1]).slice(0, 6);
  summary.hidden = false;
  summary.innerHTML = `
    <article><p>Appraisals</p><strong>${shown.length}</strong></article>
    <article><p>Distinct designs</p><strong>${designs.size}</strong></article>
    <article><p>Where they came from</p><strong>${sources.map(([name, count]) => `${esc(name)} ${count}`).join(" · ") || "none"}</strong></article>
    <article class="wide"><p>Precedents returned most often</p><strong>${top.map(([name, count]) => `${esc(name.split("—")[0].trim())} ${count}`).join(" · ") || "none"}</strong></article>
  `;
}

function renderFilters() {
  filters.hidden = false;
  const sources = ["all", "mcp", "http", "local"];
  filters.innerHTML = sources.map((source) => `
    <button type="button" data-source="${source}" aria-pressed="${state.source === source}">${source === "all" ? "All sources" : source}</button>
  `).join("") + `
    <button type="button" id="checks" aria-pressed="${state.hideChecks}">Hide setup checks</button>
    <button type="button" id="refresh">Refresh</button>
  `;
}

function renderList(shown) {
  if (!shown.length) {
    main.innerHTML = `<p class="empty">No appraisals in this view.</p>`;
    return;
  }
  main.innerHTML = `<div class="case-list">${shown.map((event) => `
    <article class="log-card">
      <div class="meta">
        <span class="badge ${event.source === "mcp" ? "fda" : event.source === "http" ? "ema" : "screen"}">${esc(event.source)}</span>
        <span class="badge screen">${esc(event.outcome)}</span>
        <span class="year">${esc(when(event.at))}</span>
      </div>
      <p class="design">${esc(event.design)}</p>
      <div class="tags">${(event.precedents || []).map((name) => `<span class="tag">${esc(name)}</span>`).join("") || `<span class="tag">No precedent returned</span>`}</div>
    </article>
  `).join("")}</div>`;
}

function render() {
  const shown = visible();
  renderSummary(shown);
  renderFilters();
  renderList(shown);
}

async function load(token) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch("/api/usage?limit=100", { headers, cache: "no-store" });
  if (response.status === 404) {
    gate.hidden = false;
    summary.hidden = true;
    filters.hidden = true;
    main.innerHTML = `<p class="empty">The read token was not accepted.</p>`;
    return false;
  }
  if (!response.ok) {
    main.innerHTML = `<p class="empty">The log could not be read.</p>`;
    return false;
  }
  const payload = await response.json();
  state.events = payload.events || [];
  gate.hidden = true;
  render();
  return true;
}

gate.addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = tokenInput.value.trim();
  if (!token) return;
  const ok = await load(token);
  if (ok) sessionStorage.setItem("reg4rwe-usage-token", token);
});

document.body.addEventListener("click", (event) => {
  const source = event.target.closest("[data-source]");
  if (source) {
    state.source = source.dataset.source;
    render();
    return;
  }
  if (event.target.id === "checks") {
    state.hideChecks = !state.hideChecks;
    render();
    return;
  }
  if (event.target.id === "refresh") load(state.token);
});

load(state.token);
