# Publish IaaS Inspection Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 IaaS 智能巡检平台开发基线整理为可公开浏览的 GitHub 仓库，并发布 `v0.1.0` tag 和 Release。

**Architecture:** 保留现有 Django 最小骨架、依赖清单和两份中文设计文档，只补充根目录项目介绍。GitHub 仓库使用 `underthedeepsea/iaas-inspection-platform`，默认公开，远端 `main` 与本地发布 tag 保持一致。

**Tech Stack:** Python 3.10.x、Django 4.2.16、Django REST Framework 3.15.x、Airflow 2.3.2、LangGraph 1.2.10、LangChain 1.3.14、PostgreSQL 14.x、Ollama、pytest。

**Spec:** `设计文档/IaaS智能巡检平台_详细设计文档_v1.md`

## Global Constraints

- 项目版本固定为 `0.1.0`，Git tag 使用 `v0.1.0`。
- GitHub 仓库名固定为 `iaas-inspection-platform`，仓库描述使用 README 的一句话定位。
- 不新增运行时依赖，不修改现有设计文档内容。
- 保留开始任务前已有的 `设计文档/IaaS智能巡检平台_详细设计文档_v1.md` 未提交改动，不将其加入本次发布提交。
- 不提交 `.env`、密钥、数据库密码或本地虚拟环境。

---

### Task 1: 补充项目介绍与发布计划

**Files:**
- Create: `README.md`
- Create: `docs/superpowers/plans/2026-08-25-publish-iaas-inspection.md`

**Interfaces:**
- Produces: GitHub 首页可直接阅读的项目定位、技术栈、目录、运行检查命令和安全边界。

- [x] **Step 1: 写入 README**

  README 只描述当前已存在的骨架与文档，不把尚未实现的生产能力写成已完成能力。

- [x] **Step 2: 写入本计划**

  计划记录仓库名、版本、发布边界和验证命令，便于后续维护者复现本次发布。

### Task 2: 验证本地发布基线

**Files:**
- Verify: `README.md`
- Verify: `VERSION`
- Verify: `tests/test_version_constraints.py`

**Interfaces:**
- Consumes: Task 1 的 README 和现有 Django 配置。
- Produces: 可复核的工作区状态、测试结果和版本号。

- [ ] **Step 1: 检查文档格式与版本**

```bash
git diff --check
test "$(tr -d '[:space:]' < VERSION)" = "0.1.0"
```

- [ ] **Step 2: 运行基线测试**

```bash
python -m pytest -q
python manage.py check
```

  如果当前环境缺少依赖，记录实际缺少的包，不修改依赖版本来绕过问题。

- [ ] **Step 3: 创建发布提交**

```bash
git add README.md docs/superpowers/plans/2026-08-25-publish-iaas-inspection.md
git commit -m "docs: prepare v0.1.0 public baseline"
git tag -a v0.1.0 -m "Release v0.1.0"
```

  只暂存本任务创建的文件，保留预先存在的设计文档未提交改动。

### Task 3: 创建 GitHub 仓库并推送代码

**Files:**
- Remote: `underthedeepsea/iaas-inspection-platform`

**Interfaces:**
- Consumes: Task 2 的发布提交和 `v0.1.0` tag。
- Produces: 远端仓库描述、`main` 分支和 `v0.1.0` tag。

- [ ] **Step 1: 创建公开仓库并设置描述**

```bash
gh repo create underthedeepsea/iaas-inspection-platform \
  --public \
  --description "Code-first、AI-on-demand 的自进化 IaaS 巡检平台开发基线"
```

- [ ] **Step 2: 配置远端并推送**

```bash
git remote add origin https://github.com/underthedeepsea/iaas-inspection-platform.git
git push -u origin main
git push origin v0.1.0
```

### Task 4: 创建并复核 GitHub Release

**Files:**
- Remote: GitHub Release `v0.1.0`

**Interfaces:**
- Consumes: 远端 `main` 与 `v0.1.0` tag。
- Produces: 标题为 `v0.1.0 · IaaS 智能巡检平台开发基线` 的 Release。

- [ ] **Step 1: 创建 Release**

```bash
gh release create v0.1.0 \
  --repo underthedeepsea/iaas-inspection-platform \
  --title "v0.1.0 · IaaS 智能巡检平台开发基线" \
  --notes "首个开发基线。包含 Django 最小运行骨架、固定依赖约束、版本测试、产品详细设计文档和开发实施文档。当前阶段使用模拟数据，尚未接入真实 Prometheus、Kubernetes、CMDB、日志平台，也不包含生产写操作。"
```

- [ ] **Step 2: 复核远端对象**

```bash
gh repo view underthedeepsea/iaas-inspection-platform
gh release view v0.1.0 --repo underthedeepsea/iaas-inspection-platform
git ls-remote --tags origin v0.1.0
```
