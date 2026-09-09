# Enterprise Service Desk Agent

[![contract-tests](https://github.com/Ai-Eastern/enterprise-service-desk-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Ai-Eastern/enterprise-service-desk-agent/actions/workflows/ci.yml)

一个面向政企内部服务台的 Agent 工程演进项目：从 RAG 单 Agent 底座，逐步演进到 MCP 工具接入、A2A 跨 Agent 验证和多 Agent 协作。

它不是单纯的工单审批系统。系统先理解问题并分流：知识类问题检索后回答，状态类问题交给诊断 Agent，只有确实需要写入工单时才触发权限校验、人工审批和幂等写入。

> 当前发布：**v1.2.0-integration**（v1.0 多 Agent 能力的本地中间件联调与容量基线）
> 履历对应阶段：2026
> Git 说明：四个阶段均在当前日期重新整理为真实提交和标签，没有伪造历史提交日期。

GitHub Releases 保留四个阶段标签；后续修正使用普通补丁版本，不改写已发布标签。

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
| v1.1.0-evidence | 2026 | 100 条复合任务合同集、30 条故障注入集和机器可读报告 | 不等同于生产数据、容量或用户验收 |
| v1.2.0-integration | 2026 | PostgreSQL/Redis/Milvus 本地容器联调；1,000 条并发 ASGI 容量基线 | 不等同于生产拓扑、外部系统或生产压测 |

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

生成并复核公开证据包：

~~~powershell
.\.venv\Scripts\python.exe scripts/run_contract_suite.py
~~~

当前固定证据为 **100/100 条复合任务合同通过、30/30 条故障注入合同通过**。复合任务覆盖知识/状态/建单分流、请求 Schema、引用映射、权限和人工审批门禁；故障集覆盖未知身份、只读身份越权、诊断超时、中断恢复、重复执行和人工拒绝。机器可读结果见 [contract-report.json](docs/evidence/contract-report.json)。

这组结果是本地确定性合同证据，不是语义检索质量、真实政企业务联调、生产 IAM、容量压测或用户验收。完整 RAG 检索评测仍由 `src/eval/project_eval.py` 独立执行，避免把桩函数结果包装成真实检索成绩。

运行本地容量基线：

~~~powershell
.\.venv\Scripts\python.exe scripts/run_capacity_baseline.py
~~~

当前留档结果为 **1,000/1,000 条混合请求成功**，并发 20；400 条知识、300 条状态和 300 条建单前人工中断请求。吞吐与 P50/P95/P99 见 [capacity-baseline.json](docs/evidence/capacity-baseline.json)。这是进程内 ASGI 与确定性内存适配器的模拟容量基线，只能支撑“完成 800+ 任务量级的本地容量评估”，不能写成真实日均流量或生产压测。

运行本地中间件联调：

~~~powershell
docker compose -f compose.integration.yml up -d --wait
.\.venv\Scripts\python.exe scripts/run_integration_smoke.py
docker compose -f compose.integration.yml down
~~~

当前留档结果为 **3/3 项真实本地容器回环通过**：PostgreSQL 验证幂等键复用原工单 ID，Redis 验证带 TTL 的任务状态读写，Milvus 验证查询阶段 `visibility` 过滤只返回公开文档。Compose 复用固定版本的官方 PostgreSQL/Redis 镜像与 Milvus 官方 standalone 依赖结构，结果见 [integration-report.json](docs/evidence/integration-report.json)。这只能证明本机容器和真实客户端的一次有界联调，不证明生产高可用、备份、容灾、安全加固、持续负载或外部业务系统。

容器基线参考 [Milvus 官方 standalone Compose](https://milvus.io/docs/install_standalone-docker-compose.md)、[PostgreSQL Docker Official Image](https://hub.docker.com/_/postgres) 与 [Redis Docker Official Image](https://hub.docker.com/_/redis)；项目固定精确版本，避免 `latest` 漂移。

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
- 提供可重复生成的 100 条复合任务合同集与 30 条故障注入集，并保留机器可读结果。
- 完成 1,000 条混合请求的本地模拟容量基线，保留吞吐和 P50/P95/P99 延迟。

仓库当前不能单独证明：

- 真实国企生产部署、生产 IAM 或真实用户数据。
- 日均 800+ 次真实任务量；若写入履历，应另有压测报告并明确是模拟容量测试还是生产统计。
- Milvus/PostgreSQL/Redis 生产集群、容灾和性能验收；仓库只完成本地容器回环。
- 第三方 MCP/A2A 客户端生态兼容、GUI、发布或用户验收。

## 许可证

项目代码使用 [MIT License](LICENSE)。MCP Python SDK 为 MIT；A2A Python SDK 为 Apache-2.0；其余第三方依赖沿用各自许可证。
