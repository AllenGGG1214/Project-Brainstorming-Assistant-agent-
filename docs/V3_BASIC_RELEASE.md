# V3 基础版交付与上线指南

日期：2026-09-12。本次是在现有 `v2/` 应用内增量升级；目录名保留，避免破坏部署路径。完整 V3 设计见 [V3_DESIGN.md](V3_DESIGN.md)。

## 已实现范围

- LangGraph StateGraph 包含五个具名生成节点、版本保存节点、审批 interrupt 和 ACCEPT/GO/PIVOT/STOP 终止分支。
- 为每次阶段生成建立独立持久化 thread。保留逐阶段手动生成体验；接受后不自动调用下一阶段模型。
- PostgreSQL 使用官方 PostgresSaver；本地 SQLite 使用 SqliteSaver，两者都将 checkpoint 保存到当前数据库。
- 生成输入与模型配置快照、结果记录、审批命令持久化。候选版本提交幂等，审批命令与业务审批共享事务。
- API 进程内调度器每 5 秒检查排队任务与过期租约；正常工作每 15 秒续租，默认租约 60 秒。后台请求和恢复调度通过同一租约避免重复领取。
- 重启后复用已保存结果。外部调用已开始但结果未知时，标为需要手动重试，不自动重新消费 API。
- 现有阶段门禁、版本历史、账号隔离、原型沙箱和 ZIP 导出保留。V2 项目从下一次阶段生成开始使用新引擎，不伪造旧 checkpoint。
- 前端显示已保存/等待审批状态、更新运行状态轮询，以及已保存版本的工作流同步重试。

关键代码：`v2/backend/app/orchestration/runner.py`、`v2/backend/app/db.py`、`v2/backend/app/main.py`。

## 明确边界

本次没有三路并行搜索、独立 worker、暂停/取消按钮、运行级费用预算、RAG 或复杂 Agent 协作。这些属于完整 MVP。当前调度器适用于邀请制、低流量部署；API 休眠或停止时不执行工作，醒来后重新检查。重启时未过期租约最长需等待约 60 秒。

Checkpoint 与业务提交不是同一个事务，靠结果记录与幂等提交对账。基础版按整个阶段记录 Provider 调用：研究搜索与综合报告之间若崩溃而尚未保存完整结果，仍需手动重试；不声称能恢复到研究内部每次 API 调用。

本次测试不调用真实模型。真实 API 生成、搜索质量、费用和 5–10 个 Ideas 的评估仍待验证。尚未推送或部署到线上；现有线上站点不会因本地修改自动更新。

## 本地运行

重新运行 `v2/setup.ps1` 安装更新后的锁定依赖，然后按现有 `v2/start.ps1` 启动。默认 `WORKFLOW_ENGINE=langgraph`，无需改动用户操作流程。

环境变量 `WORKFLOW_ENGINE=v2` 只让新生成回到旧引擎；已有 V3 任务仍运行恢复调度。旧的在途 V2 生成重启后继续沿用原先“失败后手动重试”的行为。

## Render 上线步骤

1. 上线前备份 PostgreSQL；保留当前可回滚提交，并避免带着正在生成的旧 V2 请求切换。
   Free Tier 不支持控制台导出，可在本机 `v2/.env` 设置 External Database URL，然后从 `v2/backend` 执行 `../.venv/Scripts/python.exe backup_database.py`。脚本将 custom archive 和 SHA-256 清单保存在被 Git 忽略的 `v2/data/backups/`，校验 archive catalog，但不会自动恢复到测试库。
2. 推送经评审的代码后，使用更新后的 `requirements.lock.txt` 构建 API 服务。
3. 启动命令保持 `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`。迁移 `0002` 增加 graph_jobs，不改变历史版本内容。
4. 设置 `WORKFLOW_ENGINE=langgraph`（Blueprint 已包含）。API 启动时官方 saver.setup() 创建 checkpoint 表/索引；数据库账号需要相应 DDL 权限。
5. 部署前端，并用测试账号完成 Demo 五阶段、刷新、GO/PIVOT/STOP、导出。
6. 用一个真实测试 Idea 检查 Live 搜索与生成；确认 API 用量后再开放 Beta 用户。
7. 验证任务中途 API 重启后，已提交版本未重复，未知调用没有自动重试。

出现异常先设置 `WORKFLOW_ENGINE=v2` 停止新的 V3 生成，保留 checkpoint 与 graph_jobs 表。若必须回滚旧代码，先排空/停止 V3 任务；旧代码不了解 V3 恢复规则，不能保证安全接管。不要直接删除 checkpoint 表或执行 0002 downgrade 来回滚功能。

## 验证命令

```powershell
cd v2/backend
../.venv/Scripts/python.exe -m pytest -q
# Optional: isolated test database only; tests clear graph_jobs/runs/artifacts.
$env:TEST_DATABASE_URL='postgresql://test-user@127.0.0.1:55439/test-db'
../.venv/Scripts/python.exe -m pytest -q
```

前端运行 `pnpm typecheck` 与 `pnpm build`。数据库迁移可用隔离 PostgreSQL 实例验证从 0001 升级至 0002。Checkpoint 是用户数据的一部分，必须与业务数据库一起备份；未来增加项目删除功能时也必须清理对应 checkpoint。

实现参考：[LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。
