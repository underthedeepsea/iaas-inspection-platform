import { escapeHtml, formatDate, get, listResponse, number, percent, showError } from "./api.js";

const modeLabels = {
  CODE_ONLY: "纯代码",
  CODE_FIRST_AI_FALLBACK: "Code-first + AI",
  AI_INVESTIGATION: "AI 调查",
  LEARNING_MODE: "学习中",
};

function renderCapabilitySummary(root, items) {
  const target = root.querySelector("[data-capability-summary]");
  if (!target) return;
  const coded = items.filter((item) => item.code_status === "CODE_ACTIVE").length;
  const partial = items.filter((item) => ["PARTIAL_CODE", "SHADOW", "CODE_PENDING"].includes(item.code_status)).length;
  const ai = items.filter((item) => item.execution_mode === "AI_INVESTIGATION").length;
  target.innerHTML = [
    ["完全代码化", coded, "CODE_ACTIVE"],
    ["正在演进", partial, "SHADOW / PENDING"],
    ["仍依赖 AI", ai, "AI_INVESTIGATION"],
  ].map(([label, value, note]) => `<div class="summary-pill"><span>${label}</span><strong>${number(value)}</strong><small class="muted">${note}</small></div>`).join("");
}

function renderItems(root, items) {
  const target = root.querySelector("[data-inspection-items]");
  if (!target) return;
  if (!items.length) {
    target.innerHTML = '<tr><td colspan="6" class="empty-cell">暂无巡检能力。</td></tr>';
    return;
  }
  target.innerHTML = items.map((item) => `
    <tr>
      <td><div class="risk-name"><strong>${escapeHtml(item.name || item.code || "未命名项目")}</strong><small>${escapeHtml(item.code || "")}</small></div></td>
      <td><span class="mode-badge">${escapeHtml(modeLabels[item.execution_mode] || item.execution_mode || "--")}</span></td>
      <td>${escapeHtml(item.code_status || "--")}</td>
      <td>${escapeHtml(percent(item.code_coverage_percent))}</td>
      <td><span class="llm-responsibility" title="${escapeHtml((item.llm_responsibilities || []).join("；"))}">${escapeHtml((item.llm_responsibilities || []).join("；") || "无，代码已覆盖")}</span></td>
      <td><a class="text-link" href="/capabilities">查看 →</a></td>
    </tr>`).join("");
}

export async function loadCapabilities(root) {
  try {
    const [itemPayload, capabilityPayload] = await Promise.all([
      get(root, "/inspection-items", { page_size: 100 }),
      get(root, "/capabilities", { page_size: 100 }),
    ]);
    const items = listResponse(itemPayload);
    const capabilities = listResponse(capabilityPayload);
    renderCapabilitySummary(root, items);
    renderItems(root, items);
    root.__capabilities = capabilities;
  } catch (error) {
    showError(root.querySelector("[data-inspection-items]"), error.message);
    showError(root.querySelector("[data-capability-summary]"), "暂无能力统计");
  }
}

function renderEvolutionMetrics(root, snapshot) {
  ["code_coverage_rate", "deterministic_deflection_rate", "ai_displacement_rate"].forEach((key) => {
    root.querySelector(`[data-evolution="${key}"]`)?.replaceChildren(
      document.createTextNode(percent(snapshot?.[key])),
    );
  });
}

function renderEvolutionQueue(root, tasks) {
  const target = root.querySelector("[data-evolution-queue]");
  if (!target) return;
  if (!tasks.length) {
    target.innerHTML = '<span class="empty-cell">暂无待处理的代码化任务。</span>';
    return;
  }
  target.innerHTML = tasks.slice(0, 6).map((task) => `
    <div class="maturity-row"><span>${escapeHtml(task.title || task.target_capability_id || "代码化任务")}</span><strong>${escapeHtml(task.status || "--")}</strong><div class="progress-track"><i style="width:${Math.min(100, Math.max(0, Number(task.precision || 0) * 100))}%"></i></div></div>
  `).join("");
}

export async function loadEvolution(root) {
  try {
    const [snapshotPayload, taskPayload] = await Promise.all([
      get(root, "/daily-snapshots", { page_size: 30 }),
      get(root, "/codeization-tasks", { page_size: 50 }),
    ]);
    const snapshots = listResponse(snapshotPayload);
    renderEvolutionMetrics(root, snapshots[0] || {});
    renderEvolutionQueue(root, listResponse(taskPayload));
  } catch (error) {
    renderEvolutionMetrics(root, {});
    showError(root.querySelector("[data-evolution-queue]"), error.message);
  }
}

export async function loadExperiences(root) {
  const target = root.querySelector("[data-experiences]");
  try {
    const payload = await get(root, "/experiences", { page_size: 100 });
    const experiences = listResponse(payload);
    if (!experiences.length) {
      target.innerHTML = '<tr><td colspan="5" class="empty-cell">暂无人工反馈形成的经验。</td></tr>';
      return;
    }
    target.innerHTML = experiences.map((experience) => `
      <tr><td><div class="risk-name"><strong>${escapeHtml(experience.title || experience.experience_key || "未命名经验")}</strong><small>${escapeHtml(experience.domain || "")}</small></div></td><td><span class="status-badge">${escapeHtml(experience.code_status || experience.status || "--")}</span></td><td>${escapeHtml(experience.target_claim || "--")}</td><td>${escapeHtml(experience.source_risk_id ? "风险反馈" : "人工输入")}</td><td class="muted">${escapeHtml(formatDate(experience.created_at, true))}</td></tr>
    `).join("");
  } catch (error) {
    showError(target, error.message);
  }
}
