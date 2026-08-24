import { escapeHtml, get } from "./api.js";

async function loadProductMeta() {
  const target = document.querySelector("[data-product-meta]");
  if (!target) return;
  try {
    const root = document.querySelector("[data-api-base]") || document.body;
    const product = await get(root, "/product-info");
    const versions = product.versions || {};
    target.innerHTML = `
      <span>数据源：${escapeHtml(product.data_mode || "MOCK")}</span>
      <span>Provider：${escapeHtml(product.llm_provider || "ollama")}</span>
      <span>安全模式：${escapeHtml(product.security_mode || "READ_ONLY_TOOLS")}</span>
      <span>Web Runtime：Django ${escapeHtml(versions.django || "4.2.16")}</span>`;
  } catch {
    // The static product page remains useful when the API is not running.
  }
}

loadProductMeta();
