/**
 * ArchitectChat.js
 * Clear, human-readable presentation of how plain-text user rules translate into:
 *   1. Input Shortcut / Guardrail Rules (Yes/No probability checks)
 *   2. Weighted Scoring Topics (0-3 rubrics or Yes/No risks)
 *   3. Score-to-Model Tier Mapping (0%-100% bands)
 *   4. Post-Answer Checks & Auto-Escalation (+1 tier on draft check)
 */

import { escapeHtml, renderMarkdown } from "../utils/markdown.js";

function humanizeArrows(str) {
  return String(str ?? "")
    .replaceAll("$\\rightarrow$", "→")
    .replaceAll("->", "→")
    .replaceAll(">=", "≥")
    .replaceAll("<=", "≤");
}

export function renderSkillsBar(container, allSkills, activeSkillNames = []) {
  const activeSet = new Set(activeSkillNames);
  container.innerHTML = (allSkills || [])
    .map((s) => {
      const isAct = activeSet.has(s.name);
      return `<span class="skill-chip ${isAct ? "active" : ""}" title="${escapeHtml(s.description)}">${escapeHtml(s.name)}</span>`;
    })
    .join("");
}

export function appendChatMessage(streamEl, role, payload, onApplySpec) {
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;

  if (role === "user") {
    div.textContent = payload;
  } else {
    div.classList.add("markdown-body");
    let inner = renderMarkdown(humanizeArrows(payload.reply_markdown));
    const steps = payload.translation_steps || [];

    if (payload.proposed_spec && steps.length > 0) {
      inner += `
        <div class="diff-card">
          <div class="diff-card-header">
            <span>Step-by-Step Translation Plan (${steps.length} Building Blocks)</span>
            <span class="pill-badge emerald">Ready to Activate</span>
          </div>
          ${steps
            .map(
              (st) => `
              <div class="translation-step-card">
                <div class="translation-step-top">
                  <span class="translation-step-title">${escapeHtml(humanizeArrows(st.title))}</span>
                  <span class="pill-badge teal">${escapeHtml(st.phase)}</span>
                </div>
                <div class="translation-kv">
                  <div class="translation-k">Your Requirement</div>
                  <div class="translation-v">${escapeHtml(humanizeArrows(st.from_your_text))}</div>

                  <div class="translation-k">Decision API Call</div>
                  <div class="translation-v">
                    <strong>${escapeHtml(st.decision_api_check)}</strong><br/>
                    <em>"${escapeHtml(st.api_question)}"</em>
                  </div>

                  <div class="translation-k">How It Routes</div>
                  <div class="translation-v rule-highlight">${escapeHtml(humanizeArrows(st.routing_rule))}</div>
                </div>
              </div>
            `
            )
            .join("")}
          <button type="button" class="primary-btn diff-apply-btn">
            Activate This Router &rarr;
          </button>
        </div>
      `;
    }

    div.innerHTML = inner;

    const applyBtn = div.querySelector(".diff-apply-btn");
    if (applyBtn && payload.proposed_spec) {
      applyBtn.addEventListener("click", () => {
        onApplySpec(payload.proposed_spec);
        applyBtn.textContent = "Router Active — Ready to Test in Tab 2 ✓";
        applyBtn.disabled = true;
      });
    }
  }

  streamEl.appendChild(div);
  streamEl.scrollTop = streamEl.scrollHeight;
}

function modelLabelForTier(spec, tier) {
  const m = (spec.models || []).find((x) => x.tier === tier);
  return m ? `${m.display_name} (${m.model_id})` : tier;
}

