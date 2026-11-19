/**
 * main.js
 * Virgin-session application controller for Decision-Grounded LLM Router Studio.
 * Starts every new session completely clean:
 *   - No predefined router scenarios or presets
 *   - No pre-filled inputs or sample prompt pills
 *   - 3 focused tabs:
 *       1. Router Architect Agent
 *       2. Step-by-Step Pipeline Trace
 *       3. Topics, Weights & Thresholds
 */

import { renderPipelineTrace } from "./components/PipelineVisualizer.js";
import {
  renderSkillsBar,
  appendChatMessage,
  renderActiveBlueprint,
} from "./components/ArchitectChat.js";
import { renderWorkbench } from "./components/TopicWeightStudio.js";

const ALL_TABS = ["architect", "pipeline", "workbench"];

const state = {
  status: null,
  skills: [],
  activeSpec: null,
  lastTrace: null,
  conversationHistory: [],
  activeTab: "architect",
};

async function apiFetch(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

function updateHeaderStatus() {
  const dot = document.getElementById("api-status-dot");
  const label = document.getElementById("api-status-label");
  if (state.status?.live_api_available) {
    dot.classList.add("live");
    label.textContent = `Live API (${state.status.masked_api_key || "Active"})`;
  } else {
    dot.classList.remove("live");
    label.textContent = "Simulation Mode · Set API Key";
  }

  const stats = state.status?.stats || {};
  document.getElementById("stat-routed").textContent = String(stats.total_routed ?? 0);
  document.getElementById("stat-savings").textContent =
    stats.total_routed > 0 ? `${stats.savings_pct.toFixed(1)}%` : "—";

  const execMode = state.activeSpec?.execution_mode || "staged";
  document
    .getElementById("mode-staged-btn")
    .classList.toggle("active", execMode === "staged");
  document
    .getElementById("mode-batched-btn")
    .classList.toggle("active", execMode === "batched");

  const routeBtn = document.getElementById("run-route-btn");
  if (routeBtn) {
    routeBtn.disabled = !state.activeSpec;
    routeBtn.title = state.activeSpec
      ? "Evaluate prompt across your custom Decision-grounded router"
      : "Configure your custom router in Tab 1 first";
  }
}

async function refreshStatus() {
  state.status = await apiFetch("/api/status");
  updateHeaderStatus();
}

function syncBlueprintPanel() {
  renderActiveBlueprint(
    document.getElementById("architect-blueprint-root"),
    state.activeSpec,
    state.lastTrace,
    () => switchTab("pipeline"),
    () => switchTab("workbench")
  );
}

async function executeRoute() {
  const promptInput = document.getElementById("route-prompt-input");
  const prompt = promptInput.value.trim();
  if (!state.activeSpec) {
    switchTab("architect");
    return;
  }
  if (!prompt) {
    promptInput.focus();
    return;
  }

  const btn = document.getElementById("run-route-btn");
  btn.disabled = true;
  btn.textContent = "Scoring Decisions...";

  try {
    renderSkillsBar(document.getElementById("skills-bar"), state.skills, [
      "decision-weighted-routing",
    ]);
    state.lastTrace = await apiFetch("/api/route", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        router_spec: state.activeSpec,
      }),
    });
    renderPipelineTrace(
      document.getElementById("pipeline-trace-root"),
      state.lastTrace,
      state.activeSpec,
      () => switchTab("architect")
    );
    syncBlueprintPanel();
    await refreshStatus();
  } catch (err) {
    alert(`Routing error: ${err.message}`);
  } finally {
    btn.disabled = !state.activeSpec;
    btn.textContent = "Evaluate & Route";
  }
}

