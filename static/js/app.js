import { loadCapabilities, loadEvolution, loadExperiences } from "./capabilities.js";
import { loadDashboard } from "./dashboard.js";
import { initConversation } from "./conversation.js";
import { bindRiskActions, bindRiskFilters, loadRiskDetail, loadRiskList } from "./risks.js";
import { escapeHtml } from "./api.js";

const pageTitles = {
  dashboard: "每日巡检",
  risks: "风险中心",
  "risk-detail": "风险详情",
  history: "历史趋势",
  pending: "待处置",
  capabilities: "巡检能力",
  experiences: "规则与经验",
  evolution: "能力演进",
  "ai-runtime": "AI 运行情况",
  settings: "系统设置",
};

function showView(root, page) {
  root.querySelectorAll("[data-view]").forEach((view) => {
    view.hidden = view.dataset.view !== page;
  });
}

function activateNavigation(root, page) {
  const activePage = page === "risk-detail" ? "risks" : page;
  root.querySelectorAll("[data-page-link]").forEach((link) => {
    link.classList.toggle("is-active", link.dataset.pageLink === activePage);
  });
  root.querySelector("[data-page-title]")?.replaceChildren(
    document.createTextNode(pageTitles[page] || "IaaS 智能巡检"),
  );
}

async function loadPage(root, page) {
  if (page === "dashboard") return loadDashboard(root);
  if (page === "risks") return loadRiskList(root);
  if (page === "risk-detail") return loadRiskDetail(root);
  if (page === "capabilities") return loadCapabilities(root);
  if (page === "evolution") return loadEvolution(root);
  if (page === "experiences") return loadExperiences(root);
  if (page === "ai-runtime") {
    const target = root.querySelector("[data-runtime-info]");
    try {
      const { get } = await import("./api.js");
      const product = await get(root, "/product-info");
      if (target) {
        target.innerHTML = `<div><dt>Provider</dt><dd>${escapeHtml(product.llm_provider || "ollama")}</dd></div><div><dt>安全模式</dt><dd>${escapeHtml(product.security_mode || "READ_ONLY_TOOLS")}</dd></div><div><dt>数据源</dt><dd>${escapeHtml(product.data_mode || "MOCK")}</dd></div>`;
      }
    } catch (error) {
      if (target) target.innerHTML = `<div><dt>运行时状态</dt><dd>${escapeHtml(error.message || "暂时不可用")}</dd></div>`;
    }
  }
}

function setupRefresh(root, page, load) {
  root.querySelectorAll("[data-refresh]").forEach((button) => {
    button.addEventListener("click", () => load(root, page));
  });
  root.querySelector("[data-environment]")?.addEventListener("change", (event) => {
    root.dataset.environment = event.target.value;
    window.localStorage.setItem("inspection-environment", event.target.value);
    load(root, page);
  });
}

async function start() {
  const root = document.querySelector(".app-shell");
  if (!root) return;
  const page = root.dataset.page || "dashboard";
  showView(root, page);
  activateNavigation(root, page);
  const environment = window.localStorage.getItem("inspection-environment") || "";
  const picker = root.querySelector("[data-environment]");
  if (picker) {
    picker.value = environment;
    root.dataset.environment = environment;
  }
  initConversation(root);
  bindRiskActions(root);
  bindRiskFilters(root, () => loadRiskList(root));
  setupRefresh(root, page, loadPage);
  await loadPage(root, page);
}

start();
