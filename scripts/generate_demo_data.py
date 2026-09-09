"""Generate deterministic fictional demo data using only the standard library."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import PROJECT_PATHS
from src.data_schema import EvaluationCase, EvalTool, KnowledgeDocument, PermissionResult, Product, Visibility


PRODUCT_FIELDS = ("product_id", "name", "service_status", "status_message")
TICKET_FIELDS = (
    "ticket_id",
    "idempotency_key",
    "created_at",
    "role",
    "product_id",
    "summary",
    "status",
)
EVAL_FILENAME = "project_eval.json"

PRODUCTS = (
    Product(
        "smart-assist",
        "智达科技智能助手（虚构演示产品）",
        "operational",
        "智达科技虚构演示状态：服务运行正常。",
    ),
    Product(
        "knowledge-hub",
        "智达科技知识中心（虚构演示产品）",
        "degraded",
        "智达科技虚构演示状态：部分检索响应较慢。",
    ),
    Product(
        "service-console",
        "智达科技服务控制台（虚构演示产品）",
        "maintenance",
        "智达科技虚构演示状态：正在计划维护。",
    ),
)

DOCUMENTS = (
    KnowledgeDocument(
        "product-manual",
        "智达科技智能助手产品手册",
        "产品手册",
        Visibility.PUBLIC,
        "smart-assist",
        """# 智达科技智能助手产品手册

本文档及所述产品均为虚构演示数据。

智能助手提供知识查询、结果摘要和来源提示。用户应核对重要信息，不应把演示回答视为真实业务承诺。""",
    ),
    KnowledgeDocument(
        "service-terms",
        "智达科技演示服务条款",
        "服务条款",
        Visibility.PUBLIC,
        "smart-assist",
        """# 智达科技演示服务条款

本文档及全部条款均为虚构演示数据，不构成真实合同。

演示服务仅用于功能学习。使用者应避免提交个人信息、密钥或真实业务资料。""",
    ),
    KnowledgeDocument(
        "common-faq",
        "智达科技知识中心常见问题",
        "FAQ",
        Visibility.PUBLIC,
        "knowledge-hub",
        """# 智达科技知识中心常见问题

本文档及问答均为虚构演示数据。

## 为什么回答会附带来源？

来源提示用于展示回答依据，使用者仍需自行判断内容是否适用。""",
    ),
    KnowledgeDocument(
        "troubleshooting-guide",
        "智达科技知识中心故障处理",
        "故障处理",
        Visibility.SUPPORT,
        "knowledge-hub",
        """# 智达科技知识中心故障处理

本文档及故障场景均为虚构演示数据。

当检索响应较慢时，客服可先确认服务状态，再建议用户缩短问题并重试。不得要求用户提供密码或密钥。""",
    ),
    KnowledgeDocument(
        "support-playbook",
        "智达科技内部客服资料",
        "内部客服资料",
        Visibility.SUPPORT,
        "service-console",
        """# 智达科技内部客服资料

本文档、流程和角色均为虚构演示数据。

客服应先确认问题摘要与产品，再记录可复现步骤。涉及管理员权限的事项必须升级处理。""",
    ),
    KnowledgeDocument(
        "admin-operations",
        "智达科技管理员资料",
        "管理员资料",
        Visibility.ADMIN,
        "service-console",
        """# 智达科技管理员资料

本文档及管理流程均为虚构演示数据。

管理员变更服务状态前应复核影响范围并保留操作说明。演示资料不包含真实账号、地址或连接信息。""",
    ),
    KnowledgeDocument("smart-assist-setup", "智达科技智能助手配置手册", "产品手册", Visibility.PUBLIC, "smart-assist", """# 智达科技智能助手配置手册

本文档及配置步骤均为虚构演示数据。

首次使用时选择演示知识空间并保存偏好；配置变更只影响当前演示环境。"""),
    KnowledgeDocument("knowledge-hub-search", "智达科技知识中心检索说明", "产品手册", Visibility.PUBLIC, "knowledge-hub", """# 智达科技知识中心检索说明

本文档及检索规则均为虚构演示数据。

检索会按相关性返回来源文档，问题越具体越容易得到稳定结果。"""),
    KnowledgeDocument("service-console-overview", "智达科技服务控制台概览", "产品手册", Visibility.PUBLIC, "service-console", """# 智达科技服务控制台概览

