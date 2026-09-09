"""Parse, embed, persist, and search the fictional knowledge documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from src.config import PROJECT_PATHS, PROJECT_ROOT
from src.data_schema import KnowledgeDocument, Visibility

# Project cache variables are set by src.config before these imports.
import chromadb
from sentence_transformers import SentenceTransformer


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
COLLECTION_NAME = "zhida-knowledge-v1"
CHROMA_PATH = PROJECT_PATHS["runtime"] / "chroma"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
CHUNK_LIMIT = 400
FRONT_MATTER_FIELDS = ("doc_id", "title", "category", "visibility", "product_id")


@dataclass(frozen=True)
class ParsedDocument:
    document: KnowledgeDocument
    source_file: str


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    text: str
    chunk_index: int
    document: KnowledgeDocument
    source_file: str

    @property
    def metadata(self) -> dict[str, str | int]:
        return {
            "doc_id": self.document.doc_id,
            "title": self.document.title,
            "category": self.document.category,
            "visibility": self.document.visibility.value,
            "product_id": self.document.product_id,
            "source_file": self.source_file,
            "chunk_index": self.chunk_index,
        }


@dataclass(frozen=True)
class SearchResult:
    rank: int
    chunk_id: str
    doc_id: str
    title: str
    category: str
    visibility: str
    product_id: str
    source_file: str
    score: float
    text: str


def parse_markdown(path: Path, project_root: Path = PROJECT_ROOT) -> ParsedDocument:
    path = path.resolve()
    project_root = project_root.resolve()
    try:
        source_file = path.relative_to(project_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"知识文档必须位于项目根目录内：{path}") from exc

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"缺少固定 front matter：{source_file}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"front matter 未闭合：{source_file}") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if ": " not in line:
            raise ValueError(f"front matter 行格式错误：{source_file}")
        key, value = line.split(": ", 1)
        if key in metadata:
            raise ValueError(f"front matter 字段重复：{key}")
        metadata[key] = value
    if set(metadata) != set(FRONT_MATTER_FIELDS):
        missing = sorted(set(FRONT_MATTER_FIELDS) - set(metadata))
        extra = sorted(set(metadata) - set(FRONT_MATTER_FIELDS))
        raise ValueError(f"front matter 字段不符合合同，缺失={missing}，额外={extra}")

    body = "\n".join(lines[end + 1 :]).strip()
    document = KnowledgeDocument(
        doc_id=metadata["doc_id"],
        title=metadata["title"],
        category=metadata["category"],
        visibility=Visibility(metadata["visibility"]),
        product_id=metadata["product_id"],
        content=body,
    )
    return ParsedDocument(document=document, source_file=source_file)


def chunk_document(parsed: ParsedDocument, limit: int = CHUNK_LIMIT) -> tuple[TextChunk, ...]:
    if limit < 1:
        raise ValueError("分块上限必须为正整数。")
    paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n", parsed.document.content)]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if not paragraph:
            continue
        if len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            pieces = [paragraph[index : index + limit] for index in range(0, len(paragraph), limit)]
            chunks.extend(pieces[:-1])
            current = pieces[-1]
            continue

        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph

    if current:
        chunks.append(current)

    return tuple(
        TextChunk(
            chunk_id=f"{parsed.document.doc_id}:{index:04d}",
            text=text,
            chunk_index=index,
            document=parsed.document,
            source_file=parsed.source_file,
        )
        for index, text in enumerate(chunks)
    )


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    return SentenceTransformer(
        MODEL_NAME,
        revision=MODEL_REVISION,
        device="cpu",
    )


def _embed(texts: list[str]) -> list[list[float]]:
    embeddings = _load_model().encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embeddings.astype("float32", copy=False).tolist()


def _require_cosine_collection(collection: object) -> None:
    configuration = getattr(collection, "configuration", {})
    hnsw = configuration.get("hnsw") if isinstance(configuration, dict) else None
    if not isinstance(hnsw, dict) or hnsw.get("space") != "cosine":
        raise ValueError("Chroma collection 必须使用 cosine 距离空间，请更换空的运行目录后重新入库。")


def ingest(
    knowledge_dir: Path = PROJECT_PATHS["data"] / "knowledge",
    chroma_path: Path = CHROMA_PATH,
) -> dict[str, object]:
    paths = sorted(knowledge_dir.resolve().glob("*.md"))
    if not paths:
        raise ValueError(f"未找到知识文档：{knowledge_dir}")
    parsed = tuple(parse_markdown(path) for path in paths)
    chunks = tuple(chunk for document in parsed for chunk in chunk_document(document))
    if not chunks:
        raise ValueError("知识文档没有可入库正文。")

    chroma_path = chroma_path.resolve()
    chroma_path.mkdir(parents=True, exist_ok=True)
    with chromadb.PersistentClient(path=str(chroma_path)) as client:
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            configuration={"hnsw": {"space": "cosine"}},
            embedding_function=None,
        )
        _require_cosine_collection(collection)
        collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[chunk.metadata for chunk in chunks],
            embeddings=_embed([chunk.text for chunk in chunks]),
        )
        chunk_count = collection.count()
    return {
        "collection": COLLECTION_NAME,
        "model_revision": MODEL_REVISION,
        "document_count": len(parsed),
        "chunk_count": chunk_count,
        "chroma_path": str(chroma_path),
    }


def _allowed_values(allowed_visibilities: Iterable[Visibility | str]) -> tuple[str, ...]:
    try:
        values = tuple(dict.fromkeys(Visibility(value).value for value in allowed_visibilities))
    except (TypeError, ValueError) as exc:
        raise ValueError("allowed_visibilities 只能包含 public、support 或 admin。") from exc
    if not values:
        raise ValueError("allowed_visibilities 不得为空。")
    return values


def search(
    query: str,
    allowed_visibilities: Iterable[Visibility | str],
    top_k: int = 5,
    chroma_path: Path = CHROMA_PATH,
) -> tuple[SearchResult, ...]:
    if not isinstance(query, str) or not (cleaned_query := query.strip()):
        raise ValueError("query 不得为空。")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ValueError("top_k 必须是 1-20 的整数。")
    allowed = _allowed_values(allowed_visibilities)
    where = {"visibility": {"$in": list(allowed)}}

    with chromadb.PersistentClient(path=str(chroma_path.resolve())) as client:
        collection = client.get_collection(name=COLLECTION_NAME, embedding_function=None)
        _require_cosine_collection(collection)
        response = collection.query(
            query_embeddings=_embed([QUERY_INSTRUCTION + cleaned_query]),
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    ids = response["ids"][0]
    documents = response["documents"][0]
    metadatas = response["metadatas"][0]
    distances = response["distances"][0]

    results: list[SearchResult] = []
    for rank, (chunk_id, text, metadata, distance) in enumerate(
        zip(ids, documents, metadatas, distances, strict=True), start=1
    ):
        visibility = str(metadata["visibility"])
        if visibility not in allowed:
            raise AssertionError("Chroma 返回了权限过滤范围之外的结果。")
        results.append(
            SearchResult(
                rank=rank,
                chunk_id=chunk_id,
                doc_id=str(metadata["doc_id"]),
                title=str(metadata["title"]),
                category=str(metadata["category"]),
                visibility=visibility,
                product_id=str(metadata["product_id"]),
                source_file=str(metadata["source_file"]),
                score=1.0 - float(distance),
                text=text,
            )
        )
    return tuple(results)