export function renderActiveBlueprint(
  container,
  spec,
  lastTrace,
  onGoPipeline,
  onTuneTabClick
) {
  if (!container) return;

  if (!spec) {
    container.innerHTML = `
      <div>
        <div class="section-eyebrow">Active Router Blueprint</div>
        <h3 style="margin:4px 0 6px;font-size:15px;font-weight:700;">No Router Configured Yet</h3>
        <p class="blueprint-item-sub" style="margin:0;">
          Write your routing rules in plain English on the left. The Architect will translate each sentence into explicit <code>gemini-decision-1</code> questions and show you the exact <strong>IF / THEN</strong> and <strong>Weighted Score</strong> logic before you activate it.
        </p>
      </div>
      <div class="blueprint-group">
        <div class="section-eyebrow" style="margin-bottom:6px;">Available Candidate Models (Lowest Cost &rarr; Highest Capability)</div>
        <div class="blueprint-item">
          <span><strong>1. Gemini 3.5 Flash-Lite</strong></span>
          <span class="mono">$0.30 / $2.50</span>
        </div>
        <div class="blueprint-item">
          <span><strong>2. Gemini 4 Hydrogen</strong></span>
          <span class="mono">$1.50 / $7.50</span>
        </div>
        <div class="blueprint-item">
          <span><strong>3. Gemini 4 Neon</strong></span>
          <span class="mono">$3.00 / $15.00</span>
        </div>
        <div class="blueprint-item">
          <span><strong>4. Gemini 4 Carbon</strong></span>
          <span class="mono">$4.00 / $20.00</span>
        </div>
      </div>
    `;
    return;
  }

  const enabledGates = (spec.hard_gates || []).filter((g) => g.enabled);
  const enabledTopics = (spec.topics || []).filter((t) => t.enabled && t.weight > 0);
  const enabledPost = (spec.quality_gate?.custom_checks || []).filter((p) => p.enabled);
  const totalWeight = enabledTopics.reduce((s, t) => s + t.weight, 0) || 1;
  const cut = spec.tier_cutoffs;
  const sPct = Math.round(cut.standard * 100);
  const cPct = Math.round(cut.complex * 100);
  const ePct = Math.round(cut.expert * 100);

  container.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
      <div>
        <div class="section-eyebrow">Active Router Execution Plan</div>
        <h3 style="margin:3px 0 0;font-size:15px;font-weight:700;">${escapeHtml(spec.name)}</h3>
      </div>
      <span class="pill-badge emerald">Active</span>
    </div>
    <p class="blueprint-item-sub" style="margin:6px 0 0;">
      ${escapeHtml(spec.description)}
    </p>

    <div class="blueprint-group">
      <div class="section-eyebrow" style="margin-bottom:6px;">Step 1 · Input Shortcut &amp; Guardrail Rules (${enabledGates.length})</div>
      ${
        enabledGates.length
          ? enabledGates
              .map((g) => {
                const pct = Math.round(g.threshold * 100);
                let actionText = `Require at least ${modelLabelForTier(spec, g.min_tier)}`;
                if (g.action === "route_to_tier") {
                  actionText = `Route directly to ${modelLabelForTier(spec, g.min_tier)}`;
                } else if (g.action === "bump_one_tier") {
                  actionText = `Escalate +1 higher tier`;
                }
                return `
                  <div style="margin-bottom:8px;">
                    <div style="font-size:12.5px;font-weight:600;">${escapeHtml(g.label)}</div>
                    <div class="blueprint-item-sub"><em>"${escapeHtml(g.instructions)}"</em></div>
                    <div class="mono" style="font-size:11.5px;color:var(--signal-cobalt);margin-top:2px;">
                      IF Yes &ge; ${pct}% &rarr; ${escapeHtml(actionText)}
                    </div>
                  </div>
                `;
              })
              .join("")
          : `<div class="blueprint-item-sub">None — goes straight to Step 2 weighted topic scoring.</div>`
      }
    </div>

    <div class="blueprint-group">
      <div class="section-eyebrow" style="margin-bottom:6px;">Step 2 · Weighted Topic Score (${enabledTopics.length})</div>
      ${enabledTopics
        .map((t) => {
          const share = Math.round((t.weight / totalWeight) * 100);
          return `
            <div style="margin-bottom:7px;">
              <div class="blueprint-item" style="padding:0;">
                <span><strong>${escapeHtml(t.label)}</strong></span>
                <span class="pill-badge">${share}% weight</span>
              </div>
              <div class="blueprint-item-sub"><em>"${escapeHtml(t.instructions)}"</em></div>
            </div>
          `;
        })
        .join("")}
      <div style="margin-top:8px;padding:8px 10px;background:var(--bg-subtle);border-radius:6px;font-size:11.5px;" class="mono">
        <div>0%–${sPct - 1}% &rarr; ${escapeHtml(modelLabelForTier(spec, "SIMPLE"))}</div>
        <div>${sPct}%–${cPct - 1}% &rarr; ${escapeHtml(modelLabelForTier(spec, "STANDARD"))}</div>
        <div>${cPct}%–${ePct - 1}% &rarr; ${escapeHtml(modelLabelForTier(spec, "COMPLEX"))}</div>
        <div>${ePct}%–100% &rarr; ${escapeHtml(modelLabelForTier(spec, "EXPERT"))}</div>
      </div>
    </div>

    <div class="blueprint-group">
      <div class="section-eyebrow" style="margin-bottom:6px;">Step 3 · Post-Answer Escalation Checks (${enabledPost.length})</div>
      ${
        enabledPost.length
          ? enabledPost
              .map(
                (pc) => `
                <div style="margin-bottom:6px;">
                  <div style="font-size:12.5px;font-weight:600;">${escapeHtml(pc.label)}</div>
                  <div class="blueprint-item-sub"><em>"${escapeHtml(pc.instructions)}"</em></div>
                  <div class="mono" style="font-size:11.5px;color:var(--signal-amber);margin-top:2px;">
                    IF Yes &ge; ${Math.round(pc.threshold * 100)}% &rarr; Re-run on next higher tier (+1)
                  </div>
                </div>
              `
              )
              .join("")
          : `<div class="blueprint-item-sub">Standard response quality check (&gt;${Math.round(spec.quality_gate.threshold * 100)}%).</div>`
      }
    </div>

    ${
      lastTrace
        ? `
        <div class="blueprint-group">
          <div class="section-eyebrow" style="margin-bottom:4px;">Latest Tested Prompt</div>
          <div class="blueprint-item">
            <span>Score = <strong>${(lastTrace.resolution.composite_score * 100).toFixed(1)}%</strong></span>
            <span class="pill-badge emerald">${escapeHtml(lastTrace.final_model_name)}</span>
          </div>
        </div>
      `
        : ""
    }

    <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap;">
      <button type="button" id="blueprint-pipeline-btn" class="primary-btn small-btn" style="flex:1;">
        Test Prompts in Tab 2 &rarr;
      </button>
      <button type="button" id="blueprint-tune-btn" class="ghost-btn small-btn" style="flex:1;">
        Adjust Sliders in Tab 3 &rarr;
      </button>
    </div>
  `;

  const pipeBtn = container.querySelector("#blueprint-pipeline-btn");
  if (pipeBtn && onGoPipeline) pipeBtn.addEventListener("click", onGoPipeline);

  const tuneBtn = container.querySelector("#blueprint-tune-btn");
  if (tuneBtn && onTuneTabClick) tuneBtn.addEventListener("click", onTuneTabClick);
}
