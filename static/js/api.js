const DEFAULT_BASE = "/api/v1";

function baseUrl(root) {
  return (root?.dataset.apiBase || DEFAULT_BASE).replace(/\/$/, "");
}

function urlFor(root, path, params = {}) {
  const normalized = String(path).startsWith("/") ? path : `/${path}`;
  const url = new URL(`${baseUrl(root)}${normalized}`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  return url;
}

async function decode(response) {
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const error = body?.error || {};
    throw new Error(error.message || `请求失败（${response.status}）`);
  }
  return body;
}

export async function request(root, path, options = {}) {
  const { params, body, ...init } = options;
  const response = await fetch(urlFor(root, path, params), {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(init.headers || {}),
    },
    ...init,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return decode(response);
}

export function get(root, path, params) {
  return request(root, path, { method: "GET", params });
}

export function post(root, path, body = {}) {
  return request(root, path, { method: "POST", body });
}

export function put(root, path, body = {}) {
  return request(root, path, { method: "PUT", body });
}

export function formatDate(value, withTime = false) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return String(value).slice(0, 16);
  return new Intl.DateTimeFormat("zh-CN", withTime ? {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  } : { month: "2-digit", day: "2-digit" }).format(date);
}

export function number(value, digits = 0) {
  if (value === null || value === undefined || value === "") return "--";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "--";
  return parsed.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function percent(value, digits = 1) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${number(parsed, digits)}%` : "--";
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function listResponse(value) {
  return Array.isArray(value) ? value : Array.isArray(value?.items) ? value.items : [];
}

export function showError(node, message) {
  if (!node) return;
  node.innerHTML = `<span class="empty-cell">${escapeHtml(message || "暂时无法加载数据")}</span>`;
}

export function apiPath(root, path) {
  return urlFor(root, path).toString();
}
