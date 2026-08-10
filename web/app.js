const $ = (id) => document.getElementById(id);

const state = {
  apiBase: normaliseBase(new URLSearchParams(window.location.search).get("api") || localStorage.getItem("igraph_api") || "http://localhost:8000"),
  analysis: null,
  health: null,
  toastTimer: null,
};

const riskColors = {
  low: "#91efc7",
  medium: "#f2c46e",
  high: "#ffad76",
  critical: "#ff8b86",
};

function normaliseBase(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function shortHash(value, length = 12) {
  const text = String(value || "—");
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(date);
}

function humanAction(value) {
  return String(value || "action").replaceAll("_", " ");
}

function humanType(value) {
  return String(value || "asset").replaceAll("_", " ");
}

function riskColor(tier) {
  return riskColors[String(tier || "").toLowerCase()] || "#82909d";
}

function setBusy(button, busy, label) {
  if (!button) return;
  button.disabled = busy;
  button.classList.toggle("is-busy", busy);
  if (busy) {
    button.dataset.originalLabel = button.innerHTML;
    button.innerHTML = `<span class="loader"></span><span>${escapeHtml(label || "Working…")}</span>`;
  } else if (button.dataset.originalLabel) {
    button.innerHTML = button.dataset.originalLabel;
  }
}

function showToast(message, kind = "info") {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast show${kind === "error" ? " error" : ""}`;
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => { toast.className = "toast"; }, 4200);
}

async function fetchJson(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 14000);
  try {
    const response = await fetch(`${state.apiBase}${path}`, { ...options, signal: controller.signal });
    const text = await response.text();
    let payload = {};
    try { payload = text ? JSON.parse(text) : {}; } catch { payload = { detail: text }; }
    if (!response.ok) {
      const error = new Error(payload.detail || payload.error || `Request failed (${response.status})`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  } finally {
    window.clearTimeout(timeout);
  }
}

function updateConnection(stateName, label) {
  const pill = $("connectionPill");
  const dot = $("connectionDot");
  pill.dataset.state = stateName;
  dot.className = `status-dot ${stateName === "online" ? "mint" : stateName === "offline" ? "red" : ""}`;
  $("connectionLabel").textContent = label;
}

function updateRequestPreview() {
  const action = humanAction($("action").value);
  const entity = $("entity").value.trim() || "entity";
  const field = $("field").value.trim() || "field";
  const replacement = $("replacement").value.trim();
  const suffix = replacement ? ` → ${replacement}` : "";
  $("requestPreview").textContent = `${action}(${entity}.${field}${suffix})`;
}

async function checkHealth({ silent = false } = {}) {
  if (!state.apiBase) {
    updateConnection("offline", "API URL missing");
    return null;
  }
  try {
    const health = await fetchJson("/health");
    state.health = health;
    const mode = health.context_mode ? String(health.context_mode).toUpperCase() : "READY";
    updateConnection("online", `${mode} / API online`);
    $("contextStatus").textContent = `${mode} context ready`;
    $("writebackStatus").textContent = health.writeback_enabled ? "Enabled" : "Opt-in / off";
    $("modalStatus").className = "modal-status online";
    $("modalStatus").innerHTML = `<span class="status-dot mint"></span><span>Connected · ${escapeHtml(mode)} context</span>`;
    return health;
  } catch (error) {
    state.health = null;
    updateConnection("offline", error.name === "AbortError" ? "API timed out" : "API unreachable");
    $("contextStatus").textContent = "Awaiting API connection";
    $("modalStatus").className = "modal-status offline";
    $("modalStatus").innerHTML = `<span class="status-dot red"></span><span>${escapeHtml(error.message || "API unreachable")}</span>`;
    if (!silent) showToast(`Could not reach ${state.apiBase}`, "error");
    return null;
  }
}

function setResultState(label, stateName = "") {
  const resultState = $("resultState");
  resultState.className = `result-state ${stateName}`;
  resultState.innerHTML = `<span class="status-dot ${stateName === "ready" ? "mint" : stateName === "blocked" ? "red" : ""}"></span>${escapeHtml(label)}`;
}

function renderGraph(pact) {
  const context = pact.context || {};
  const downstream = Array.isArray(context.downstream) ? context.downstream : [];
  const visibleNodes = downstream.slice(0, 8);
  const extra = Math.max(0, downstream.length - visibleNodes.length);
  $("graphEmpty").hidden = true;
  $("graphContent").hidden = false;
  $("graphSourceLabel").textContent = context.source_name || "source asset";
  $("graphContextHash").textContent = `fingerprint ${shortHash(pact.context_hash, 16)}`;
  const mode = context.live ? "LIVE" : "DEMO";
  $("graphMode").textContent = mode;
  $("graphMode").classList.toggle("live", Boolean(context.live));

  const source = `<div class="graph-source-col"><div class="source-node"><div class="node-type"><i></i>source asset</div><strong>${escapeHtml(context.source_name || "Unnamed asset")}</strong><span class="node-owner">${escapeHtml((context.owners || ["owner unresolved"])[0])}</span></div></div>`;
  const nodes = visibleNodes.map((node) => {
    const signals = [...(node.tags || []), ...(node.glossary_terms || [])].map((item) => String(item).toLowerCase());
    const sensitive = signals.some((item) => ["pii", "sensitive", "restricted"].some((flag) => item.includes(flag)));
    return `<div class="downstream-node${sensitive ? " sensitive" : ""}"><div class="node-type"><i></i></div><div><strong>${escapeHtml(node.name || "Unnamed downstream")}</strong><span class="node-owner">${escapeHtml(node.owner || node.domain || humanType(node.type))}</span></div><span class="node-depth">D${escapeHtml(node.depth ?? 0)}</span></div>`;
  }).join("");
  const extraNode = extra ? `<div class="downstream-node"><div class="node-type"><i></i></div><div><strong>+${extra} more dependencies</strong><span class="node-owner">full graph bound in Pact</span></div><span class="node-depth">…</span></div>` : "";
  $("graphCanvas").innerHTML = `${source}<div class="graph-downstream-col">${nodes || `<div class="muted-line">No downstream nodes returned.</div>`}${extraNode}</div>`;

  const domainCount = (context.domains || []).length;
  const ownerCount = (context.owners || []).length;
  const usage = context.query_count == null ? "—" : context.query_count;
  $("graphSummary").innerHTML = [
    `<span class="summary-chip"><b>${downstream.length}</b> downstream assets</span>`,
    `<span class="summary-chip"><b>${domainCount}</b> domains</span>`,
    `<span class="summary-chip"><b>${ownerCount}</b> owners</span>`,
    `<span class="summary-chip"><b>${escapeHtml(usage)}</b> query uses</span>`,
    `<span class="summary-chip"><b>${context.retrieval_complete ? "complete" : "incomplete"}</b> retrieval</span>`,
  ].join("");
}

function renderRisk(pact) {
  const risk = pact.risk || {};
  const score = Number(risk.score || 0);
  const color = riskColor(risk.tier);
  const ring = $("riskDisplay").querySelector(".risk-ring");
  ring.style.background = `conic-gradient(${color} ${score * 3.6}deg, #26313b ${score * 3.6}deg)`;
  ring.querySelector("span").textContent = score;
  ring.querySelector("small").textContent = "/100";
  const label = $("riskDisplay").querySelector(".risk-label");
  label.textContent = `${String(risk.tier || "unknown").toUpperCase()} consequence`;
  label.style.color = color;
  $("riskDisplay").querySelector("p").textContent = score >= 45
    ? "The current graph grants only constrained authority. Review the reasons before approving a side effect."
    : "The current graph is relatively contained, but the Pact still narrows the executor’s scope.";
  $("riskReasons").innerHTML = (risk.reasons || []).length
    ? risk.reasons.map((reason) => `<div class="reason-row">${escapeHtml(humanAction(reason))}</div>`).join("")
    : `<div class="muted-line">No elevated consequence signals.</div>`;

  const context = pact.context || {};
  const firstOwner = (context.owners || ["unresolved"])[0];
  const firstDomain = (context.domains || ["unassigned"])[0];
  const assertionCount = Object.keys(context.assertion_statuses || {}).length || (context.assertions || []).length;
  $("contextFacts").innerHTML = [
    ["source", context.source_name || "—"],
    ["owner", firstOwner],
    ["domain", firstDomain],
    ["assertions", assertionCount],
    ["tags", (context.tags || []).length],
    ["retrieval", context.retrieval_complete ? "complete" : "incomplete"],
  ].map(([label, value]) => `<div class="fact"><span>${escapeHtml(label)}</span><b title="${escapeHtml(value)}">${escapeHtml(value)}</b></div>`).join("");
}

function renderPact(pact) {
  const signature = pact.signature ? "issued / signed" : "unsigned";
  $("pactId").textContent = pact.pact_id || "igp_—";
  $("pactPolicy").textContent = pact.policy_version || "—";
  $("pactExpiry").textContent = formatDate(pact.expires_at);
  $("pactFingerprint").textContent = pact.context_hash || "—";
  $("pactSeal").textContent = signature;
  $("pactSeal").parentElement.classList.toggle("issued", Boolean(pact.signature));
  $("allowedCount").textContent = (pact.allowed_actions || []).length;
  $("blockedCount").textContent = (pact.blocked_actions || []).length;
  $("allowedActions").innerHTML = (pact.allowed_actions || []).map((item) => `<span class="authority-action">${escapeHtml(humanAction(item))}</span>`).join("") || `<span class="muted-line">None</span>`;
  $("blockedActions").innerHTML = (pact.blocked_actions || []).map((item) => `<span class="authority-action">${escapeHtml(humanAction(item))}</span>`).join("") || `<span class="muted-line">None</span>`;
  const approval = pact.requires_human_approval || [];
  $("approvalBanner").hidden = approval.length === 0;
  if (approval.length) $("approvalText").textContent = `Approval is required for: ${approval.map(humanAction).join(", ")}. The executor remains outside the boundary until a human explicitly approves.`;
  const scope = pact.execution_scope?.deploy_staging;
  const artifact = scope?.artifact_hashes?.[0] || pact.artifact_hashes?.[0] || "";
  $("executionArtifact").textContent = artifact ? shortHash(artifact, 18) : "not authorized";
  $("executionArtifact").title = artifact;
  $("executionTarget").textContent = $("target").value;
  $("executeAction").disabled = !scope || !artifact;
  $("executionState").className = "execution-state";
  $("executionState").innerHTML = `<span class="status-dot blue"></span><span>${scope ? "Pact scope is armed. The attempt will be checked again at the boundary." : "This Pact does not authorize staging execution; review remains the only available path."}</span>`;
}

function renderGates(pact, receipt) {
  const context = pact.context || {};
  const rows = [...$("gateList").querySelectorAll(".gate-row")];
  const statuses = [
    ["pass", context.live ? "live snapshot" : "demo snapshot"],
    ["pass", `${String(pact.risk?.tier || "unknown")} / scored`],
    [pact.signature ? "pass" : "blocked", pact.signature ? "signed" : "unsigned"],
    [Object.keys(pact.execution_scope || {}).length ? "active" : "blocked", Object.keys(pact.execution_scope || {}).length ? "preflight armed" : "no scope"],
    [receipt ? (receipt.status === "blocked" || receipt.status === "context_unavailable" ? "blocked" : "pass") : "pending", receipt ? humanAction(receipt.status) : "waiting"],
  ];
  rows.forEach((row, index) => {
    const [className, label] = statuses[index];
    row.className = `gate-row ${className}`;
    row.querySelector(".gate-state").textContent = label;
  });
  const footer = $("gateList").parentElement.querySelector(".gate-footer");
  footer.innerHTML = `<span class="status-dot ${receipt?.status === "blocked" ? "red" : "amber"}"></span><span>${receipt?.status === "blocked" ? "Boundary held. No executor invocation implied." : "Analysis prepares authority; execution still requires the enforcement point."}</span>`;
}

function renderEvidence(receipt) {
  const artifacts = receipt?.generated_artifacts || [];
  $("artifactCount").textContent = `${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"}`;
  $("artifactsList").innerHTML = artifacts.length ? artifacts.map((artifact) => `<div class="artifact-row"><div class="artifact-icon">▤</div><div><strong>${escapeHtml(artifact.path)}</strong><small>${escapeHtml(humanType(artifact.kind))}</small></div><span class="artifact-hash">${escapeHtml(shortHash(artifact.sha256))}</span></div>`).join("") : `<div class="empty-evidence"><span class="empty-evidence-icon">▤</span><span>No generated artifacts returned.</span></div>`;

  const validations = receipt?.validations || [];
  $("validationList").innerHTML = validations.length ? validations.map((validation) => `<div class="validation-row"><span class="validation-status ${escapeHtml(validation.status)}">${escapeHtml(validation.status)}</span><div><strong>${escapeHtml(humanAction(validation.name))}</strong><p>${escapeHtml(validation.evidence)}</p></div></div>`).join("") : `<div class="empty-evidence"><span class="empty-evidence-icon">✓</span><span>No validations returned.</span></div>`;
  const writeback = receipt?.writeback;
  if (writeback) {
    const mode = String(writeback.mode || "skipped");
    const pill = $("writebackPill");
    pill.textContent = mode;
    pill.className = `mini-pill ${mode === "emitted" ? "emitted" : mode === "failed" ? "failed" : ""}`;
    $("writebackDetail").textContent = writeback.error || `${mode === "demo" ? "Demo write-back is represented but not emitted." : "No external write-back emitted."} Target: ${writeback.target_urn || "—"}`;
  }
}

function renderReceipt(receipt) {
  if (!receipt) return;
  const status = String(receipt.status || "ready_for_review");
  $("receiptId").textContent = receipt.receipt_id || "receipt pending";
  const summary = $("receiptSummary");
  const blocked = ["blocked", "context_unavailable", "failed"].includes(status);
  summary.className = `receipt-summary ${blocked ? "blocked" : "ready"}`;
  summary.innerHTML = `<span class="status-dot"></span><strong>${escapeHtml(humanAction(status))}</strong><span>${receipt.attempted_actions?.length || 0} decision${receipt.attempted_actions?.length === 1 ? "" : "s"} recorded · executor evidence is explicit</span>`;
  $("receiptJson").textContent = JSON.stringify(receipt, null, 2);
}

function renderExecution(response) {
  const event = response.event || {};
  const receipt = response.receipt || {};
  if (state.analysis) state.analysis.receipt = receipt;
  renderGates(state.analysis?.pact || {}, receipt);
  renderEvidence(receipt);
  renderReceipt(receipt);
  const executed = event.status === "executed" && event.executor_invoked;
  const blocked = !executed;
  const stateElement = $("executionState");
  stateElement.className = `execution-state ${executed ? "pass" : blocked ? "blocked" : ""}`;
  stateElement.innerHTML = `<span class="status-dot ${executed ? "mint" : "red"}"></span><span><strong>${escapeHtml(humanAction(event.status || "denied"))}</strong> · ${escapeHtml(event.detail || event.decision?.reason || "No executor evidence returned.")}</span>`;
  setResultState(executed ? "executor invoked · receipt recorded" : `${String(event.status || "denied").toUpperCase()} · boundary held`, executed ? "ready" : "blocked");
  showToast(executed ? "Staging simulator invoked once. The receipt is now the source of proof." : "The enforcement point held the boundary; no executor invocation was recorded.", executed ? "info" : "error");
}

function renderAnalysis(data) {
  state.analysis = data;
  const pact = data.pact || {};
  const receipt = data.receipt || {};
  const context = pact.context || {};
  $("contextStatus").textContent = `${context.live ? "LIVE" : "DEMO"} · ${context.source_name || "context snapshot"}`;
  $("writebackStatus").textContent = receipt.writeback?.mode === "emitted" ? "Emitted" : "Opt-in / off";
  setResultState(`${String(pact.risk?.tier || "unknown").toUpperCase()} · Pact issued`, "ready");
  renderGraph(pact);
  renderRisk(pact);
  renderPact(pact);
  renderGates(pact, receipt);
  renderEvidence(receipt);
  renderReceipt(receipt);
  $("copyFingerprint").disabled = !pact.context_hash;
  showToast(`Impact Pact ${shortHash(pact.pact_id, 19)} issued for review.`);
  document.querySelector("#impact-graph").scrollIntoView({ behavior: "smooth", block: "start" });
}

function showGraphError(title, detail) {
  $("graphContent").hidden = true;
  $("graphEmpty").hidden = false;
  $("graphEmpty").innerHTML = `<div class="empty-glyph"><span></span><span></span><span></span></div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p><div class="empty-hint"><span class="status-dot red"></span><span>Control plane remains fail-closed</span></div>`;
  setResultState(title, "blocked");
}

async function runAnalysis() {
  const button = $("changeForm").querySelector(".form-submit");
  const payload = {
    action: $("action").value,
    entity: $("entity").value.trim(),
    field: $("field").value.trim() || null,
    replacement: $("replacement").value.trim() || null,
  };
  if (!payload.entity) {
    showToast("An entity is required before a Pact can be compiled.", "error");
    $("entity").focus();
    return;
  }
  setBusy(button, true, "Reading context…");
  try {
    const data = await fetchJson("/v1/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    renderAnalysis(data);
  } catch (error) {
    const detail = error.payload?.error === "context_unavailable" ? "Live context was unavailable. iGraph refused to turn the failure into a demo success." : error.name === "AbortError" ? "The control plane timed out before returning a Pact." : `Could not reach the control plane at ${state.apiBase}.`;
    showGraphError("No Pact issued", detail);
    showToast(detail, "error");
  } finally {
    setBusy(button, false);
  }
}

async function executeAction() {
  const pact = state.analysis?.pact;
  const button = $("executeAction");
  const artifact = pact?.execution_scope?.deploy_staging?.artifact_hashes?.[0] || pact?.artifact_hashes?.[0];
  if (!pact || !artifact) {
    showToast("Compile a Pact with staging scope before testing the boundary.", "error");
    return;
  }
  const parameters = { target: $("target").value, artifact_sha256: artifact };
  setBusy(button, true, "Checking boundary…");
  try {
    const response = await fetchJson("/v1/actions/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pact, action: "deploy_staging", parameters, human_approved: $("humanApproved").checked }),
    });
    renderExecution(response);
  } catch (error) {
    $("executionState").className = "execution-state blocked";
    $("executionState").innerHTML = `<span class="status-dot red"></span><span>${escapeHtml(error.message || "The enforcement point could not be reached.")}</span>`;
    showToast(`Execution check failed: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

function renderDiscovery(data) {
  const panel = $("discoveryPanel");
  panel.hidden = false;
  panel.querySelector(".eyebrow").textContent = `DataHub discovery · ${data.live ? "live" : "demo"}`;
  panel.querySelector("h3").textContent = "Assets with the most consequence";
  const candidates = data.candidates || [];
  $("discoveryList").innerHTML = candidates.length ? candidates.slice(0, 9).map((candidate) => `<div class="discovery-item"><strong>${escapeHtml(candidate.name)}</strong><small>${escapeHtml(shortHash(candidate.urn, 35))}</small><div class="discovery-metrics"><span><b>${candidate.downstream_count}</b> downstream</span><span><b>${candidate.risk_score}</b> risk</span></div></div>`).join("") : `<div class="empty-evidence"><span class="empty-evidence-icon">◈</span><span>No candidate assets returned.</span></div>`;
  panel.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function discoverAssets() {
  const button = $("discoverAssets");
  setBusy(button, true, "Scanning…");
  try {
    renderDiscovery(await fetchJson("/v1/discover"));
  } catch (error) {
    showToast(`Discovery failed: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

function renderDrift(data) {
  const panel = $("discoveryPanel");
  panel.hidden = false;
  panel.querySelector(".eyebrow").textContent = "Authority drift experiment · deterministic proof";
  panel.querySelector("h3").textContent = "Same request. Different authority.";
  const before = data.before || {};
  const after = data.after || {};
  const beforeDecision = data.before_decision || {};
  const afterDecision = data.after_decision || {};
  $("discoveryList").innerHTML = `<div class="drift-claim"><span class="status-dot mint"></span><strong>${escapeHtml(data.claim || "Context changes authority while the request remains constant.")}</strong><small>tested action · ${escapeHtml(humanAction(data.tested_action))}</small></div><div class="drift-card"><div class="drift-card-header"><span>isolated context</span><b class="decision-good">${escapeHtml(beforeDecision.decision || "allow")}</b></div><strong>${escapeHtml(before.context?.source_name || "before")}</strong><p>${escapeHtml(before.risk?.tier || "low")} risk · ${before.context?.downstream?.length || 0} downstream assets</p><code>${escapeHtml(shortHash(before.context_hash, 16))}</code></div><div class="drift-arrow">→</div><div class="drift-card drift-card-after"><div class="drift-card-header"><span>governed context</span><b class="decision-bad">${escapeHtml(afterDecision.decision || "require approval")}</b></div><strong>${escapeHtml(after.context?.source_name || "after")}</strong><p>${escapeHtml(after.risk?.tier || "high")} risk · ${after.context?.downstream?.length || 0} downstream assets</p><code>${escapeHtml(shortHash(after.context_hash, 16))}</code></div>`;
  panel.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function runDrift() {
  const button = $("runDrift");
  setBusy(button, true, "Comparing contexts…");
  try {
    renderDrift(await fetchJson("/v1/experiments/authority-drift"));
    showToast("Authority drift proof loaded: same request, different Pact.");
  } catch (error) {
    showToast(`Authority drift failed: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

async function copyText(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(successMessage);
  } catch {
    showToast("Clipboard access was unavailable.", "error");
  }
}

function openSettings() {
  $("apiUrl").value = state.apiBase;
  $("apiModal").hidden = false;
  window.setTimeout(() => $("apiUrl").focus(), 40);
}

function closeSettings() { $("apiModal").hidden = true; }

async function saveSettings() {
  const value = normaliseBase($("apiUrl").value);
  if (!value) {
    showToast("Enter an API base URL first.", "error");
    return;
  }
  state.apiBase = value;
  localStorage.setItem("igraph_api", value);
  await checkHealth();
  closeSettings();
}

function resetDiscoveryTitle() {
  const panel = $("discoveryPanel");
  panel.querySelector(".eyebrow").textContent = "DataHub discovery";
  panel.querySelector("h3").textContent = "Assets with the most consequence";
}

document.addEventListener("DOMContentLoaded", () => {
  $("apiUrl").value = state.apiBase;
  $("changeForm").addEventListener("submit", (event) => { event.preventDefault(); runAnalysis(); });
  ["entity", "action", "field", "replacement"].forEach((id) => $(id).addEventListener("input", updateRequestPreview));
  $("target").addEventListener("change", () => { $("executionTarget").textContent = $("target").value; });
  $("runSample").addEventListener("click", () => { $("changeForm").scrollIntoView({ behavior: "smooth", block: "center" }); window.setTimeout(runAnalysis, 220); });
  $("runDrift").addEventListener("click", runDrift);
  $("discoverAssets").addEventListener("click", discoverAssets);
  $("executeAction").addEventListener("click", executeAction);
  $("closeDiscovery").addEventListener("click", () => { $("discoveryPanel").hidden = true; resetDiscoveryTitle(); });
  $("refreshHealth").addEventListener("click", () => checkHealth());
  $("openApiSettings").addEventListener("click", openSettings);
  $("closeApiSettings").addEventListener("click", closeSettings);
  $("cancelApiSettings").addEventListener("click", closeSettings);
  $("saveApiSettings").addEventListener("click", saveSettings);
  $("apiModal").addEventListener("click", (event) => { if (event.target === $("apiModal")) closeSettings(); });
  $("copyFingerprint").addEventListener("click", () => copyText(state.analysis?.pact?.context_hash || "", "Context fingerprint copied."));
  $("copyReceipt").addEventListener("click", () => copyText($("receiptJson").textContent, "Receipt JSON copied."));
  updateRequestPreview();
  checkHealth({ silent: true });
});
