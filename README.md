# Enterprise Service Desk Agent

面向政企内部服务台的 Agent 工程演进项目。它不是单纯的工单审批系统：先检索制度与知识、判断问题类型、查询服务状态；只有确实需要写入工单时，才进入权限校验、人工审批和幂等建单。

> 当前标签：`v0.1.0-rag-service-desk`  
> 履历对应阶段：2024 Q4（代码与 Git 提交在当前日期重新整理，不伪造历史提交时间）

## 当前版本实现

- 单 Agent 的 RAG 检索与引用返回。
- `user_id -> role -> visibility` 的查询阶段权限过滤。
- `get_service_status` 只读查询。
- LangGraph 中断/恢复：`create_ticket` 执行前必须人工确认。
- SQLite 检查点和幂等键，降低重复建单风险。
- 全部数据均为本地虚构数据，不连接真实政企系统。

## 为什么不是“只做审批”

典型问题会先分流：

1. 制度、操作方法、常见故障：知识检索后直接回答，不建单。
2. 已知服务异常：查询服务状态后解释，不重复建单。
3. 无法自助解决且满足建单条件：生成工单草案，人工确认后才写入。
4. 权限不足或身份未知：拒绝调用，不进入审批。

## 四阶段路线

| 标签 | 履历对应阶段 | 本阶段新增能力 |
| --- | --- | --- |
| `v0.1.0-rag-service-desk` | 2024 Q4 | 单 Agent、RAG 引用、权限过滤、状态查询、人工审批建单 |
| `v0.2.0-mcp-pilot` | 2025 H1 | 用当时可用的官方 MCP Python SDK 暴露只读工具 |
| `v0.3.0-a2a-poc` | 2025 H2 | 独立诊断 Agent 的 Agent Card、任务状态、结果与失败回传 |
| `v1.0.0-multi-agent` | 2026 | 调度、知识、诊断、工单、审计 Agent 协作与工程治理 |

每个标签都是可检出的真实代码状态，不把后续能力倒灌到前一版本。

## 快速开始

环境：Windows x64、Python 3.10.11。依赖与 API 口径冻结在 2024-12-31；后续标签仅作为路线说明，不倒灌到本版本。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
.\.venv\Scripts\python.exe scripts/generate_demo_data.py
.\.venv\Scripts\python.exe scripts/ingest.py
.\.venv\Scripts\python.exe scripts/search.py --user-id readonly-demo --query "如何处理服务异常"
```

测试（不会下载模型；若未创建冻结环境，不要安装依赖后宣称已通过）：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_v01_contracts tests.test_v01_rag_flow -v
```

启动可能需要人工审批的工作流：

```powershell
.\.venv\Scripts\python.exe scripts/demo.py start --thread-id demo-001 --user-id support-demo --query "为 smart-assist 创建工单" --product-id smart-assist --idempotency-key demo-001
.\.venv\Scripts\python.exe scripts/demo.py resume --thread-id demo-001 --decision approve
```

## 代码导航

- `src/auth/context.py`：可信演示身份与权限上下文。
- `src/retrieval/chroma_store.py`：带 visibility 过滤的检索。
- `src/tools/platform_tools.py`：状态查询与幂等建单工具。
- `src/agent/workflow.py`：LangGraph 编排、人工复核和断点恢复。
- `src/eval/`：检索、工作流与故障评测入口。

## 证据边界

本版本是 Windows x64 上的本地、脱敏、虚构数据 Demo：单 Agent、RAG、LangGraph 人工门禁和本地 SQLite/Chroma；不包含 MCP、A2A 或多 Agent 协作。代码与自动化检查只能证明静态合同和聚焦检查覆盖的权限、路由、引用去重、人工门禁与幂等路径；不能证明生产部署、生产 IAM、真实用户/业务数据、真实外部服务、800+ 日任务量、Milvus/PostgreSQL/Redis 集群、GUI、设备路径或用户验收。依赖安装、模型下载和服务/API 验证需在明确的冻结环境中单独完成。

## 许可证

项目代码使用 [MIT License](LICENSE)。第三方依赖沿用各自许可证。
