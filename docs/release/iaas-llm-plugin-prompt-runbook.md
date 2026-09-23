# 推理性能插件与提示词发布运行说明

适用于[设计 v1](../插件系统/iaas_llm_plugin_prompt_design_v1.md)与[实施 v1](../插件系统/iaas_llm_plugin_prompt_implementation_v1.md)的增量升级。本文是操作顺序，不代表生产已经部署或验证。现有数据库必须保留；不能沿用旧 v0.2 文档的空库重建流程。

## 切换前

1. 记录当前部署 Git SHA、数据库迁移状态、策略文件和 Airflow DAG 配置；备份数据库。统计 Snapshot、Asset、InspectionItem、CheckResult、Risk、Evidence 和 CapabilityVersion，并保存演示插件对象清单。在 PostgreSQL 副本上先演练迁移与回填，核对这些数量和历史证据。
2. 暂停旧 `daily_iaas_inspection`，等待旧 Run 结束。旧任务会生成模拟数据，不能与真实来源的 Run 交错。
3. 部署应用时设置 `DEPLOY_COMMIT_SHA` 为**实际部署提交**。在服务端设置强随机 `PROMPT_ADMIN_TOKEN` 才启用提示词写入；缺省为空时写接口拒绝。管理员在浏览器临时输入，令牌不放进前端构建、浏览器持久存储或版本库。生产入口使用 TLS 和可信网关；公开 API 仍处于项目既有可信网络边界。
4. 检查 `config/inference_performance_policies.json` 中 `quality.max_age_seconds` 与 `quality.max_gap_seconds`。示例均为 300 秒；按上游真实采样频率及可接受延迟调整，避免把正常间隔判为过期或缺口。记录最终策略版本。

## 迁移与回填

在相同代码及配置的 PostgreSQL 副本先执行：

```sh
python manage.py showmigrations inference_performance inspections investigations
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py backfill_inference_assets --batch-size 500
```

`backfill_inference_assets` 默认 **dry-run**，只报告尚未关联 Asset 的快照数。核对环境、引擎 ID、类型和模型名的资产身份及预期数量后，才在副本执行 `python manage.py backfill_inference_assets --apply --batch-size 500`，重跑 dry-run 应为零。命令按主键分批、仅补快照 Asset 关联；不重算历史 evaluation，不造历史 Run 或插件版本。

副本验证通过后，在正式库按相同顺序执行 `migrate --plan`、`migrate --noinput`、dry-run、核对和 `--apply`。要求回填完成，或明确记录旧未关联数据的保留期及覆盖范围，再开放正式运行。迁移包含精确退役旧演示插件和提示词初始化。随后运行**新代码中的** `python manage.py seed_launch`，注册 `llm.performance_profile` 并绑定 `LLM_RUNTIME`；核对旧三项仍禁用。不能在回滚的旧提交上重跑旧 `seed_launch`，也不要在正式库运行 `seed_e2e_complete`。迁移后复核原有证据数量与关系，不能为通过检查删除旧数据。

## 真实数据与运行

1. 更新正式插件目录和策略配置，确认 `inference-performance` 注册版本可解析。真实采集端推送到 `POST /api/v1/inference-performance/snapshots` 或 `/batch`。Push 经注册处理器产生带插件 ID/版本、策略和质量信息的新评估；已有完成评估不会因查询或策略保存而重算。
2. 收到新版本的真实快照后，检查响应及引擎画像的 `plugin`、`quality`、`freshness`、`status` 和 `evaluation_status`。`UNKNOWN`、`IDLE`、过期或待确认不能当作恢复正常。Push 的即时状态与正式 Run 的 Risk 更新有不同时间点，监控时分别标记。
3. 手动运行一次真实 `LLM_RUNTIME` 巡检，核对冻结来源 `INFERENCE_SNAPSHOT`、CheckResult、Risk、复验与资源汇总。无活动插件应报告冲突；无资产/数据应报告无数据，不能产生空集合 `NORMAL`。
4. 将新 `airflow/dags/daily_iaas_inspection.py` 部署到 Airflow，仅在新代码、迁移和真实输入确认后恢复 DAG。Airflow 配置 `INSPECTION_API_BASE_URL`、`AIRFLOW_INTERNAL_TOKEN`、`INSPECTION_ENVIRONMENT_ID`，按需设置 `INSPECTION_DAG_SCHEDULE`。DAG 通过内部 HTTP 依次执行 create/freeze → execute → correlate → reverify → resource summaries → snapshot → complete；不再生成 mock dataset。实跑一次并核对 Run、检查结果、风险和阶段重试。
5. 经提示词管理页检查默认 `inspection-explanation`，用受保护写接口测试编辑、版本冲突及恢复默认；重跑 seed 不应覆盖已编辑文本。用真实 Qwen3.5-4B 验证首页解读和资源/Run 解读使用已保存提示词。模型故障不能改变 CODE 检查事实或风险。

## 验收证据与回滚

本地可执行 `python manage.py check`、`python manage.py makemigrations --check --dry-run`、`python -m pytest -q`；前端执行 `npm ci`、`npm test`、`npm run build`。需保留对应提交的 CI、数据库副本迁移、真实 Push、手动 Run、实际 Airflow HTTP Run、真实模型、历史数量对比和高数据量固定负载记录。代码测试不替代生产连接、迁移或吞吐验收；这些门禁未实际执行前状态仍为**未验证**。

故障时先暂停新 DAG 与输入切换，恢复上一稳定应用和策略配置，保留新增 nullable 字段、提示词表以及已产生的真实快照与证据，不做破坏性反向迁移。若回滚到旧提交，**旧 daily DAG 与旧 `seed_launch` 必须继续停用**，否则会重新制造演示结果。确认兼容的读取路径、备份和数据对账后再决定后续修复。
