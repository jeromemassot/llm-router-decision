/**
 * TopicWeightStudio.js
 * Clear, human-readable sliders for adjusting Topic Weights, Input Rule Thresholds,
 * Combined Score Tier Cutoffs, and Post-Answer Escalation Thresholds.
 */

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export function renderWorkbench(
  container,
  spec,
  onSpecUpdated,
  onFullReroute,
  onGoArchitect
) {
  if (!spec) {
    container.innerHTML = `
      <div class="stage-card">
        <h3 class="stage-card-title" style="margin-bottom:6px;">No Topics or Thresholds Defined Yet</h3>
        <p class="stage-card-sub" style="margin-bottom:14px;">
          Start in Tab 1 (<strong>Router Architect Agent</strong>) and describe the rules and topics that matter to you. Once your router is created, you can fine-tune every weight and percentage threshold here.
        </p>
        <button type="button" id="wb-go-arch-btn" class="primary-btn small-btn">
          Go to Tab 1 · Router Architect Agent &rarr;
        </button>
      </div>
    `;
    const btn = container.querySelector("#wb-go-arch-btn");
    if (btn && onGoArchitect) btn.addEventListener("click", onGoArchitect);
    return;
  }

  const totalWeight =
    spec.topics
      .filter((t) => t.enabled)
      .reduce((sum, t) => sum + t.weight, 0) || 1;

  container.innerHTML = `
    <div class="workbench-grid">
      <!-- Weighted Scoring Topics Column -->
      <section class="stage-card">
        <div class="stage-card-header">
          <div>
            <h3 class="stage-card-title">Step 2 · Weighted Scoring Topics</h3>
            <p class="stage-card-sub">Adjust how much each topic contributes to the Combined Score (0% – 100%)</p>
          </div>
          <button type="button" id="wb-reroute-btn" class="primary-btn small-btn">Re-Run Prompt</button>
        </div>
        ${spec.topics
          .map((t, idx) => {
            const sharePct = t.enabled ? Math.round((t.weight / totalWeight) * 100) : 0;
            return `
            <div class="slider-row">
              <div class="slider-top">
                <label>
                  <input type="checkbox" class="wb-topic-enable" data-idx="${idx}" ${t.enabled ? "checked" : ""} />
                  ${escapeHtml(t.label)}
                </label>
                <span class="mono" id="wb-tw-val-${idx}">${sharePct}% share (w=${t.weight.toFixed(2)})</span>
              </div>
              <input
                type="range"
                class="range-slider wb-topic-weight"
                data-idx="${idx}"
                min="0.05"
                max="1.5"
                step="0.05"
                value="${t.weight}"
              />
              <div style="font-size:12px;color:var(--ink-secondary);margin-top:4px;">
                <em>Question: "${escapeHtml(t.instructions)}"</em>
              </div>
            </div>
          `;
          })
          .join("")}
      </section>

      <!-- Input Rules, Tier Cutoffs & Post-Answer Checks Column -->
      <section class="stage-card">
        <div class="stage-card-header">
          <div>
            <h3 class="stage-card-title">Thresholds &amp; Model Cutoffs</h3>
            <p class="stage-card-sub">Tune Yes/No rule probability thresholds and Combined Score model bands</p>
          </div>
        </div>

        <div class="section-eyebrow" style="margin-bottom:8px;">Step 1 · Input Shortcut &amp; Guardrail Rules</div>
        ${
          spec.hard_gates.length
            ? spec.hard_gates
                .map(
                  (g, idx) => `
                  <div class="slider-row">
                    <div class="slider-top">
                      <label>
                        <input type="checkbox" class="wb-gate-enable" data-idx="${idx}" ${g.enabled ? "checked" : ""} />
                        ${escapeHtml(g.label)}
                      </label>
                      <span class="mono" id="wb-gt-val-${idx}">Threshold = ${Math.round(g.threshold * 100)}%</span>
                    </div>
                    <input
                      type="range"
                      class="range-slider wb-gate-thresh"
                      data-idx="${idx}"
                      min="0.10"
                      max="0.95"
                      step="0.05"
                      value="${g.threshold}"
                    />
                    <div style="font-size:11.5px;color:var(--ink-secondary);margin-top:3px;">
                      <em>"${escapeHtml(g.instructions)}"</em>
                    </div>
                  </div>
                `
                )
                .join("")
            : `<p class="stage-card-sub" style="margin-bottom:12px;">No input shortcut rules configured.</p>`
        }

        <div class="section-eyebrow" style="margin:16px 0 8px;">Combined Score Cutoffs (Model Tier Boundaries)</div>
        <div class="slider-row">
          <div class="slider-top">
            <span>Flash-Lite &rarr; Hydrogen</span>
            <span class="mono" id="wb-cut-std">${Math.round(spec.tier_cutoffs.standard * 100)}%</span>
          </div>
          <input type="range" id="wb-slider-std" class="range-slider" min="0.10" max="0.50" step="0.02" value="${spec.tier_cutoffs.standard}" />
        </div>
        <div class="slider-row">
          <div class="slider-top">
            <span>Hydrogen &rarr; Neon</span>
            <span class="mono" id="wb-cut-cplx">${Math.round(spec.tier_cutoffs.complex * 100)}%</span>
          </div>
          <input type="range" id="wb-slider-cplx" class="range-slider" min="0.25" max="0.78" step="0.02" value="${spec.tier_cutoffs.complex}" />
        </div>
        <div class="slider-row">
          <div class="slider-top">
            <span>Neon &rarr; Carbon</span>
            <span class="mono" id="wb-cut-exp">${Math.round(spec.tier_cutoffs.expert * 100)}%</span>
          </div>
          <input type="range" id="wb-slider-exp" class="range-slider" min="0.50" max="0.95" step="0.02" value="${spec.tier_cutoffs.expert}" />
        </div>

        <div class="section-eyebrow" style="margin:16px 0 8px;">Step 3 · Post-Answer Escalation Checks</div>
        ${(spec.quality_gate.custom_checks || [])
          .map(
            (pc, idx) => `
            <div class="slider-row">
              <div class="slider-top">
                <label>
                  <input type="checkbox" class="wb-post-enable" data-idx="${idx}" ${pc.enabled ? "checked" : ""} />
                  ${escapeHtml(pc.label)} (+1 Tier)
                </label>
                <span class="mono" id="wb-pc-val-${idx}">Limit = ${Math.round(pc.threshold * 100)}%</span>
              </div>
              <input
                type="range"
                class="range-slider wb-post-thresh"
                data-idx="${idx}"
                min="0.10"
                max="0.95"
                step="0.05"
                value="${pc.threshold}"
              />
              <div style="font-size:11.5px;color:var(--ink-secondary);margin-top:3px;">
                <em>"${escapeHtml(pc.instructions)}"</em>
              </div>
            </div>
          `
          )
          .join("")}

        <div class="slider-row">
          <div class="slider-top">
            <label>
              <input type="checkbox" id="wb-qg-enable" ${spec.quality_gate.enabled ? "checked" : ""} />
              Minimum Overall Answer Quality
            </label>
            <span class="mono" id="wb-qg-val">${Math.round(spec.quality_gate.threshold * 100)}%</span>
          </div>
          <input type="range" id="wb-slider-qg" class="range-slider" min="0.40" max="0.92" step="0.02" value="${spec.quality_gate.threshold}" />
        </div>
      </section>
    </div>

    <details class="stage-card json-details">
      <summary>Inspect Full <code>RouterSpec</code> JSON Configuration</summary>
      <pre class="json-pre" id="wb-spec-json">${escapeHtml(JSON.stringify(spec, null, 2))}</pre>
    </details>
  `;

  const syncJsonPreview = () => {
    const pre = container.querySelector("#wb-spec-json");
    if (pre) pre.textContent = JSON.stringify(spec, null, 2);
  };

  const refreshTopicLabels = () => {
    const tot =
      spec.topics
        .filter((t) => t.enabled)
        .reduce((s, t) => s + t.weight, 0) || 1;
    spec.topics.forEach((t, i) => {
      const share = t.enabled ? Math.round((t.weight / tot) * 100) : 0;
      const lbl = container.querySelector(`#wb-tw-val-${i}`);
      if (lbl) lbl.textContent = `${share}% share (w=${t.weight.toFixed(2)})`;
    });
  };

  container.querySelectorAll(".wb-topic-weight").forEach((el) => {
    el.addEventListener("input", () => {
      const idx = Number(el.dataset.idx);
      spec.topics[idx].weight = Number(el.value);
      refreshTopicLabels();
      syncJsonPreview();
      onSpecUpdated(spec);
    });
  });

  container.querySelectorAll(".wb-topic-enable").forEach((el) => {
    el.addEventListener("change", () => {
      const idx = Number(el.dataset.idx);
      spec.topics[idx].enabled = el.checked;
      if (!spec.topics.some((t) => t.enabled && t.weight > 0)) {
        spec.topics[idx].enabled = true;
        el.checked = true;
      }
      refreshTopicLabels();
      syncJsonPreview();
      onSpecUpdated(spec);
    });
  });

  container.querySelectorAll(".wb-gate-thresh").forEach((el) => {
    el.addEventListener("input", () => {
      const idx = Number(el.dataset.idx);
      spec.hard_gates[idx].threshold = Number(el.value);
      container.querySelector(`#wb-gt-val-${idx}`).textContent = `Threshold = ${Math.round(spec.hard_gates[idx].threshold * 100)}%`;
      syncJsonPreview();
      onSpecUpdated(spec);
    });
  });

  container.querySelectorAll(".wb-gate-enable").forEach((el) => {
    el.addEventListener("change", () => {
      const idx = Number(el.dataset.idx);
      spec.hard_gates[idx].enabled = el.checked;
      syncJsonPreview();
      onSpecUpdated(spec);
    });
  });

  container.querySelectorAll(".wb-post-thresh").forEach((el) => {
    el.addEventListener("input", () => {
      const idx = Number(el.dataset.idx);
      spec.quality_gate.custom_checks[idx].threshold = Number(el.value);
      container.querySelector(`#wb-pc-val-${idx}`).textContent = `Limit = ${Math.round(spec.quality_gate.custom_checks[idx].threshold * 100)}%`;
      syncJsonPreview();
      onSpecUpdated(spec);
    });
  });

  container.querySelectorAll(".wb-post-enable").forEach((el) => {
    el.addEventListener("change", () => {
      const idx = Number(el.dataset.idx);
      spec.quality_gate.custom_checks[idx].enabled = el.checked;
      syncJsonPreview();
      onSpecUpdated(spec);
    });
  });

  const sStd = container.querySelector("#wb-slider-std");
  const sCplx = container.querySelector("#wb-slider-cplx");
  const sExp = container.querySelector("#wb-slider-exp");

  const updateCutoffs = () => {
    let v1 = Number(sStd.value);
    let v2 = Math.max(v1 + 0.06, Number(sCplx.value));
    let v3 = Math.max(v2 + 0.06, Number(sExp.value));
    v3 = Math.min(0.95, v3);
    v2 = Math.min(v3 - 0.06, v2);
    v1 = Math.min(v2 - 0.06, v1);

    sStd.value = v1;
    sCplx.value = v2;
    sExp.value = v3;
    spec.tier_cutoffs = {
      standard: Number(v1.toFixed(2)),
      complex: Number(v2.toFixed(2)),
      expert: Number(v3.toFixed(2)),
    };
    container.querySelector("#wb-cut-std").textContent = `${Math.round(v1 * 100)}%`;
    container.querySelector("#wb-cut-cplx").textContent = `${Math.round(v2 * 100)}%`;
    container.querySelector("#wb-cut-exp").textContent = `${Math.round(v3 * 100)}%`;
    syncJsonPreview();
    onSpecUpdated(spec);
  };

  sStd.addEventListener("input", updateCutoffs);
  sCplx.addEventListener("input", updateCutoffs);
  sExp.addEventListener("input", updateCutoffs);

  const sQg = container.querySelector("#wb-slider-qg");
  sQg.addEventListener("input", () => {
    spec.quality_gate.threshold = Number(sQg.value);
    container.querySelector("#wb-qg-val").textContent = `${Math.round(spec.quality_gate.threshold * 100)}%`;
    syncJsonPreview();
  });

  container.querySelector("#wb-qg-enable").addEventListener("change", (e) => {
    spec.quality_gate.enabled = e.target.checked;
    syncJsonPreview();
  });

  container.querySelector("#wb-reroute-btn").addEventListener("click", () => {
    onFullReroute();
  });
}
