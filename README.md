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

环境：Windows、Python 3.11 x64。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
.\.venv\Scripts\python.exe scripts/generate_demo_data.py
.\.venv\Scripts\python.exe scripts/ingest.py
.\.venv\Scripts\python.exe scripts/search.py --user-id readonly-demo --query "如何处理服务异常"
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

本版本是本地工程 Demo。代码与自动化检查可以证明权限、路由、人工门禁和幂等合同；不能证明真实国企部署、生产 IAM、真实用户数据、800+ 日任务量、Milvus/PostgreSQL/Redis 集群、GUI 或用户验收。

## 许可证

项目代码使用 [MIT License](LICENSE)。第三方依赖沿用各自许可证。
