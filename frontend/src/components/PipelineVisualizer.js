/**
 * PipelineVisualizer.js
 * Clear, human-readable visual trace of how a prompt moves through:
 *   - Input Shortcut & Guardrail Rules (Yes/No checks)
 *   - Weighted Topic Scoring (0-3 scales -> 0%-100% Combined Score)
 *   - Candidate LLM Selection
 *   - Post-Answer Checks & +1 Tier Escalation
 */

import { escapeHtml, renderMarkdown } from "../utils/markdown.js";

function renderQuestionEvalBlock(key, qSpec, ans, gateEvalMap, topicLabelMap) {
  const qType = ans?.type || qSpec?.type || "noul";
  const confPct = Math.round((ans?.confidence ?? 0.8) * 100);
  const humanTitle =
    gateEvalMap.get(key)?.label || topicLabelMap.get(key) || key;
  const questionAsked = qSpec?.instructions || "";

  if (qType === "noul") {
    const noulVal = Number(ans?.noul ?? 0.5);
    const pct = Math.round(noulVal * 100);
    const gate = gateEvalMap.get(key);

    if (gate) {
      const threshPct = Math.round(gate.threshold * 100);
      return `
        <div class="q-eval-block">
          <div class="q-eval-head">
            <span class="q-eval-name">${escapeHtml(gate.label)}</span>
            <span class="q-eval-meta">
              Yes Probability = <strong>${pct}%</strong> (threshold ${threshPct}%) ·
              ${
                gate.triggered
                  ? `<span class="pill-badge amber">RULE MATCHED</span>`
                  : `<span class="pill-badge">Did not trigger</span>`
              }
            </span>
          </div>
          <div style="font-size:12px;color:var(--ink-secondary);margin-bottom:6px;">
            <em>Question: "${escapeHtml(questionAsked)}"</em><br/>
            <span class="mono" style="font-size:11px;">${escapeHtml(gate.effect_summary.replaceAll("->", "→").replaceAll(">=", "≥"))}</span>
          </div>
          <div class="prob-bar-track">
            <div class="prob-bar-fill ${gate.triggered ? "triggered" : ""}" style="width: ${pct}%"></div>
            <div class="threshold-tick" style="left: ${threshPct}%">
              <span class="threshold-tick-label">${threshPct}%</span>
            </div>
          </div>
        </div>
      `;
    }

    return `
      <div class="q-eval-block">
        <div class="q-eval-head">
          <span class="q-eval-name">${escapeHtml(humanTitle)}</span>
          <span class="q-eval-meta">Yes Probability = <strong>${pct}%</strong> · confidence ${confPct}%</span>
        </div>
        <div style="font-size:12px;color:var(--ink-secondary);margin-bottom:6px;">
          <em>Question: "${escapeHtml(questionAsked)}"</em>
        </div>
        <div class="prob-bar-track">
          <div class="prob-bar-fill" style="width: ${pct}%"></div>
        </div>
      </div>
    `;
  }

  if (qType === "choice") {
    const probs = ans?.probabilities || {};
    const topChoice = ans?.choice || "";
    const entries = Object.entries(probs).sort((a, b) => b[1] - a[1]);
    return `
      <div class="q-eval-block">
        <div class="q-eval-head">
          <span class="q-eval-name">${escapeHtml(humanTitle)}</span>
          <span class="q-eval-meta">Matched: <strong>${escapeHtml(topChoice)}</strong> (${confPct}% confidence)</span>
        </div>
        <div style="font-size:12px;color:var(--ink-secondary);margin-bottom:6px;">
          <em>Question: "${escapeHtml(questionAsked)}"</em>
        </div>
        <div class="dist-rows">
          ${entries
            .map(([opt, p]) => {
              const pPct = Math.round(p * 100);
              const isWin = opt === topChoice;
              return `
                <div class="dist-row">
                  <span class="dist-label ${isWin ? "winner" : ""}" title="${escapeHtml(opt)}">${escapeHtml(opt)}</span>
                  <div class="dist-mini-track">
                    <div class="dist-mini-fill" style="width: ${pPct}%"></div>
                  </div>
                  <span class="dist-pct">${(p * 100).toFixed(0)}%</span>
                </div>
              `;
            })
            .join("")}
        </div>
      </div>
    `;
  }

  // score rubric
  const probs = ans?.probabilities || {};
  const legend = ans?.legend || {};
  const scoreVal = Number(ans?.score ?? 0);
  const levels = Object.keys(probs).sort((a, b) => Number(a) - Number(b));
  const maxIdx = Math.max(1, levels.length - 1);
  const normPct = Math.round((scoreVal / maxIdx) * 100);

  return `
    <div class="q-eval-block">
      <div class="q-eval-head">
        <span class="q-eval-name">${escapeHtml(humanTitle)}</span>
        <span class="q-eval-meta">Score = <strong>${scoreVal.toFixed(2)} / ${maxIdx}</strong> (${normPct}%) · confidence ${confPct}%</span>
      </div>
      <div style="font-size:12px;color:var(--ink-secondary);margin-bottom:6px;">
        <em>Question: "${escapeHtml(questionAsked)}"</em>
      </div>
      <div class="dist-rows">
        ${levels
          .map((lvl) => {
            const p = Number(probs[lvl] || 0);
            const desc = legend[lvl] || `Level ${lvl}`;
            return `
              <div class="dist-row">
                <span class="dist-label" title="${escapeHtml(desc)}">${lvl}: ${escapeHtml(desc)}</span>
                <div class="dist-mini-track">
                  <div class="dist-mini-fill" style="width: ${Math.round(p * 100)}%"></div>
                </div>
                <span class="dist-pct">${(p * 100).toFixed(0)}%</span>
              </div>
            `;
          })
          .join("")}
      </div>
    </div>
  `;
}