async function handleLiveWeightRecompute(updatedSpec) {
  state.activeSpec = updatedSpec;
  await apiFetch("/api/config", {
    method: "POST",
    body: JSON.stringify(state.activeSpec),
  });
  syncBlueprintPanel();
  if (!state.lastTrace) return;

  const hardGateAnswers = {};
  const topicAnswers = {};
  for (const call of state.lastTrace.decision_calls || []) {
    if (call.stage_name.includes("Quality Gate")) continue;
    const answers = call.response_payload?.answers || {};
    for (const g of updatedSpec.hard_gates) {
      if (answers[g.key]) hardGateAnswers[g.key] = answers[g.key];
    }
    for (const t of updatedSpec.topics) {
      if (answers[t.key]) topicAnswers[t.key] = answers[t.key];
    }
  }

  try {
    const recomputed = await apiFetch("/api/recompute-score", {
      method: "POST",
      body: JSON.stringify({
        router_spec: updatedSpec,
        hard_gate_answers: hardGateAnswers,
        topic_answers: topicAnswers,
      }),
    });
    state.lastTrace.hard_gate_evaluations = recomputed.hard_gate_evaluations;
    state.lastTrace.topic_scores = recomputed.topic_scores;
    state.lastTrace.resolution = recomputed.resolution;
    state.lastTrace.final_model_id = recomputed.resolution.selected_model_id;
    state.lastTrace.final_model_name = recomputed.resolution.selected_model_name;
    state.lastTrace.final_tier = recomputed.resolution.resolved_tier;

    renderPipelineTrace(
      document.getElementById("pipeline-trace-root"),
      state.lastTrace,
      state.activeSpec,
      () => switchTab("architect")
    );
    syncBlueprintPanel();
  } catch {
    // Ignore transient validation while dragging
  }
}

function renderAllPanels() {
  syncBlueprintPanel();
  renderPipelineTrace(
    document.getElementById("pipeline-trace-root"),
    state.lastTrace,
    state.activeSpec,
    () => switchTab("architect")
  );
  renderWorkbench(
    document.getElementById("workbench-root"),
    state.activeSpec,
    handleLiveWeightRecompute,
    async () => {
      switchTab("pipeline");
      if (document.getElementById("route-prompt-input").value.trim()) {
        await executeRoute();
      }
    },
    () => switchTab("architect")
  );
}

function switchTab(tabName) {
  if (!ALL_TABS.includes(tabName)) return;
  state.activeTab = tabName;

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    const active = btn.dataset.tab === tabName;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", String(active));
  });

  ALL_TABS.forEach((name) => {
    const panel = document.getElementById(`tab-panel-${name}`);
    if (!panel) return;
    const active = name === tabName;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });

  renderAllPanels();
}

async function applyProposedSpec(newSpec) {
  state.activeSpec = structuredClone(newSpec);
  await apiFetch("/api/config", {
    method: "POST",
    body: JSON.stringify(state.activeSpec),
  });
  updateHeaderStatus();
  renderAllPanels();
  if (document.getElementById("route-prompt-input").value.trim()) {
    await executeRoute();
  }
}

async function sendArchitectTurn(text) {
  const stream = document.getElementById("architect-chat-stream");
  const sendBtn = document.getElementById("architect-send-btn");
  appendChatMessage(stream, "user", text);
  state.conversationHistory.push({ role: "user", content: text });

  sendBtn.disabled = true;
  sendBtn.textContent = "Working...";

  try {
    const resp = await apiFetch("/api/architect/chat", {
      method: "POST",
      body: JSON.stringify({
        message: text,
        current_spec: state.activeSpec,
        conversation_history: state.conversationHistory,
        last_route_result: state.lastTrace,
      }),
    });

    state.conversationHistory.push({
      role: "assistant",
      content: resp.reply_markdown,
    });

    renderSkillsBar(
      document.getElementById("skills-bar"),
      state.skills,
      resp.active_skills
    );

    appendChatMessage(stream, "agent", resp, applyProposedSpec);
  } catch (err) {
    appendChatMessage(stream, "agent", {
      reply_markdown: `**Error**: ${err.message}`,
      changes: [],
    });
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send to Architect";
  }
}

