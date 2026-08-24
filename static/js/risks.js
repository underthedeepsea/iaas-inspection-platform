import { escapeHtml, formatDate, get, number, percent, post, showError } from "./api.js";

const statusLabels = {
  NEW: "首次发现",
  PERSISTING: "风险持续",
  WORSENED: "风险加重",
  INVESTIGATING: "调查中",
  LOCATED: "已定位",
  PENDING_ACTION: "待处置",
  PENDING_REVERIFY: "待复验",
  RECOVERED: "已恢复",
  IGNORED: "已忽略",
};

function statusLabel(value) {
  return statusLabels[value] || value || "--";
}

function riskLink(risk) {
  return `/risks/${encodeURIComponent(risk.risk_id || risk.id)}`;
}

function renderRiskRows(target, risks) {
  if (!target) return;
  if (!risks.length) {
    target.innerHTML = '<tr><td colspan="7" class="empty-cell">没有符合条件的风险。</td></tr>';
    return;
  }
  target.innerHTML = risks.map((risk) => `
    <tr>
      <td><a class="risk-name" href="${riskLink(risk)}"><strong>${escapeHtml(risk.title || "未命名风险")}</strong><small>${escapeHtml(risk.risk_key || "")}</small></a></td>
      <td>${escapeHtml(risk.domain || "--")}</td>
      <td><span class="severity-badge severity-${escapeHtml(String(risk.severity || "").toLowerCase())}">${escapeHtml(risk.severity || "--")}</span></td>
      <td><span class="status-badge">${escapeHtml(statusLabel(risk.status))}</span></td>
      <td>${number(risk.occurrence_count)}</td>
      <td>${risk.ai_involved ? '<span class="ai-mark">AI 介入</span>' : '<span class="muted">代码判断</span>'}</td>
      <td><a class="text-link" href="${riskLink(risk)}">打开 →</a></td>
    </tr>`).join("");
}

function listParams(root) {
  const params = { page_size: 100 };
  if (root.dataset.riskSeverity) params.severity = root.dataset.riskSeverity;
  if (root.dataset.riskStatus) params.status = root.dataset.riskStatus;
  return params;
}

export async function loadRiskList(root) {
  const target = root.querySelector("[data-risk-list]");
  try {
    const payload = await get(root, "/risks", listParams(root));
    renderRiskRows(target, Array.isArray(payload.items) ? payload.items : []);
  } catch (error) {
    showError(target, error.message);
  }
}

function renderRiskSummary(root, risk) {
  root.querySelector("[data-risk-id-label]")?.replaceChildren(document.createTextNode(risk.risk_id || risk.id || ""));
  root.querySelector("[data-risk-domain]")?.replaceChildren(document.createTextNode(risk.domain || "RISK DETAIL"));
  root.querySelector("[data-risk-title]")?.replaceChildren(document.createTextNode(risk.title || "未命名风险"));
  root.querySelector("[data-risk-conclusion]")?.replaceChildren(document.createTextNode(risk.current_conclusion || "当前还没有形成最终结论。"));
  root.querySelector("[data-risk-impact]")?.replaceChildren(document.createTextNode(risk.impact_summary || "暂无影响摘要。"));
  root.querySelector("[data-risk-recommendation]")?.replaceChildren(document.createTextNode(risk.recommendation || "暂无处理建议。"));
  const status = root.querySelector("[data-risk-status]");
  if (status) {
    status.textContent = statusLabel(risk.status);
    status.className = `status-badge ${risk.severity === "P1" ? "status-critical" : ""}`;
  }
  const code = risk.codeization || {};
  const codeTarget = root.querySelector("[data-risk-codeization]");
  if (codeTarget) {
    codeTarget.innerHTML = `
      <div><dt>执行模式</dt><dd>${escapeHtml(code.execution_mode || "--")}</dd></div>
      <div><dt>代码状态</dt><dd>${escapeHtml(code.code_status || "--")}</dd></div>
      <div><dt>代码覆盖率</dt><dd>${escapeHtml(percent(code.code_coverage_percent))}</dd></div>`;
  }
  root.__riskDetail = risk;
}