export function renderPipelineTrace(container, trace, spec, onGoArchitect) {
  if (!spec) {
    container.innerHTML = `
      <div class="stage-card">
        <h3 class="stage-card-title" style="margin-bottom:6px;">No Router Configured Yet</h3>
        <p class="stage-card-sub" style="margin-bottom:14px;">
          Build your custom Decision-Grounded LLM Router with the <strong>Router Architect Agent</strong> in Tab 1 first, then enter any task prompt here to visualize every step of the pipeline.
        </p>
        <button type="button" id="empty-go-arch-btn" class="primary-btn small-btn">
          Go to Tab 1 · Router Architect Agent &rarr;
        </button>
      </div>
    `;
    const btn = container.querySelector("#empty-go-arch-btn");
    if (btn && onGoArchitect) btn.addEventListener("click", onGoArchitect);
    return;
  }

  if (!trace) {
    container.innerHTML = `
      <div class="stage-card">
        <h3 class="stage-card-title" style="margin-bottom:6px;">Router Active — Enter a Prompt Above</h3>
        <p class="stage-card-sub">
          Type any test prompt in the box above and click <strong>Evaluate &amp; Route</strong> to watch how <code>gemini-decision-1</code> scores each of your rules and picks the right model.
        </p>
      </div>
    `;
    return;
  }

  const gateEvalMap = new Map(
    (trace.hard_gate_evaluations || []).map((g) => [g.key, g])
  );
  const topicLabelMap = new Map(
    (spec.topics || []).map((t) => [t.key, t.label])
  );
  const preGenCalls = (trace.decision_calls || []).filter(
    (c) => !c.stage_name.includes("Post-Answer")
  );
  const res = trace.resolution;
  const qg = trace.quality_gate;
  const cut = spec.tier_cutoffs;

  const wSimple = Math.max(5, cut.standard * 100);
  const wStd = Math.max(5, (cut.complex - cut.standard) * 100);
  const wComplex = Math.max(5, (cut.expert - cut.complex) * 100);
  const wExpert = Math.max(5, (1 - cut.expert) * 100);
  const pinLeft = Math.min(98.5, Math.max(1.5, res.composite_score * 100));

  const modeBadge =
    trace.mode === "live"
      ? `<span class="pill-badge emerald">LIVE gemini-decision-1</span>`
      : `<span class="pill-badge amber">SIMULATION MODE</span>`;

  // 1. Summary Stepper Rail
  const stepperHtml = `
    <div class="stepper-rail" aria-label="Pipeline Execution Summary">
      <div class="step-node ${res.triggered_gates.length ? "warn" : ""}">
        <div class="step-num">Step 1 · Input Rules</div>
        <div class="step-title">${
          res.triggered_gates.length
            ? `${res.triggered_gates.length} Rule Triggered`
            : "No Shortcut Fired"
        }</div>
        <div class="step-metric">${trace.hard_gate_evaluations.length} rule(s) checked</div>
      </div>
      <div class="step-node highlighted">
        <div class="step-num">Step 2 · Topic Score</div>
        <div class="step-title">Combined = ${(res.composite_score * 100).toFixed(1)}%</div>
        <div class="step-metric">Confidence ${(res.aggregate_confidence * 100).toFixed(0)}%</div>
      </div>
      <div class="step-node highlighted">
        <div class="step-num">Step 3 · Initial Model</div>
        <div class="step-title">${escapeHtml(res.selected_model_name)}</div>
        <div class="step-metric"><code>${escapeHtml(res.selected_model_id)}</code></div>
      </div>
      <div class="step-node ${qg.fallback_triggered ? "warn" : ""}">
        <div class="step-num">Step 4 · Output Check</div>
        <div class="step-title">${
          !qg.executed
            ? "Top Tier (No Fallback)"
            : qg.passed
            ? "Passed All Checks"
            : "Escalated +1 Tier"
        }</div>
        <div class="step-metric">${
          qg.fallback_triggered
            ? `&rarr; ${escapeHtml(qg.fallback_to_model)}`
            : "0 output tokens"
        }</div>
      </div>
      <div class="step-node">
        <div class="step-num">Step 5 · Final Cost</div>
        <div class="step-title">$${trace.total_cost_usd.toFixed(6)}</div>
        <div class="step-metric">${
          trace.savings_pct >= 0
            ? `Saved ${trace.savings_pct.toFixed(1)}% vs Carbon`
            : `Escalated +${Math.abs(trace.savings_pct).toFixed(1)}%`
        }</div>
      </div>
    </div>
  `;

  // 2. Decision API Pre-Routing Call Cards
  const decisionCallsHtml = `
    <div class="trace-section-grid">
      ${preGenCalls
        .map((call) => {
          const questionsReq = call.request_payload?.questions || {};
          const answersResp = call.response_payload?.answers || {};
          return `
            <article class="stage-card">
              <div class="stage-card-header">
                <div>
                  <h3 class="stage-card-title">${escapeHtml(call.stage_name)}</h3>
                  <p class="stage-card-sub">${escapeHtml(call.purpose)}</p>
                </div>
                <div class="badge-row">
                  <span class="pill-badge teal">0 output tok</span>
                  <span class="pill-badge">${call.latency_ms.toFixed(0)} ms</span>
                </div>
              </div>
              ${Object.entries(questionsReq)
                .map(([qKey, qDef]) =>
                  renderQuestionEvalBlock(
                    qKey,
                    qDef,
                    answersResp[qKey],
                    gateEvalMap,
                    topicLabelMap
                  )
                )
                .join("")}
              <details class="json-details">
                <summary>View Raw <code>gemini-decision-1</code> Request &amp; Response JSON</summary>
                <pre class="json-pre">${escapeHtml(
                  JSON.stringify(
                    { request: call.request_payload, response: call.response_payload },
                    null,
                    2
                  )
                )}</pre>
              </details>
            </article>
          `;
        })
        .join("")}
    </div>
  `;

  // 3. Weighted Score Combiner & Tier Threshold Ruler
  const combinerHtml = `
    <article class="stage-card">
      <div class="stage-card-header">
        <div>
          <h3 class="stage-card-title">How the Scores Combined to Pick a Model</h3>
          <p class="stage-card-sub">
            Weighted Topic Score (0% – 100%) mapped onto your 4 model bands, followed by any Input Shortcut or Guardrail overrides
          </p>
        </div>
        <div class="badge-row">
          ${modeBadge}
          <span class="pill-badge">Combined Score = ${(res.composite_score * 100).toFixed(1)}%</span>
        </div>
      </div>

      <div class="ruler-wrapper">
        <div class="score-pin" style="left: ${pinLeft}%">
          <span class="score-pin-tag">${(res.composite_score * 100).toFixed(1)}%</span>
          <span class="score-pin-stem"></span>
        </div>
        <div class="ruler-zones">
          <div class="ruler-zone simple" style="width: ${wSimple}%">Flash-Lite (&lt;${Math.round(cut.standard * 100)}%)</div>
          <div class="ruler-zone standard" style="width: ${wStd}%">Hydrogen (${Math.round(cut.standard * 100)}–${Math.round(cut.complex * 100)}%)</div>
          <div class="ruler-zone complex" style="width: ${wComplex}%">Neon (${Math.round(cut.complex * 100)}–${Math.round(cut.expert * 100)}%)</div>
          <div class="ruler-zone expert" style="width: ${wExpert}%">Carbon (&ge;${Math.round(cut.expert * 100)}%)</div>
        </div>
      </div>

      <table class="contrib-table">
        <thead>
          <tr>
            <th>Topic</th>
            <th>Normalized Topic Score</th>
            <th>Topic Weight</th>
            <th>Points Added to Combined Score</th>
          </tr>
        </thead>
        <tbody>
          ${trace.topic_scores
            .map(
              (t) => `
              <tr>
                <td>
                  <strong>${escapeHtml(t.label)}</strong>
                  <div style="font-size:11.5px;color:var(--ink-secondary);">${escapeHtml(t.instructions)}</div>
                </td>
                <td class="mono">${(t.normalized_score * 100).toFixed(1)}%</td>
                <td class="mono">${(t.effective_weight_share * 100).toFixed(0)}%</td>
                <td class="mono"><strong>+${(t.weighted_contribution * 100).toFixed(1)}%</strong></td>
              </tr>
            `
            )
            .join("")}
        </tbody>
      </table>

      <ul class="explanation-list">
        ${res.explanation
          .map((line) => `<li>${escapeHtml(line.replaceAll("->", "→").replaceAll(">=", "≥"))}</li>`)
          .join("")}
      </ul>
    </article>
  `;

  // 4. Candidate LLM Pool & Post-Answer Checks
  const llmCardsHtml = (spec.models || [])
    .map((m) => {
      const isFinal = m.model_id === trace.final_model_id;
      const isFbOrigin = qg.fallback_triggered && m.model_id === qg.fallback_from_model;
      return `
        <div class="llm-card ${isFinal ? "selected" : ""} ${isFbOrigin ? "fallback-origin" : ""}">
          <div class="llm-tier-tag">${escapeHtml(m.tier)}${isFinal ? " · FINAL MODEL" : isFbOrigin ? " · DRAFT 1 (ESCALATED)" : ""}</div>
          <div class="llm-name">${escapeHtml(m.display_name)}</div>
          <div class="llm-id">${escapeHtml(m.model_id)}</div>
          <div class="llm-price">$${m.input_price_per_1m.toFixed(2)} in / $${m.output_price_per_1m.toFixed(2)} out (1M)</div>
        </div>
      `;
    })
    .join("");

  const customPostHtml = (qg.custom_check_results || [])
    .map((pc) => {
      const pct = Math.round(pc.noul * 100);
      const tPct = Math.round(pc.threshold * 100);
      return `
        <div class="q-eval-block" style="margin-top: 10px;">
          <div class="q-eval-head">
            <span class="q-eval-name">Post-Answer Rule · ${escapeHtml(pc.label)}</span>
            <span class="q-eval-meta">
              Yes Probability = <strong>${pct}%</strong> (limit ${tPct}%) ·
              ${
                pc.triggered_escalation
                  ? `<span class="pill-badge amber">ESCALATED +1 TIER</span>`
                  : `<span class="pill-badge emerald">PASSED (&lt; ${tPct}%)</span>`
              }
            </span>
          </div>
          <div style="font-size:12px;color:var(--ink-secondary);margin-bottom:6px;">
            <em>Question on draft output: "${escapeHtml(pc.instructions)}"</em>
          </div>
          <div class="prob-bar-track">
            <div class="prob-bar-fill ${pc.triggered_escalation ? "triggered" : ""}" style="width: ${pct}%"></div>
            <div class="threshold-tick" style="left: ${tPct}%">
              <span class="threshold-tick-label">${tPct}%</span>
            </div>
          </div>
        </div>
      `;
    })
    .join("");

  const qgSectionHtml = qg.executed
    ? `
      ${customPostHtml}
      <div class="q-eval-block" style="margin-top: 10px;">
        <div class="q-eval-head">
          <span class="q-eval-name">Overall Answer Quality Check</span>
          <span class="q-eval-meta">
            Quality = <strong>${(qg.normalized_quality * 100).toFixed(0)}%</strong> (${qg.quality_10_scale}/10) ·
            ${
              qg.passed
                ? `<span class="pill-badge emerald">ACCEPTED</span>`
                : `<span class="pill-badge amber">ESCALATED: ${escapeHtml(qg.fallback_from_model)} &rarr; ${escapeHtml(qg.fallback_to_model)} (${escapeHtml(qg.fallback_reason || "")})</span>`
            }
          </span>
        </div>
        <div class="prob-bar-track">
          <div class="prob-bar-fill ${qg.passed ? "" : "triggered"}" style="width: ${Math.round((qg.normalized_quality || 0) * 100)}%"></div>
          <div class="threshold-tick" style="left: ${Math.round(qg.threshold * 100)}%">
            <span class="threshold-tick-label">${Math.round(qg.threshold * 100)}%</span>
          </div>
        </div>
      </div>
    `
    : "";

  const dispatchCardHtml = `
    <article class="stage-card">
      <div class="stage-card-header">
        <div>
          <h3 class="stage-card-title">Model Selection, Answer &amp; Post-Answer Checks</h3>
          <p class="stage-card-sub">Generates the answer on the chosen model and verifies output checks via <code>gemini-decision-1</code> (0 output tokens)</p>
        </div>
        <div class="badge-row">
          <span class="pill-badge emerald">Saved $${trace.saved_vs_ceiling_usd.toFixed(6)} (${trace.savings_pct.toFixed(1)}%) vs Carbon</span>
          <span class="pill-badge">Total ${trace.total_latency_ms.toFixed(0)} ms</span>
        </div>
      </div>

      <div class="llm-pool-grid">${llmCardsHtml}</div>
      <div class="answer-header-bar">
        <span class="section-eyebrow">Model Answer (${escapeHtml(trace.final_model_name)})</span>
        <button type="button" id="toggle-raw-md-btn" class="ghost-btn small-btn">View Raw Markdown</button>
      </div>
      <div id="model-answer-rendered" class="response-output-box markdown-body">${renderMarkdown(trace.final_response)}</div>
      <pre id="model-answer-raw" class="json-pre" hidden>${escapeHtml(trace.final_response)}</pre>
      ${qgSectionHtml}
    </article>
  `;

  container.innerHTML = stepperHtml + decisionCallsHtml + combinerHtml + dispatchCardHtml;

  const rawBtn = container.querySelector("#toggle-raw-md-btn");
  const renderedEl = container.querySelector("#model-answer-rendered");
  const rawEl = container.querySelector("#model-answer-raw");
  if (rawBtn && renderedEl && rawEl) {
    rawBtn.addEventListener("click", () => {
      const showingRaw = !rawEl.hidden;
      rawEl.hidden = showingRaw;
      renderedEl.hidden = !showingRaw;
      rawBtn.textContent = showingRaw ? "View Raw Markdown" : "View Rendered Markdown";
    });
  }
}
