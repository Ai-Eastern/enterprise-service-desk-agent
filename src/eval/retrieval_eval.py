"""Deterministic retrieval evaluation for the frozen T2Retrieval subset."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.config import PROJECT_ROOT

# Reuse the project BGE embedding and Chroma configuration after src.config.
from src.retrieval.chroma_store import (
    MODEL_REVISION,
    QUERY_INSTRUCTION,
    _embed,
    _require_cosine_collection,
)

import chromadb


EXPECTED_SOURCE_REVISION = "921dd3af6e78d1ae7ee0368aa8d7eaee02c8f08e"
EXPECTED_QUERY_COUNT = 60
EXPECTED_CORPUS_COUNT = 3000
TOP_K = 5
SUBSET_DIR = PROJECT_ROOT / "data" / "external" / "t2retrieval" / "subset"
EVAL_ROOT = PROJECT_ROOT / "runtime" / "eval" / "t2retrieval"
EVAL_CHROMA_PATH = EVAL_ROOT / "chroma"
REPORT_PATH = EVAL_ROOT / "report.json"
COLLECTION_NAME = "t2retrieval-demo-v1"


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    text: str


@dataclass(frozen=True)
class EvalQuery:
    query_id: str
    question: str
    expected_doc_ids: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalDataset:
    corpus: tuple[CorpusDocument, ...]
    queries: tuple[EvalQuery, ...]
    source_revision: str
    corpus_sha256: str
    eval_sha256: str


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 不能为空。")
    return value.strip()


def _project_path(path: Path, project_root: Path) -> Path:
    resolved = path.resolve()
    root = project_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("评测路径必须位于项目根目录内。")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_corpus(path: Path) -> tuple[CorpusDocument, ...]:
    documents: list[CorpusDocument] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise ValueError(f"corpus.jsonl 第 {line_number} 行为空。")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"corpus.jsonl 第 {line_number} 行格式错误。") from exc
            if not isinstance(row, dict):
                raise ValueError(f"corpus.jsonl 第 {line_number} 行必须是对象。")
            doc_id = _nonempty(row.get("doc_id"), "doc_id")
            text = _nonempty(row.get("text"), "text")
            if doc_id in seen:
                raise ValueError(f"corpus.jsonl 存在重复 doc_id：{doc_id}")
            seen.add(doc_id)
            documents.append(CorpusDocument(doc_id, text))
    if not documents:
        raise ValueError("corpus.jsonl 不能为空。")
    return tuple(documents)


def _read_queries(path: Path, corpus_ids: set[str]) -> tuple[EvalQuery, ...]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("eval.json 无法读取。") from exc
    if not isinstance(rows, list) or not rows:
        raise ValueError("eval.json 必须是非空数组。")
    queries: list[EvalQuery] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("eval.json 每项必须是对象。")
        query_id = _nonempty(row.get("query_id"), "query_id")
        question = _nonempty(row.get("question"), "question")
        expected = row.get("expected_doc_ids")
        if not isinstance(expected, list) or not expected:
            raise ValueError(f"query {query_id} 的 expected_doc_ids 不能为空。")
        expected_ids = tuple(_nonempty(value, "expected_doc_id") for value in expected)
        if len(set(expected_ids)) != len(expected_ids):
            raise ValueError(f"query {query_id} 的 expected_doc_ids 存在重复。")
        unknown = sorted(set(expected_ids) - corpus_ids)
        if unknown:
            raise ValueError(f"query {query_id} 引用了未知文档。")
        if query_id in seen:
            raise ValueError(f"eval.json 存在重复 query_id：{query_id}")
        seen.add(query_id)
        queries.append(EvalQuery(query_id, question, expected_ids))
    return tuple(queries)


def _validate_manifest(
    manifest: object,
    corpus_path: Path,
    eval_path: Path,
    expected_counts: tuple[int, int],
) -> tuple[str, str, str]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json 必须是对象。")
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("revision") != EXPECTED_SOURCE_REVISION:
        raise ValueError("T2Retrieval source revision 不符合冻结合同。")
    if manifest.get("subset_not_official_full_benchmark") is not True:
        raise ValueError("评测数据必须明确标记为非官方完整 benchmark。")

    query_count, corpus_count = expected_counts
    parameters = manifest.get("parameters")
    outputs = manifest.get("outputs")
    if not isinstance(parameters, dict) or not isinstance(outputs, dict):
        raise ValueError("manifest.json 缺少规模字段。")
    if (
        parameters.get("query_count") != query_count
        or parameters.get("corpus_size") != corpus_count
        or outputs.get("query_count") != query_count
        or outputs.get("corpus_count") != corpus_count
    ):
        raise ValueError("manifest.json 规模与评测合同不一致。")

    content_files = manifest.get("content_files")
    if not isinstance(content_files, dict):
        raise ValueError("manifest.json 缺少 content_files。")
    actual = {"corpus": corpus_path, "eval": eval_path}
    hashes: dict[str, str] = {}
    for name, path in actual.items():
        expected = content_files.get(name)
        if not isinstance(expected, dict):
            raise ValueError(f"manifest.json 缺少 {name} 内容校验。")
        digest = _sha256(path)
        if expected.get("sha256") != digest or expected.get("bytes") != path.stat().st_size:
            raise ValueError(f"{name} 内容未通过 manifest 校验。")
        hashes[name] = digest
    return str(source["revision"]), hashes["corpus"], hashes["eval"]


def load_subset(
    subset_dir: Path = SUBSET_DIR,
    *,
    expected_counts: tuple[int, int] = (EXPECTED_QUERY_COUNT, EXPECTED_CORPUS_COUNT),
    project_root: Path = PROJECT_ROOT,
) -> RetrievalDataset:
    subset_dir = _project_path(Path(subset_dir), Path(project_root))
    corpus_path = subset_dir / "corpus.jsonl"
    eval_path = subset_dir / "eval.json"
    manifest_path = subset_dir / "manifest.json"
    if not all(path.is_file() for path in (corpus_path, eval_path, manifest_path)):
        raise ValueError("评测 subset 文件不完整。")
    corpus = _read_corpus(corpus_path)
    queries = _read_queries(eval_path, {document.doc_id for document in corpus})
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest.json 无法读取。") from exc
    revision, corpus_sha256, eval_sha256 = _validate_manifest(
        manifest, corpus_path, eval_path, expected_counts
    )
    if len(corpus) != expected_counts[1] or len(queries) != expected_counts[0]:
        raise ValueError("评测 subset 实际规模不符合冻结合同。")
    return RetrievalDataset(corpus, queries, revision, corpus_sha256, eval_sha256)


def _validate_top_k(top_k: int) -> None:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ValueError("top_k 必须是 1-20 的整数。")


def dedupe_doc_ids(ranked_doc_ids: Iterable[str], top_k: int = TOP_K) -> list[str]:
    _validate_top_k(top_k)
    unique: list[str] = []
    seen: set[str] = set()
    for doc_id in ranked_doc_ids:
        if doc_id not in seen:
            seen.add(doc_id)
            unique.append(doc_id)
        if len(unique) == top_k:
            break
    return unique


def score_query(
    query_id: str,
    ranked_doc_ids: Iterable[str],
    expected_doc_ids: Iterable[str],
    *,
    top_k: int = TOP_K,
) -> dict[str, object]:
    ranked = dedupe_doc_ids(ranked_doc_ids, top_k)
    expected = set(expected_doc_ids)
    first_hit_rank = next(
        (rank for rank, doc_id in enumerate(ranked, start=1) if doc_id in expected),
        None,
    )
    return {
        "query_id": query_id,
        "ranked_doc_ids": ranked,
        "first_hit_rank": first_hit_rank,
        "hit": first_hit_rank is not None,
        "reciprocal_rank": 0.0 if first_hit_rank is None else 1.0 / first_hit_rank,
    }


def build_report(
    queries: Sequence[EvalQuery],
    rankings: Mapping[str, Sequence[str]],
    *,
    model_revision: str,
) -> dict[str, object]:
    if not queries:
        raise ValueError("评测 query 不能为空。")
    scored = [
        score_query(query.query_id, rankings.get(query.query_id, ()), query.expected_doc_ids)
        for query in queries
    ]
    hit_queries = sum(bool(item["hit"]) for item in scored)
    reciprocal_total = sum(float(item["reciprocal_rank"]) for item in scored)
    return {
        "source_revision": EXPECTED_SOURCE_REVISION,
        "model_revision": model_revision,
        "collection": COLLECTION_NAME,
        "subset_not_official_full_benchmark": True,
        "evaluation_boundary": (
            "60 queries / 3000 documents subset; retrieval only; "
            "not official full benchmark; not permission/tool evaluation; "
            "not enterprise/government RAG quality."
        ),
        "total_queries": len(scored),
        "hit_queries": hit_queries,
        "hit_at_5": round(hit_queries / len(scored), 8),
        "mrr": round(reciprocal_total / len(scored), 8),
        "failed_query_ids": [item["query_id"] for item in scored if not item["hit"]],
        "queries": [
            {
                "query_id": item["query_id"],
                "ranked_doc_ids": item["ranked_doc_ids"],
                "first_hit_rank": item["first_hit_rank"],
            }
            for item in scored
        ],
    }


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part_path = path.with_name(path.name + ".part")
    part_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(part_path, path)


def _collection(client: object, corpus_sha256: str):
    metadata = {
        "corpus_sha256": corpus_sha256,
        "model_revision": MODEL_REVISION,
        "source_revision": EXPECTED_SOURCE_REVISION,
    }
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        configuration={"hnsw": {"space": "cosine"}},
        metadata=metadata,
        embedding_function=None,
    )
    _require_cosine_collection(collection)
    current_metadata = collection.metadata or {}
    if any(current_metadata.get(key) != value for key, value in metadata.items()):
        raise ValueError("评测 collection 元数据不匹配，已拒绝复用。")
    return collection


def run_evaluation(
    subset_dir: Path = SUBSET_DIR,
    *,
    chroma_path: Path = EVAL_CHROMA_PATH,
    report_path: Path = REPORT_PATH,
    top_k: int = TOP_K,
) -> dict[str, object]:
    if top_k != TOP_K:
        raise ValueError("本评测只接受 top_k=5。")
    dataset = load_subset(subset_dir)
    chroma_path = _project_path(Path(chroma_path), PROJECT_ROOT)
    report_path = _project_path(Path(report_path), PROJECT_ROOT)
    chroma_path.mkdir(parents=True, exist_ok=True)

    with chromadb.PersistentClient(path=str(chroma_path)) as client:
        collection = _collection(client, dataset.corpus_sha256)
        count = collection.count()
        if count not in (0, len(dataset.corpus)):
            raise ValueError("评测 collection 数量不匹配，已拒绝复用。")
        if count == 0:
            embeddings = _embed([document.text for document in dataset.corpus])
            collection.upsert(
                ids=[document.doc_id for document in dataset.corpus],
                documents=[document.text for document in dataset.corpus],
                metadatas=[{"doc_id": document.doc_id} for document in dataset.corpus],
                embeddings=embeddings,
            )
        rankings: dict[str, Sequence[str]] = {}
        for query in dataset.queries:
            response = collection.query(
                query_embeddings=_embed([QUERY_INSTRUCTION + query.question]),
                n_results=TOP_K,
                include=["metadatas"],
            )
            rankings[query.query_id] = tuple(
                str(metadata["doc_id"])
                for metadata in response["metadatas"][0]
            )
        collection_count = collection.count()

    report = build_report(dataset.queries, rankings, model_revision=MODEL_REVISION)
    report.update(
        {
            "corpus_count": collection_count,
            "manifest_corpus_sha256": dataset.corpus_sha256,
            "manifest_eval_sha256": dataset.eval_sha256,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    _write_report(report_path, report)
    return report