function seedVirginWelcome() {
  const stream = document.getElementById("architect-chat-stream");
  stream.innerHTML = "";
  appendChatMessage(stream, "agent", {
    reply_markdown:
      "### New Blank Router Session\n\n" +
      "No topics, thresholds, or scenarios are preloaded. Describe the tasks you want to route, the topics and probability thresholds that matter to you, or click **Interview Me** to build your custom `gemini-decision-1` router step by step.",
    changes: [],
  });
}

async function startVirginSession() {
  state.activeSpec = null;
  state.lastTrace = null;
  state.conversationHistory = [];
  document.getElementById("route-prompt-input").value = "";
  document.getElementById("architect-input").value = "";

  state.status = await apiFetch("/api/session/reset", { method: "POST" });
  updateHeaderStatus();
  seedVirginWelcome();
  renderSkillsBar(document.getElementById("skills-bar"), state.skills, [
    "topic-threshold-discovery",
  ]);
  switchTab("architect");
}

function wireEvents() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.getElementById("run-route-btn").addEventListener("click", executeRoute);

  document
    .getElementById("reset-session-btn")
    .addEventListener("click", startVirginSession);

  ["mode-staged-btn", "mode-batched-btn"].forEach((id) => {
    document.getElementById(id).addEventListener("click", async (e) => {
      const chosenMode = e.currentTarget.dataset.execMode;
      document
        .getElementById("mode-staged-btn")
        .classList.toggle("active", chosenMode === "staged");
      document
        .getElementById("mode-batched-btn")
        .classList.toggle("active", chosenMode === "batched");

      if (!state.activeSpec) return;
      state.activeSpec.execution_mode = chosenMode;
      await apiFetch("/api/config", {
        method: "POST",
        body: JSON.stringify(state.activeSpec),
      });
      if (document.getElementById("route-prompt-input").value.trim()) {
        await executeRoute();
      }
      renderAllPanels();
    });
  });

  document.getElementById("architect-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("architect-input");
    const val = input.value.trim();
    if (!val) return;
    input.value = "";
    await sendArchitectTurn(val);
  });

  document.getElementById("discover-btn").addEventListener("click", () => {
    sendArchitectTurn("Interview me to discover my routing topics and thresholds.");
  });

  // API Key Modal
  const modal = document.getElementById("api-key-modal");
  document.getElementById("api-key-btn").addEventListener("click", () => {
    modal.hidden = false;
  });
  document.getElementById("modal-close-btn").addEventListener("click", () => {
    modal.hidden = true;
  });
  document.getElementById("api-key-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const keyVal = document.getElementById("api-key-input").value.trim();
    if (keyVal) {
      sessionStorage.setItem("router_studio_gemini_key", keyVal);
    }
    await apiFetch("/api/session/api-key", {
      method: "POST",
      body: JSON.stringify({ api_key: keyVal }),
    });
    document.getElementById("api-key-input").value = "";
    modal.hidden = true;
    await refreshStatus();
  });
  document.getElementById("clear-api-key-btn").addEventListener("click", async () => {
    sessionStorage.removeItem("router_studio_gemini_key");
    await apiFetch("/api/session/api-key", {
      method: "POST",
      body: JSON.stringify({ api_key: "" }),
    });
    modal.hidden = true;
    await refreshStatus();
  });
}

async function boot() {
  wireEvents();
  // Sync any sessionStorage API key across server reloads automatically
  const cachedKey = sessionStorage.getItem("router_studio_gemini_key");
  if (cachedKey) {
    await apiFetch("/api/session/api-key", {
      method: "POST",
      body: JSON.stringify({ api_key: cachedKey }),
    }).catch(() => {});
  }

  const skillsData = await apiFetch("/api/skills");
  state.skills = skillsData.skills || [];
  await startVirginSession();
}

boot();
