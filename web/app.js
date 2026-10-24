const state = {
  corpus: null,
  layer: "decision",
  category: "all",
  caseId: null,
  query: "",
  agency: "all",
};

const LAYER_ORDER = ["decision", "question", "setting", "judgement"];
const FDA_LAYER = "fda-release";

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function readHash() {
  const parts = (location.hash.replace(/^#/, "") || "/decision/all").split("/").filter(Boolean);
  const layer = parts[0] === FDA_LAYER || LAYER_ORDER.includes(parts[0]) ? parts[0] : "decision";
  const category = parts[1] || "all";
  const caseAt = parts.indexOf("case");
  return {
    layer,
    category,
    caseId: caseAt >= 0 ? parts[caseAt + 1] : null,
  };
}

function writeHash() {
  const bits = [state.layer, state.category];
  if (state.caseId) bits.push("case", state.caseId);
  const next = "#/" + bits.join("/");
  if (location.hash !== next) location.hash = next;
}

function recordMatches(record) {
  if (state.agency !== "all" && record.agency !== state.agency) return false;
  const q = state.query.trim().toLowerCase();
  if (!q) return true;
  const hay = [
    record.drug, record.indication, record.assessment, record.issues, record.quote,
    record.role, record.data_source, record.application, record.rwe_type, record.design,
    record.summary, record.theme1, record.theme2,
  ].join(" ").toLowerCase();
  return q.split(/\s+/).every((word) => hay.includes(word));
}

function inCategory(record) {
  if (state.category === "all") return true;
  if (state.layer === "decision") return record.decision_id === state.category;
  if (state.layer === "question") return record.question_id === state.category;
  if (state.layer === "setting") return record.settings.some((item) => item.id === state.category);
  return record.judgements.some((item) => item.id === state.category);
}

function visibleRecords() {
  return state.corpus.records
    .filter((record) => recordMatches(record) && inCategory(record))
    .sort((a, b) => (b.year || "").localeCompare(a.year || "") || a.drug.localeCompare(b.drug));
}

function categoryStats(categoryId) {
  const saved = state.category;
  state.category = categoryId;
  const rows = state.corpus.records.filter((record) => recordMatches(record) && inCategory(record));
  state.category = saved;
  return {
    n: rows.length,
    fda: rows.filter((record) => record.agency === "FDA").length,
    ema: rows.filter((record) => record.agency === "EMA").length,
  };
}

function renderChrome() {
  const counts = state.corpus.counts;
  document.getElementById("lede").textContent =
    `${counts.documents} documents` +
    (counts.needs_manual_review ? `. ${counts.needs_manual_review} need manual review.` : ".");

  const layers = document.getElementById("layers");
  layers.innerHTML = LAYER_ORDER.map((id) => {
    const layer = state.corpus.layers[id];
    const current = id === state.layer;
    return `<button type="button" data-layer="${id}" ${current ? 'aria-current="page"' : ""}>${esc(layer.title)}</button>`;
  }).join("") + `<button type="button" data-layer="${FDA_LAYER}" ${state.layer === FDA_LAYER ? 'aria-current="page"' : ""}>FDA’s own examples</button>`;

  const filters = document.getElementById("filters");
  const agencies = [["all", "Both agencies"], ["FDA", "FDA"], ["EMA", "EMA"]];
  filters.innerHTML =
    agencies.map(([id, label]) =>
      `<button type="button" data-agency="${id}" aria-pressed="${state.agency === id}">${label}</button>`).join("") +
    `<span class="count" id="shown"></span>`;
}

function renderList() {
  const layer = state.corpus.layers[state.layer];
  const categories = [{ id: "all", label: "Everything in this layer", lesson: layer.orientation, count: null }]
    .concat(layer.categories);
  const active = categories.some((cat) => cat.id === state.category) ? state.category : "all";
  state.category = active;
  const rows = visibleRecords();
  const selected = categories.find((cat) => cat.id === active);

  const cats = categories.map((cat) => {
    const stats = categoryStats(cat.id);
    const meta = cat.id === "all" ? `${stats.n} shown` : `${stats.n} shown · ${stats.fda} FDA · ${stats.ema} EMA`;
    return `<button type="button" data-category="${esc(cat.id)}" ${cat.id === active ? 'aria-current="true"' : ""}>
      <span class="cat-label">${esc(cat.label)}</span>
      <span class="cat-meta">${esc(meta)}</span>
    </button>`;
  }).join("");

  const barCounts = layer.categories.map((cat) => ({ ...cat, shown: categoryStats(cat.id).n }));
  const maxBar = Math.max(...barCounts.map((cat) => cat.shown), 1);
  const bars = state.category === "all" ? `<div class="bars">${barCounts.map((cat) => `
    <div class="bar-row">
      <span>${esc(cat.label)}</span>
      <div class="bar"><span style="width:${Math.round(100 * cat.shown / maxBar)}%"></span></div>
      <span>${cat.shown}</span>
    </div>`).join("")}</div>` : "";

  const list = rows.length ? `<div class="case-list">${rows.map(caseRow).join("")}</div>` :
    `<p class="empty">Nothing in this layer matches the current search and filters.</p>`;

  document.getElementById("main").innerHTML = `<div class="workspace">
    <aside class="categories">${cats}</aside>
    <section class="reading">
      <div class="orientation">
        <h2>${esc(selected.label)}</h2>
        <p>${esc(selected.lesson || layer.orientation)}</p>
        ${bars}
      </div>
      ${list}
    </section>
  </div>`;
  document.getElementById("shown").textContent = `${rows.length} documents`;
}

function caseRow(record) {
  const review = record.needs_manual_review ? `<span class="badge screen">Needs manual review</span>` : "";
  return `<button type="button" class="case-row" data-case="${esc(record.id)}">
    <div class="meta">
      <span class="badge ${record.agency.toLowerCase()}">${esc(record.agency)}</span>
      ${review}
      <span class="year">${esc(record.year)}</span>
    </div>
    <div>
      <h3>${esc(record.drug)}</h3>
      <p class="snippet">${esc(record.summary)}</p>
      <div class="tags"><span class="tag">${esc(record.decision)}</span></div>
    </div>
  </button>`;
}

function renderCase() {
  const record = state.corpus.records.find((item) => item.id === state.caseId);
  if (!record) {
    document.getElementById("main").innerHTML = `<div class="reading"><p class="empty">That document is not in the corpus.</p></div>`;
    return;
  }
  const chips = [
    ["decision", record.decision_id, record.decision],
    ["question", record.question_id, record.question],
    ...record.settings.map((item) => ["setting", item.id, item.label]),
    ...record.judgements.map((item) => ["judgement", item.id, item.label]),
  ];
  const documentUrl = record.document_url
    ? `${record.document_url}${record.page ? `#page=${record.page}` : ""}`
    : "";
  const documentLabel = record.page
    ? `Open page ${record.page} of the ${record.document_title || "public review"}`
    : record.document_url
      ? `Open the ${record.document_title || "public review"}`
      : "";
  const productLabel = record.agency === "EMA" ? "EMA medicine page" : "Drugs@FDA product page";
  const links = [
    documentUrl ? `<a class="doc-link" href="${esc(documentUrl)}" target="_blank" rel="noreferrer">${esc(documentLabel)}</a>` : "",
    record.fda_example_url ? `<a class="text-link" href="${esc(record.fda_example_url)}" target="_blank" rel="noreferrer">FDA’s published example</a>` : "",
    record.source_url ? `<a class="text-link" href="${esc(record.source_url)}" target="_blank" rel="noreferrer">${productLabel}</a>` : "",
  ].filter(Boolean).join("");
  const where = record.location_note
    || "The product page is linked. The page of this passage has not been recorded yet.";
  const banner = record.needs_manual_review
    ? `<div class="banner">${esc(record.curation || "Needs manual review.")}</div>` : "";
  document.getElementById("main").innerHTML = `<div class="reading case">
    <button type="button" class="back" id="back">Back to the list</button>
    <header class="case-head">
      <div class="meta">
        <span class="badge ${record.agency.toLowerCase()}">${esc(record.agency)}</span>
        <span class="year">${esc(record.year)}</span>
        ${record.needs_manual_review ? `<span class="badge screen">Needs manual review</span>` : ""}
      </div>
      <h2>${esc(record.drug)}</h2>
      <p class="appl">${esc(record.application)}</p>
    </header>
    ${banner}
    <div class="tags">${chips.map(([layer, id, label]) =>
      `<button type="button" class="chip-button" data-goto="${esc(layer)}" data-category="${esc(id)}">${esc(label)}</button>`).join("")}</div>
    <section class="section">
      <h3>What was recorded about the evidence</h3>
      <p class="prose">${esc(record.assessment || "No assessment summary was recorded.")}</p>
    </section>
    <section class="section">
      <h3>Methodological feedback</h3>
      <p>${esc(record.issues || "No methodological issues were recorded.")}</p>
    </section>
    <section class="section">
      <h3>Where this was said</h3>
      <p class="where">${esc(where)}</p>
    </section>
    <section class="section">
      <h3>Passage from the public document</h3>
      <blockquote class="quote">${esc(record.quote || "No passage was extracted.")}</blockquote>
    </section>
    <section class="section">
      <h3>How the evidence was described</h3>
      <p>${esc([record.rwe_type, record.design, record.data_source, record.comparator, record.role].filter(Boolean).join(" · "))}</p>
    </section>
    <section class="section">
      <h3>Indication</h3>
      <p>${esc(record.indication || "Not recorded.")}</p>
    </section>
    <div class="links">${links}</div>
  </div>`;
  document.getElementById("shown").textContent = record.drug;
}

function releaseVisible(text) {
  const q = state.query.trim().toLowerCase();
  if (!q) return true;
  return q.split(/\s+/).every((word) => text.toLowerCase().includes(word));
}

function renderFdaRelease() {
  const release = state.corpus.fda_release;
  if (!release) {
    document.getElementById("main").innerHTML = `<div class="reading"><p class="empty">FDA’s published examples have not been compared yet. From this folder, run python3 pipeline/locate_documents.py and then rebuild the corpus.</p></div>`;
    document.getElementById("shown").textContent = "";
    return;
  }
  const counts = release.counts || {};
  const shared = (release.in_both || []).filter((row) =>
    releaseVisible([row.product, row.action, row.summary, ...(row.matches || []).map((item) => item.drug)].join(" ")));
  const missing = (release.fda_only || []).filter((row) =>
    releaseVisible([row.product, row.action, row.summary].join(" ")));
  const extra = (release.corpus_only || []).filter((row) =>
    releaseVisible([row.drug, row.application, row.decision, row.year].join(" ")));
  const card = (row, body) => `<article class="release-card">
    <h3>${esc(row.product || row.drug)}</h3>
    <p class="release-meta">${esc(row.table || [row.year, row.application, row.decision].filter(Boolean).join(" · "))}</p>
    ${body}
  </article>`;
  const sharedHtml = shared.map((row) => card(row, `
    <p>${esc(row.action)}</p>
    <div class="tags">${(row.matches || []).map((item) =>
      `<button type="button" class="chip-button" data-case="${esc(item.id)}">${esc(item.drug)}</button>`).join("")}</div>
    <p><a class="text-link" href="${esc(row.url)}" target="_blank" rel="noreferrer">Open ${esc(row.table)}</a></p>
  `)).join("");
  const missingHtml = missing.map((row) => card(row, `
    <p>${esc(row.action)}</p>
    <p><a class="text-link" href="${esc(row.url)}" target="_blank" rel="noreferrer">Open ${esc(row.table)}</a></p>
  `)).join("");
  const extraHtml = extra.map((row) => card(row, `
    <div class="tags"><button type="button" class="chip-button" data-case="${esc(row.id)}">Open this entry</button></div>
  `)).join("");
  document.getElementById("main").innerHTML = `<div class="reading release">
    <div class="orientation">
      <h2>Checked against FDA’s own examples</h2>
      <p>FDA publishes three tables of cases in which it used real-world evidence: CDER drug approvals, CDER postmarketing studies, and CBER safety labeling. This check was run on ${esc(release.checked_on)}. A row is shared when the application number, the brand name, or the class name agrees. FDA lists ${counts.examples || 0} examples. ${counts.in_both || 0} of those match an FDA entry in this navigator, ${counts.fda_only || 0} are on FDA’s list only, and ${counts.corpus_only || 0} FDA entries here are not on those tables.</p>
    </div>
    <section class="release-block">
      <h2>On both lists <span>${shared.length}</span></h2>
      ${sharedHtml || `<p class="empty">No shared example matches the current search.</p>`}
    </section>
    <section class="release-block">
      <h2>On FDA’s list only <span>${missing.length}</span></h2>
      <p class="release-intro">These are in FDA’s published tables and are absent from this navigator.</p>
      ${missingHtml || `<p class="empty">No FDA-only example matches the current search.</p>`}
    </section>
    <section class="release-block">
      <h2>In this navigator only <span>${extra.length}</span></h2>
      <p class="release-intro">These FDA reviews are in the navigator and are absent from the three FDA tables.</p>
      ${extraHtml || `<p class="empty">No navigator-only entry matches the current search.</p>`}
    </section>
  </div>`;
  document.getElementById("shown").textContent = `${shared.length + missing.length + extra.length} rows`;
}

function render() {
  const route = readHash();
  state.layer = route.layer;
  state.category = route.category;
  state.caseId = route.caseId;
  renderChrome();
  if (state.caseId) renderCase();
  else if (state.layer === FDA_LAYER) renderFdaRelease();
  else renderList();
}

function openLayer(layer, category = "all") {
  state.layer = layer;
  state.category = category;
  state.caseId = null;
  writeHash();
}

document.addEventListener("click", (event) => {
  const layer = event.target.closest("[data-layer]");
  if (layer) { openLayer(layer.dataset.layer); return; }
  const category = event.target.closest("[data-category]");
  if (category && category.closest(".categories")) {
    openLayer(state.layer, category.dataset.category);
    return;
  }
  const card = event.target.closest("[data-case]");
  if (card) {
    state.caseId = card.dataset.case;
    writeHash();
    return;
  }
  if (event.target.id === "back") {
    state.caseId = null;
    writeHash();
    return;
  }
  const agency = event.target.closest("[data-agency]");
  if (agency) { state.agency = agency.dataset.agency; render(); return; }
  const go = event.target.closest("[data-goto]");
  if (go) { openLayer(go.dataset.goto, go.dataset.category); }
});

document.getElementById("search-form").addEventListener("submit", (event) => event.preventDefault());
document.getElementById("q").addEventListener("input", (event) => {
  state.query = event.target.value;
  if (state.caseId) {
    state.caseId = null;
    writeHash();
  } else {
    render();
  }
});
window.addEventListener("hashchange", render);

async function loadCorpus() {
  const urls = ["/api/corpus?v=5", "/corpus.json", "/data/corpus.json"];
  let lastError = null;
  for (const url of urls) {
    try {
      const response = await fetch(url);
      if (!response.ok) continue;
      const payload = await response.json();
      if (payload && payload.records) return payload;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("corpus missing");
}

loadCorpus()
  .then((corpus) => {
    state.corpus = corpus;
    if (!location.hash) location.hash = "#/decision/all";
    render();
  })
  .catch(() => {
    document.getElementById("main").innerHTML = `<div class="reading"><p class="empty">The corpus is not available. Run python3 pipeline/build_corpus.py and then python3 serve.py.</p></div>`;
  });
