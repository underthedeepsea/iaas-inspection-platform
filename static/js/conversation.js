import { escapeHtml, get, post } from "./api.js";

const eventLabels = {
  "investigation.started": "调查已开始",
  "llm.requested": "AI 正在整理判断",
  "tool.requested": "请求只读证据",
  "tool.completed": "证据已返回",
  "investigation.completed": "调查完成",
  "turn.completed": "本轮完成",
  "turn.error": "调查遇到问题",
};

function drawer(root) {
  return root.querySelector("[data-ai-drawer]");
}

function setStatus(root, text) {
  root.querySelector("[data-conversation-status]")?.replaceChildren(document.createTextNode(text));
}

function renderMessages(root, messages) {
  const target = root.querySelector("[data-conversation-messages]");
  if (!target) return;
  if (!messages.length) {
    target.innerHTML = '<div class="empty-state compact"><p>输入问题后，AI 会从当前风险上下文开始调查。</p></div>';
    return;
  }
  target.innerHTML = messages.map((message) => {
    const role = message.role === "USER" ? "你" : "AI 助手";
    return `<article class="message message-${message.role === "USER" ? "user" : "assistant"}"><span class="message-meta">${role}</span>${escapeHtml(message.content || "")}</article>`;
  }).join("");
  target.scrollTop = target.scrollHeight;
}

function renderEvents(root, events) {
  const target = root.querySelector("[data-investigation-events]");
  if (!target) return;
  if (!events.length) {
    target.innerHTML = '<p class="muted">暂无调查事件。</p>';
    return;
  }
  target.innerHTML = `<div class="maturity-list">${events.map((event) => {
    const data = event.data || {};
    const detail = data.summary || data.status || data.capability_id || "已记录";
    return `<div class="maturity-row"><span>${escapeHtml(eventLabels[event.event] || event.event || "调查事件")}</span><strong>${escapeHtml(String(detail).slice(0, 80))}</strong></div>`;
  }).join("")}</div>`;
}

async function loadMessages(root, conversationId) {
  const payload = await get(root, `/conversations/${encodeURIComponent(conversationId)}/messages`);
  renderMessages(root, Array.isArray(payload.messages) ? payload.messages : []);
}

async function loadEvents(root, eventsUrl) {
  if (!eventsUrl) return;
  try {
    const response = await fetch(new URL(eventsUrl, window.location.origin), {
      credentials: "same-origin",
      headers: { Accept: "text/event-stream" },
    });
    if (!response.ok) return;
    const text = await response.text();
    const events = text.split(/\n\n+/).map((chunk) => {
      const dataLine = chunk.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) return null;
      try { return JSON.parse(dataLine.slice(5).trim()); } catch { return null; }
    }).filter(Boolean);
    renderEvents(root, events);
  } catch {
    renderEvents(root, []);
  }
}

function openDrawer(root) {
  const current = root.__riskDetail;
  const target = drawer(root);
  if (!target) return;
  target.hidden = false;
  root.querySelector("[data-conversation-context]")?.replaceChildren(
    document.createTextNode(current?.title ? `当前风险：${current.title}` : "围绕当前风险补充证据或追问判断。"),
  );
  root.querySelector("[data-conversation-form] textarea")?.focus();
}

function closeDrawer(root) {
  const target = drawer(root);
  if (target) target.hidden = true;
}

async function submitQuestion(root, event) {
  event.preventDefault();
  const riskId = root.dataset.riskId;
  const form = event.currentTarget;
  const input = form.elements.message;
  const question = input.value.trim();
  if (!riskId || !question) return;
  const submit = form.querySelector("button[type=submit]");
  if (submit) submit.disabled = true;
  setStatus(root, "调查中 · 正在读取只读证据");
  try {
    const result = await post(root, `/risks/${encodeURIComponent(riskId)}/investigations`, {
      trigger_type: "HUMAN",
      question,
    });
    root.__conversation = result;
    input.value = "";
    if (result.conversation_id) await loadMessages(root, result.conversation_id);
    await loadEvents(root, result.events_url);
    setStatus(root, "调查完成 · 可继续追问");
  } catch (error) {
    setStatus(root, error.message);
  } finally {
    if (submit) submit.disabled = false;
  }
}

async function sendFeedback(root, type) {
  const risk = root.__riskDetail || {};
  const conversation = root.__conversation || {};
  let comment = "";
  if (type === "MISSING_EVIDENCE") comment = window.prompt("请补充你认为缺失的证据（可留空）：") || "";
  try {
    await post(root, "/feedback", {
      environment_id: risk.environment_id,
      risk_id: risk.risk_id || risk.id,
      investigation_id: conversation.investigation_id,
      conversation_id: conversation.conversation_id,
      feedback_type: type,
      rating: type === "HELPFUL" ? 5 : 2,
      comment,
      create_experience: false,
    });
    const status = root.querySelector("[data-feedback-actions] .muted");
    if (status) status.textContent = "反馈已记录，谢谢。";
  } catch (error) {
    const status = root.querySelector("[data-feedback-actions] .muted");
    if (status) status.textContent = error.message;
  }
}

export function initConversation(root) {
  root.querySelector("[data-open-ai]")?.addEventListener("click", () => openDrawer(root));
  root.querySelector("[data-close-ai]")?.addEventListener("click", () => closeDrawer(root));
  root.querySelector("[data-conversation-form]")?.addEventListener("submit", (event) => submitQuestion(root, event));
  root.querySelectorAll("[data-feedback-type]").forEach((button) => {
    button.addEventListener("click", () => sendFeedback(root, button.dataset.feedbackType));
  });
}
