# Changelog

本仓库按能力出现顺序重建技术演进。标签创建时间保持真实；“履历对应阶段”只用于说明当时项目能力，不代表 Git 历史提交日期。

## v0.2.0-mcp-pilot — 履历对应 2025 H1

- 采用官方 `mcp==1.9.4`（2025-06-12 发布）的 FastMCP/stdin-stdout 能力。
- 仅注册 `get_service_status`，继续复用服务端可信身份映射。
- 明确不经 MCP 暴露 `create_ticket`，保留人工审批边界。

## v0.1.0-rag-service-desk — 履历对应 2024 Q4

- 建立单 Agent RAG 服务台底座。
- 增加查询阶段权限过滤、引用、服务状态查询。
- 增加 LangGraph 人工复核、SQLite 检查点和幂等建单。
