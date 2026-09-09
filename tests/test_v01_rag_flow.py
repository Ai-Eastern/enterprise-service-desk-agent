from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data_schema import Visibility
from src.retrieval import chroma_store
from src.retrieval.chroma_store import SearchResult


def _embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [float(value) / 255.0 for value in digest[:8]]


def _retrieval(*doc_ids: str) -> tuple[SearchResult, ...]:
    return tuple(
        SearchResult(
            rank=index,
            chunk_id=f"{doc_id}:0000",
            doc_id=doc_id,
            title=f"标题 {doc_id}",
            category="FAQ",
            visibility="public",
            product_id="smart-assist",
            source_file=f"data/knowledge/{doc_id}.md",
            score=0.9,
            text=f"{doc_id} 的虚构演示规则。",
        )
        for index, doc_id in enumerate(doc_ids, 1)
    )


class V01RagFlowTest(unittest.TestCase):
    def test_ingest_and_visibility_filtered_search(self) -> None:
        with tempfile.TemporaryDirectory(dir=chroma_store.PROJECT_ROOT) as root:
            root_path = Path(root)
            knowledge = root_path / "knowledge"
            knowledge.mkdir()
            documents = (
                ("public-guide", "公开指南", "public"),
                ("support-guide", "客服指南", "support"),
                ("admin-guide", "管理员指南", "admin"),
            )
            for doc_id, title, visibility in documents:
                (knowledge / f"{doc_id}.md").write_text(
                    "---\n"
                    f"doc_id: {doc_id}\n"
                    f"title: {title}\n"
                    "category: FAQ\n"
                    f"visibility: {visibility}\n"
                    "product_id: smart-assist\n"
                    "---\n\n"
                    f"{title} 的虚构演示内容。\n",
                    encoding="utf-8",
                )
            chroma_path = root_path / "chroma"
            with patch.object(chroma_store, "_embed", side_effect=lambda texts: [_embedding(text) for text in texts]):
                report = chroma_store.ingest(knowledge, chroma_path)
                results = chroma_store.search(
                    "虚构演示内容",
                    (Visibility.PUBLIC, Visibility.SUPPORT),
                    top_k=3,
                    chroma_path=chroma_path,
                )

            self.assertEqual(report["document_count"], 3)
            self.assertTrue(results)
            self.assertTrue({result.visibility for result in results} <= {"public", "support"})
            self.assertNotIn("admin-guide", {result.doc_id for result in results})

    def test_status_and_ticket_approval_resume(self) -> None:
        from src.agent import workflow

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            checkpoint = root_path / "checkpoints.sqlite"
            tickets = root_path / "tickets.sqlite"
            status_result = {"product_id": "smart-assist", "status_message": "服务运行正常"}
            with patch.object(workflow, "search", return_value=_retrieval("public-guide")), patch.object(
                workflow, "get_service_status", return_value=status_result
            ) as get_status:
                result = workflow.start_workflow(
                    thread_id="status-001",
                    user_id="readonly-demo",
                    query="查询服务状态",
                    product_id="smart-assist",
                    idempotency_key="status-001",
                    checkpoint_path=checkpoint,
                    tickets_path=tickets,
                    chroma_path=root_path / "unused-chroma",
                )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["tool_result"], status_result)
            get_status.assert_called_once()

            with patch.object(workflow, "search", return_value=_retrieval("public-guide", "public-guide")), patch.object(
                workflow, "create_ticket", return_value={"ticket_id": "ticket-001", "reused": False}
            ) as create:
                interrupted = workflow.start_workflow(
                    thread_id="ticket-001",
                    user_id="support-demo",
                    query="为 smart-assist 创建工单",
                    product_id="smart-assist",
                    idempotency_key="ticket-001",
                    checkpoint_path=checkpoint,
                    tickets_path=tickets,
                    chroma_path=root_path / "unused-chroma",
                )
                self.assertEqual(interrupted["status"], "interrupted")
                self.assertEqual(interrupted["interrupt"]["action"], "create_ticket")
                create.assert_not_called()
                resumed = workflow.resume_workflow(
                    thread_id="ticket-001", approved=True, checkpoint_path=checkpoint
                )

            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(resumed["tool_result"]["ticket_id"], "ticket-001")
            create.assert_called_once()

    def test_readonly_ticket_denial_does_not_write(self) -> None:
        from src.agent import workflow

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            tickets = root_path / "tickets.sqlite"
            with patch.object(workflow, "search", return_value=_retrieval("public-guide")), patch.object(
                workflow, "create_ticket"
            ) as create:
                result = workflow.start_workflow(
                    thread_id="readonly-001",
                    user_id="readonly-demo",
                    query="为 smart-assist 创建工单",
                    product_id="smart-assist",
                    idempotency_key="readonly-001",
                    checkpoint_path=root_path / "checkpoints.sqlite",
                    tickets_path=tickets,
                    chroma_path=root_path / "unused-chroma",
                )

            self.assertEqual(result["status"], "completed")
            self.assertIn("无权", result["answer"])
            create.assert_not_called()
            self.assertFalse(tickets.exists())

    def test_reject_has_deduplicated_citations_and_no_write(self) -> None:
        from src.agent import workflow

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            checkpoint = root_path / "checkpoints.sqlite"
            tickets = root_path / "tickets.sqlite"
            with patch.object(workflow, "search", return_value=_retrieval("public-guide", "public-guide")), patch.object(
                workflow, "create_ticket"
            ) as create:
                interrupted = workflow.start_workflow(
                    thread_id="reject-001",
                    user_id="support-demo",
                    query="为 smart-assist 创建工单",
                    product_id="smart-assist",
                    idempotency_key="reject-001",
                    checkpoint_path=checkpoint,
                    tickets_path=tickets,
                    chroma_path=root_path / "unused-chroma",
                )
                self.assertEqual(interrupted["status"], "interrupted")
                result = workflow.resume_workflow(
                    thread_id="reject-001", approved=False, checkpoint_path=checkpoint
                )

            self.assertEqual(result["status"], "completed")
            self.assertIn("人工复核已拒绝", result["answer"])
            self.assertEqual([citation["doc_id"] for citation in result["citations"]], ["public-guide"])
            create.assert_not_called()
            self.assertFalse(tickets.exists())


if __name__ == "__main__":
    unittest.main()