本文档及控制台功能均为虚构演示数据。

控制台用于查看演示服务状态和处理流程，不提供真实生产操作能力。"""),
    KnowledgeDocument("account-faq", "智达科技账户常见问题", "FAQ", Visibility.PUBLIC, "smart-assist", """# 智达科技账户常见问题

本文档及账户问答均为虚构演示数据。

演示账户只用于本地测试；遇到配置疑问时可重新选择演示身份。"""),
    KnowledgeDocument("subscription-faq", "智达科技服务方案常见问题", "FAQ", Visibility.PUBLIC, "knowledge-hub", """# 智达科技服务方案常见问题

本文档及方案问答均为虚构演示数据。

演示方案不涉及真实计费，状态说明只用于验证查询和工具流程。"""),
    KnowledgeDocument("status-faq", "智达科技服务状态常见问题", "FAQ", Visibility.PUBLIC, "service-console", """# 智达科技服务状态常见问题

本文档及状态问答均为虚构演示数据。

服务状态分为运行、降级和维护三种演示状态，具体值以本地产品记录为准。"""),
    KnowledgeDocument("safety-faq", "智达科技安全使用常见问题", "服务条款", Visibility.PUBLIC, "smart-assist", """# 智达科技安全使用常见问题

本文档及安全问答均为虚构演示数据。

不要在演示查询中输入真实个人资料、密码、密钥或生产连接信息。"""),
    KnowledgeDocument("support-routing", "智达科技客服分流资料", "内部客服资料", Visibility.SUPPORT, "smart-assist", """# 智达科技客服分流资料

本文档、分流规则和角色均为虚构演示数据。

客服先按产品和问题类型分流；无法判断时保留原问题并升级处理。"""),
    KnowledgeDocument("support-escalation", "智达科技客服升级资料", "内部客服资料", Visibility.SUPPORT, "knowledge-hub", """# 智达科技客服升级资料

本文档、升级规则和角色均为虚构演示数据。

连续两次重试仍失败时，客服应记录时间、问题摘要和复现步骤，再请求升级。"""),
    KnowledgeDocument("support-diagnostics", "智达科技客服诊断资料", "故障处理", Visibility.SUPPORT, "knowledge-hub", """# 智达科技客服诊断资料

本文档、诊断步骤和故障均为虚构演示数据。

诊断顺序为确认服务状态、复核查询范围、记录响应现象，不要求用户提供秘密信息。"""),
    KnowledgeDocument("support-billing", "智达科技客服方案资料", "内部客服资料", Visibility.SUPPORT, "service-console", """# 智达科技客服方案资料

本文档、方案说明和客服角色均为虚构演示数据。

涉及演示方案的问题只说明本地状态，不承诺真实价格、额度或合同条款。"""),
    KnowledgeDocument("support-access", "智达科技客服访问资料", "服务条款", Visibility.SUPPORT, "smart-assist", """# 智达科技客服访问资料

本文档、访问流程和角色均为虚构演示数据。

客服只能使用已授权的演示范围；需要管理员操作时必须转交管理员。"""),
    KnowledgeDocument("support-incident", "智达科技客服事件资料", "故障处理", Visibility.SUPPORT, "service-console", """# 智达科技客服事件资料

本文档、事件记录和角色均为虚构演示数据。

事件摘要应保持简短、可复现并去除个人信息；处理完成后补充结果说明。"""),
    KnowledgeDocument("admin-users", "智达科技管理员用户资料", "管理员资料", Visibility.ADMIN, "service-console", """# 智达科技管理员用户资料

本文档、用户管理流程和角色均为虚构演示数据。

管理员变更演示身份权限前应核对请求范围，并记录变更原因。"""),
    KnowledgeDocument("admin-audit", "智达科技管理员审计资料", "管理员资料", Visibility.ADMIN, "knowledge-hub", """# 智达科技管理员审计资料

本文档、审计规则和角色均为虚构演示数据。

审计记录只保存演示操作摘要，不包含真实主体、凭据或外部地址。"""),
    KnowledgeDocument("admin-retention", "智达科技管理员保留资料", "服务条款", Visibility.ADMIN, "smart-assist", """# 智达科技管理员保留资料

本文档、保留规则和角色均为虚构演示数据。

