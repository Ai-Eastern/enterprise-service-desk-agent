# Enterprise Service Desk Agent

一个面向政企内部服务台的 Agent 工程演进项目：从 RAG 单 Agent 底座，逐步演进到 MCP 工具接入、A2A 跨 Agent 验证和多 Agent 协作。

它不是单纯的工单审批系统。系统先理解问题并分流：知识类问题检索后回答，状态类问题交给诊断 Agent，只有确实需要写入工单时才触发权限校验、人工审批和幂等写入。

> 当前标签：**v1.0.0-multi-agent**
> 履历对应阶段：2026
> Git 说明：四个阶段均在当前日期重新整理为真实提交和标签，没有伪造历史提交日期。

## 最终版本实现了什么

- **triage**：判断任务进入知识、诊断还是工单路径。
- **knowledge**：执行带 visibility 过滤的 RAG 检索并返回引用。
- **diagnostic**：复用服务状态只读工具；历史 v0.3 中用 A2A 任务模型验证状态和失败回传。
- **ticket**：复用 LangGraph 检查点；建单前中断，只有授权角色人工确认后才能恢复。
- **audit**：记录参与 Agent、动作、结果和分段耗时，并创建 OpenTelemetry span。
- FastAPI：提供任务提交、人工审批恢复和健康检查接口。
- MCP：本地 stdio 仅注册 get_service_status，不暴露 create_ticket。
- 生产适配边界：为 Milvus 元数据过滤、PostgreSQL 幂等记录和 Redis 任务状态提供窄接口。

## 四阶段技术演进

| 标签 | 履历对应阶段 | 关键增量 | 当时没有什么 |
| --- | --- | --- | --- |
| v0.1.0-rag-service-desk | 2024 Q4 | 单 Agent、RAG 引用、权限过滤、状态查询、人工审批建单 | 无 MCP、无 A2A、无多 Agent |
| v0.2.0-mcp-pilot | 2025 H1 | 官方 mcp==1.9.4，通过 stdio 暴露唯一只读工具 | 建单不经 MCP；无 A2A |
| v0.3.0-a2a-poc | 2025 H2 | 官方 a2a-sdk==0.3.6，Agent Card、任务状态、结果与失败回传 | 仅本地 PoC，未宣称生产互操作 |
| v1.0.0-multi-agent | 2026 | 五类 Agent 协作、FastAPI、追踪、生产中间件适配边界 | 未接真实政企业务系统或生产集群 |

当前 v1.0 使用 2026 可安装的维护线 mcp==2.2.0 与 a2a-sdk==1.1.2；历史标签保留当时可用的 SDK pin。详见 [版本演进说明](docs/版本演进.md)。

## 业务流程

~~~text
用户问题
  -> triage
     -> knowledge -> RAG + 权限过滤 -> 带引用回答
     -> diagnostic -> 只读服务状态 -> 诊断结果
     -> ticket -> LangGraph 中断 -> 人工批准/拒绝 -> 幂等建单
  -> audit + OpenTelemetry trace
~~~

不需要建单的情况包括：知识库已有明确答案、已知服务异常正在处理中、用户只查询状态、问题不满足建单条件，或身份/权限校验失败。

## 快速开始

环境：Windows、Python 3.11 x64。所有演示数据都是本地虚构数据。

~~~powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
.\.venv\Scripts\python.exe scripts/generate_demo_data.py
.\.venv\Scripts\python.exe scripts/ingest.py
.\.venv\Scripts\python.exe scripts/multi_agent_demo.py
~~~

启动 FastAPI：

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn src.api:app --host 127.0.0.1 --port 8000
~~~

启动 MCP stdio 服务：

~~~powershell
.\.venv\Scripts\python.exe -m src.mcp_server
~~~

运行自动化测试：

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
~~~

查看任一历史阶段：

~~~powershell
git switch --detach v0.1.0-rag-service-desk
git switch --detach v0.2.0-mcp-pilot
git switch --detach v0.3.0-a2a-poc
git switch main
~~~

## API 示例

提交状态查询不需要人工审批：

~~~json
POST /v1/tasks
{
  "thread_id": "demo-001",
  "user_id": "readonly-demo",
  "query": "查询 smart-assist 服务状态",
  "product_id": "smart-assist",
  "idempotency_key": "demo-001"
}
~~~

如果 query 明确要求报修或建单，响应会停在 LangGraph 人工复核点。授权角色再调用：

~~~json
POST /v1/tasks/demo-002/approval
{
  "user_id": "support-demo",
  "approved": true
}
~~~

## 代码导航

- src/agents/service_desk.py：多 Agent 调度、人工门禁与审计轨迹。
- src/api.py：FastAPI 对接边界。
- src/auth/context.py：可信演示身份与权限上下文。
- src/retrieval/chroma_store.py：本地 Chroma 检索和 visibility 过滤。
- src/tools/platform_tools.py：状态查询与幂等建单。
- src/agent/workflow.py：LangGraph 中断、恢复与 SQLite 检查点。
- src/mcp_server.py：MCP 本地 stdio 只读适配器。
- src/a2a_poc.py：A2A 0.3 历史 PoC 的任务模型，当前 SDK 通过兼容层运行。
- src/infrastructure/production_adapters.py：Milvus/PostgreSQL/Redis 适配边界。
- src/eval/：检索、工作流和故障评测入口。

## 履历口径与证据边界

仓库可以支撑这些表述：

- 设计 RAG、权限上下文、工具 Schema、人工复核、幂等与故障处理。
- 分阶段完成 MCP 只读工具试点、A2A 任务模型验证和多 Agent 编排。
- 提供 FastAPI、中间件适配边界、OpenTelemetry span 和自动化测试。

仓库当前不能单独证明：

- 真实国企生产部署、生产 IAM 或真实用户数据。
- 日均 800+ 次真实任务量；若写入履历，应另有压测报告并明确是模拟容量测试还是生产统计。
- Milvus/PostgreSQL/Redis 真实集群联调、容灾和性能验收。
- 第三方 MCP/A2A 客户端生态兼容、GUI、发布或用户验收。

## 许可证

项目代码使用 [MIT License](LICENSE)。MCP Python SDK 为 MIT；A2A Python SDK 为 Apache-2.0；其余第三方依赖沿用各自许可证。
