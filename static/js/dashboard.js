import { escapeHtml, formatDate, get, number, showError } from "./api.js";

const metricKeys = ["p1_count", "p2_count", "new_count", "pending_action_count", "data_completeness_rate"];

function setMetric(root, key, value) {
  root.querySelectorAll(`[data-metric="${key}"]`).forEach((node) => {
    node.textContent = key === "data_completeness_rate" ? number(value, 1) : number(value);
  });
}

function renderTopRisks(root, risks) {
  const target = root.querySelector("[data-top-risks]");
  if (!target) return;
  if (!risks.length) {
    target.innerHTML = '<tr><td colspan="5" class="empty-cell">今天没有需要优先关注的风险。</td></tr>';
    return;
  }
  target.innerHTML = risks.map((risk) => `
    <tr>
      <td><a class="risk-name" href="/risks/${encodeURIComponent(risk.risk_id || risk.id)}"><strong>${escapeHtml(risk.title || "未命名风险")}</strong><small>${escapeHtml(risk.domain || "未分类")}</small></a></td>
      <td><span class="severity-badge severity-${escapeHtml(String(risk.severity || "").toLowerCase())}">${escapeHtml(risk.severity || "--")}</span></td>
      <td><span class="status-badge ${risk.status === "P1" ? "status-critical" : ""}">${escapeHtml(risk.status || "--")}</span></td>
      <td class="muted">${escapeHtml(formatDate(risk.last_seen_at, true))}</td>
      <td><a class="text-link" href="/risks/${encodeURIComponent(risk.risk_id || risk.id)}">详情 →</a></td>
    </tr>`).join("");
}

function renderTrend(root, snapshots) {
  const target = root.querySelector("[data-trend-chart]");
  if (!target) return;
  if (!snapshots.length) {
    target.innerHTML = '<span class="empty-cell">暂无趋势数据</span>';
    return;
  }
  const values = snapshots.map((item) => Number(item.risk_total) || 0);
  const max = Math.max(...values, 1);
  target.innerHTML = snapshots.map((item, index) => {
    const label = formatDate(item.date || item.snapshot_date);
    const height = Math.max(5, Math.round(((values[index] || 0) / max) * 100));
    return `<div class="trend-column" title="${escapeHtml(label)}：${number(values[index])} 个风险"><i class="trend-bar" style="height:${height}%"></i><span>${escapeHtml(label)}</span></div>`;
  }).join("");
}

function renderMaturity(root, maturity) {
  const target = root.querySelector("[data-maturity-list]");
  if (!target) return;
  const enabled = Number(maturity?.enabled_items) || 0;
  const coded = Number(maturity?.coded_items) || 0;
  const ratio = enabled ? Math.round((coded / enabled) * 100) : 0;
  target.innerHTML = [
    ["已代码化巡检", coded, ratio],
    ["已启用巡检", enabled, 100],
  ].map(([label, value, width]) => `
    <div class="maturity-row"><span>${label}</span><strong>${number(value)}</strong><div class="progress-track"><i style="width:${width}%"></i></div></div>
  `).join("");
  root.querySelector("[data-capability-coded]")?.replaceChildren(document.createTextNode(number(coded)));
  root.querySelector("[data-capability-total]")?.replaceChildren(document.createTextNode(number(enabled)));
}

export async function loadDashboard(root) {
  const params = root.dataset.environment ? { environment: root.dataset.environment } : {};
  try {
    const payload = await get(root, "/dashboard/today", params);
    const snapshot = payload.snapshot || {};
    metricKeys.forEach((key) => setMetric(root, key, snapshot[key]));
    root.querySelector("[data-metric-note='pending_reverify_count']")?.replaceChildren(
      document.createTextNode(`含待复验 ${number(snapshot.pending_reverify_count)}`),
    );
    root.querySelector("[data-today-date]")?.replaceChildren(
      document.createTextNode(formatDate(snapshot.date || snapshot.snapshot_date)),
    );
    root.querySelector("[data-freshness]")?.replaceChildren(
      document.createTextNode(`快照已更新 · ${formatDate(snapshot.date || snapshot.snapshot_date, true)}`),
    );
    renderTopRisks(root, Array.isArray(payload.top_risks) ? payload.top_risks : []);
    renderTrend(root, Array.isArray(payload.trend_7d) ? payload.trend_7d : []);
    renderMaturity(root, payload.capability_maturity || {});
  } catch (error) {
    root.querySelector("[data-freshness]")?.replaceChildren(document.createTextNode("暂无可用快照"));
    root.querySelector("[data-today-date]")?.replaceChildren(document.createTextNode("等待首次巡检"));
    showError(root.querySelector("[data-top-risks]"), error.message);
    showError(root.querySelector("[data-trend-chart]"), "暂无趋势数据");
    showError(root.querySelector("[data-maturity-list]"), "暂无能力数据");
  }
}