演示数据按本地运行需要保留；清理前应确认不会影响当前复现。"""),
    KnowledgeDocument("admin-release", "智达科技管理员发布资料", "管理员资料", Visibility.ADMIN, "smart-assist", """# 智达科技管理员发布资料

本文档、发布流程和角色均为虚构演示数据。

发布演示配置前应检查版本标记和回滚说明，不触及真实生产环境。"""),
    KnowledgeDocument("admin-backup", "智达科技管理员备份资料", "故障处理", Visibility.ADMIN, "service-console", """# 智达科技管理员备份资料

本文档、备份流程和角色均为虚构演示数据。

本地备份只用于复现测试；恢复前应核对目标目录和演示数据版本。"""),
)


def _evaluation_cases() -> tuple[EvaluationCase, ...]:
    role_for_visibility = {
        Visibility.PUBLIC: "readonly",
        Visibility.SUPPORT: "support",
        Visibility.ADMIN: "admin",
    }
    knowledge = tuple(
        EvaluationCase(
            f"project-knowledge-{index:03d}",
            f"请说明{document.title}中的演示规则。",
            role_for_visibility[document.visibility],
            (document.doc_id,),
            EvalTool.NONE,
            PermissionResult.ALLOWED,
        )
        for index, document in enumerate(sorted(DOCUMENTS, key=lambda item: item.doc_id), 1)
    )
    statuses = tuple(
        EvaluationCase(
            f"project-status-{index:03d}",
            f"请查询{product.name}的演示服务状态。",
            ("readonly", "support", "admin")[(index - 1) % 3],
            (),
            EvalTool.GET_SERVICE_STATUS,
            PermissionResult.ALLOWED,
        )
        for index, product in enumerate(PRODUCTS * 4, 1)
    )
    allowed_tickets = tuple(
        EvaluationCase(
            f"project-ticket-allowed-{index:02d}",
            f"请为{product.name}记录一条虚构工单。",
            "support" if index <= 8 else "admin",
            (),
            EvalTool.CREATE_TICKET,
            PermissionResult.ALLOWED,
        )
        for index, product in enumerate((PRODUCTS * 6)[:16], 1)
    )
    denied_tickets = tuple(
        EvaluationCase(
            f"project-ticket-denied-{index:02d}",
            f"readonly 身份尝试为{product.name}创建工单。",
            "readonly",
            (),
            EvalTool.CREATE_TICKET,
            PermissionResult.DENIED,
        )
        for index, product in enumerate((PRODUCTS * 3)[:8], 1)
    )
    return knowledge + statuses + allowed_tickets + denied_tickets


EVALUATION_CASES = _evaluation_cases()


def _markdown(document: KnowledgeDocument) -> str:
    metadata = document.metadata
    front_matter = "\n".join(
        (
            "---",
            f"doc_id: {metadata['doc_id']}",
            f"title: {document.title}",
            f"category: {metadata['category']}",
            f"visibility: {metadata['visibility']}",
            f"product_id: {metadata['product_id']}",
            "---",
        )
    )
    return f"{front_matter}\n\n{document.content}\n"


def _write_csv(path: Path, fields: tuple[str, ...], rows: tuple[object, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in fields})


def _write_evaluation(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([case.as_dict() for case in EVALUATION_CASES], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def generate(output_dir: Path) -> tuple[Path, ...]:
    output_dir = output_dir.resolve()
    knowledge_dir = output_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for document in sorted(DOCUMENTS, key=lambda item: item.doc_id):
        path = knowledge_dir / f"{document.doc_id}.md"
        path.write_text(_markdown(document), encoding="utf-8", newline="\n")
        written.append(path)

    products_path = output_dir / "products.csv"
    _write_csv(products_path, PRODUCT_FIELDS, tuple(sorted(PRODUCTS, key=lambda item: item.product_id)))
    written.append(products_path)

    tickets_path = output_dir / "tickets.csv"
    _write_csv(tickets_path, TICKET_FIELDS, ())
    written.append(tickets_path)
    evaluation_path = output_dir / "eval" / EVAL_FILENAME
    _write_evaluation(evaluation_path)
    written.append(evaluation_path)
    return tuple(written)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成智达科技确定性虚构演示数据。")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_PATHS["data"],
        help="输出目录，默认使用项目内 data 目录。",
    )
    args = parser.parse_args()
    written = generate(args.output_dir)
    print(f"已生成 {len(written)} 个智达科技虚构演示数据文件：{args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