function renderTimeline(root, payload) {
  const target = root.querySelector("[data-risk-timeline]");
  if (!target) return;
  const events = Array.isArray(payload?.events) ? payload.events : [];
  if (!events.length) {
    target.innerHTML = '<li class="empty-cell">暂无生命周期事件。</li>';
    return;
  }
  target.innerHTML = events.map((event) => `
    <li><strong>${escapeHtml(event.label || statusLabel(event.to_status))}</strong><span>${escapeHtml(event.reason || "系统记录")}</span><small>${escapeHtml(formatDate(event.at, true))} · ${escapeHtml(event.source || "SYSTEM")}</small></li>
  `).join("");
}

function renderEvidence(root, payload) {
  const target = root.querySelector("[data-evidence-list]");
  if (!target) return;
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) {
    target.innerHTML = '<span class="empty-cell">暂无关键证据。</span>';
    return;
  }
  target.innerHTML = items.map((item) => `
    <article class="evidence-item"><header><strong>${escapeHtml(item.evidence_key || item.evidence_type || "证据")}</strong><small>${escapeHtml(item.evidence_type || "")}</small></header><p>${escapeHtml(item.summary || "暂无摘要")}</p><small>${escapeHtml(item.source || "未知来源")} · 置信度 ${escapeHtml(percent(Number(item.confidence || 0) * 100))}</small></article>
  `).join("");
}

export async function loadRiskDetail(root) {
  const riskId = root.dataset.riskId;
  if (!riskId) return;
  try {
    const [risk, timeline, evidence] = await Promise.all([
      get(root, `/risks/${encodeURIComponent(riskId)}`),
      get(root, `/risks/${encodeURIComponent(riskId)}/timeline`),
      get(root, `/risks/${encodeURIComponent(riskId)}/evidence`, { limit: 50 }),
    ]);
    renderRiskSummary(root, risk);
    renderTimeline(root, timeline);
    renderEvidence(root, evidence);
    const advanced = root.querySelector("[data-advanced-evidence]");
    if (advanced) advanced.textContent = `${evidence.total || evidence.items?.length || 0} 条证据已按需索引。展开内容仍受 API 安全投影限制。`;
  } catch (error) {
    root.querySelector("[data-risk-title]")?.replaceChildren(document.createTextNode("风险暂时无法加载"));
    root.querySelector("[data-risk-conclusion]")?.replaceChildren(document.createTextNode(error.message));
    showError(root.querySelector("[data-risk-timeline]"), "暂无生命周期数据");
    showError(root.querySelector("[data-evidence-list]"), "暂无证据数据");
  }
}

export function bindRiskFilters(root, refresh) {
  root.querySelectorAll("[data-severity], [data-status]").forEach((button) => {
    button.addEventListener("click", () => {
      root.querySelectorAll("[data-severity], [data-status]").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      root.dataset.riskSeverity = button.dataset.severity || "";
      root.dataset.riskStatus = button.dataset.status || "";
      refresh();
    });
  });
}

async function mutateRisk(root, action, body = {}) {
  const riskId = root.dataset.riskId;
  if (!riskId) return;
  const status = root.querySelector("[data-risk-status]");
  try {
    const result = await post(root, `/risks/${encodeURIComponent(riskId)}/${action}`, body);
    if (status) status.textContent = statusLabel(result.status);
    await loadRiskDetail(root);
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

export function bindRiskActions(root) {
  root.querySelector("[data-mark-handled]")?.addEventListener("click", () => {
    mutateRisk(root, "mark-handled", { comment: "已通过巡检控制台记录处置，等待自动复验。" });
  });
  root.querySelector("[data-reverify]")?.addEventListener("click", () => mutateRisk(root, "reverify"));
}
