"""Prepare a deterministic, closed T2Retrieval retrieval-evaluation subset."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import random
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import pyarrow.parquet as parquet


SOURCE_REPO = "mteb/T2Retrieval"
SOURCE_URL = "https://huggingface.co/datasets/mteb/T2Retrieval"
REVISION = "921dd3af6e78d1ae7ee0368aa8d7eaee02c8f08e"
LICENSE = "Apache-2.0"
SOURCE_LAST_MODIFIED_UTC = "2025-05-03T20:40:51Z"
MAX_RAW_BYTES = 200 * 1024 * 1024
FILES = {
    "corpus": "corpus/dev-00000-of-00001.parquet",
    "qrels": "data/dev-00000-of-00001.parquet",
    "queries": "queries/dev-00000-of-00001.parquet",
}
LOCAL_NAMES = {"corpus": "corpus-dev.parquet", "qrels": "qrels-dev.parquet", "queries": "queries-dev.parquet"}
RAW_FILES = {
    "corpus": {"bytes": 156879982, "sha256": "8f0400530c6ba664e580e2ae7bb5ed41a908b8abc17c3b3934f42cc65992ac1e"},
    "qrels": {"bytes": 1149414, "sha256": "c4c6ffd715faf151e0832a26dfcf2d7ec1edc17d9620a9aa99e721cc2436d7d2"},
    "queries": {"bytes": 817540, "sha256": "186b4d0a13cc4d8339eccfc6d465d1b2d4d1f6572defa8d39f3c8da3b66b0210"},
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _json_request(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def _metadata() -> dict:
    url = f"https://huggingface.co/api/datasets/{SOURCE_REPO}/revision/{REVISION}"
    metadata = _json_request(url)
    if metadata.get("sha") != REVISION:
        raise RuntimeError("remote revision did not match the frozen revision")
    if metadata.get("id") != SOURCE_REPO:
        raise RuntimeError("unexpected dataset identity")
    return metadata


def _expected_sizes(metadata: dict) -> dict[str, int]:
    sizes = {
        item["config_name"]: int(item["download_size"])
        for item in metadata["cardData"]["dataset_info"]
    }
    expected = {"corpus": sizes["corpus"], "qrels": sizes["default"], "queries": sizes["queries"]}
    total = sum(expected.values())
    if expected != {key: spec["bytes"] for key, spec in RAW_FILES.items()}:
        raise RuntimeError("remote file sizes did not match the frozen revision metadata")
    if total > MAX_RAW_BYTES or max(expected.values()) > MAX_RAW_BYTES:
        raise RuntimeError(f"planned download exceeds the 200 MiB safety limit: {total} bytes")
    return expected


def _resolve_project_path(root: Path, value: Path, label: str) -> Path:
    root = root.resolve()
    resolved = value.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"{label} must resolve inside the project root")
    return resolved


def _valid_raw_file(path: Path, spec: dict) -> bool:
    return path.is_file() and path.stat().st_size == spec["bytes"] and _sha256(path) == spec["sha256"]


def _check_download_budget(expected: dict[str, int], existing: dict[str, int]) -> None:
    planned = sum(expected.values())
    current_valid = sum(existing.values())
    missing = planned - current_valid
    if planned > MAX_RAW_BYTES or current_valid + missing > MAX_RAW_BYTES:
        raise RuntimeError("download budget exceeded before network access")


def _download_file(url: str, path: Path, spec: dict, opener: object = urllib.request.urlopen) -> None:
    part = path.with_name(path.name + ".part")
    part.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
        with opener(request, timeout=60) as response, part.open("wb") as handle:
            total = 0
            while chunk := response.read(1024 * 1024):
                if total + len(chunk) > spec["bytes"]:
                    raise RuntimeError(f"response exceeds expected size for {url}")
                handle.write(chunk)
                total += len(chunk)
        if not _valid_raw_file(part, spec):
            raise RuntimeError(f"size or SHA-256 mismatch for {url}")
        part.replace(path)
    except Exception:
        part.unlink(missing_ok=True)
        raise


def _download_raw(raw_dir: Path) -> tuple[dict[str, Path], dict[str, int]]:
    paths = {key: raw_dir / LOCAL_NAMES[key] for key in FILES}
    expected = {key: spec["bytes"] for key, spec in RAW_FILES.items()}
    existing = {key: spec["bytes"] for key, spec in RAW_FILES.items() if _valid_raw_file(paths[key], spec)}
    if len(existing) == len(paths):
        return paths, expected
    metadata = _metadata()
    expected = _expected_sizes(metadata)
    _check_download_budget(expected, existing)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for key, filename in FILES.items():
        path = paths[key]
        spec = RAW_FILES[key]
        if _valid_raw_file(path, spec):
            continue
        url = f"https://huggingface.co/datasets/{SOURCE_REPO}/resolve/{REVISION}/{filename}"
        _download_file(url, path, spec)
    return paths, expected


def _rows(path: Path) -> list[dict]:
    return parquet.read_table(path).to_pylist()


def _identifier(value: object, label: str) -> str:
    if value is None:
        raise ValueError(f"empty {label}")
    text = str(value).strip()
    if not text:
        raise ValueError(f"empty {label}")
    return text


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"empty {label}")
    return value


def build_subset(
    query_rows: Iterable[dict],
    qrel_rows: Iterable[dict],
    corpus_rows: Iterable[dict],
    *,
    query_count: int = 60,
    corpus_size: int = 3000,
    seed: int = 202409,
) -> tuple[list[dict], list[dict]]:
    if query_count <= 0 or corpus_size <= 0:
        raise ValueError("query_count and corpus_size must be positive")
    queries: dict[str, str] = {}
    for row in query_rows:
        query_id = _identifier(row.get("_id"), "query_id")
        question = _text(row.get("text"), "question")
        if query_id in queries:
            raise ValueError(f"duplicate query_id: {query_id}")
        queries[query_id] = question

    corpus: dict[str, str] = {}
    for row in corpus_rows:
        doc_id = _identifier(row.get("_id"), "doc_id")
        text = _text(row.get("text"), "document text")
        if doc_id in corpus:
            raise ValueError(f"duplicate doc_id: {doc_id}")
        corpus[doc_id] = text

    qrels: dict[str, set[str]] = defaultdict(set)
    seen_qrels: set[tuple[str, str]] = set()
    for row in qrel_rows:
        query_id = _identifier(row.get("query-id"), "qrel query_id")
        doc_id = _identifier(row.get("corpus-id"), "qrel doc_id")
        if query_id not in queries or doc_id not in corpus:
            raise ValueError("qrel references an unknown query or document")
        pair = (query_id, doc_id)
        if pair in seen_qrels:
            raise ValueError("duplicate qrel")
        seen_qrels.add(pair)
        if int(row.get("score", 0)) > 0:
            qrels[query_id].add(doc_id)

    candidates = sorted((query_id, queries[query_id]) for query_id in queries if qrels.get(query_id))
    if len(candidates) < query_count:
        raise ValueError("not enough queries with non-empty qrels")
    chosen = sorted(random.Random(seed).sample(candidates, query_count))
    expected_by_query = {query_id: sorted(qrels[query_id]) for query_id, _ in chosen}
    required_ids = {doc_id for ids in expected_by_query.values() for doc_id in ids}
    if len(required_ids) > corpus_size:
        raise ValueError("relevant document closure exceeds corpus_size")

    missing = required_ids - corpus.keys()
    if missing:
        raise ValueError(f"missing relevant documents: {sorted(missing)[:3]}")

    selected_ids = set(required_ids)
    distractors = [doc_id for doc_id in sorted(corpus) if doc_id not in required_ids]
    random.Random(seed ^ 0x5EED).shuffle(distractors)
    selected_ids.update(distractors[: corpus_size - len(selected_ids)])
    if len(selected_ids) != corpus_size:
        raise ValueError("corpus does not contain enough documents")
    corpus_out = [{"doc_id": doc_id, "text": corpus[doc_id]} for doc_id in sorted(selected_ids)]
    eval_out = [
        {"query_id": query_id, "question": question, "expected_doc_ids": expected_by_query[query_id]}
        for query_id, question in chosen
    ]
    return corpus_out, eval_out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, writer: object) -> None:
    part = _write_part(path, writer)
    try:
        part.replace(path)
    except Exception:
        part.unlink(missing_ok=True)
        raise


def _write_part(path: Path, writer: object) -> Path:
    part = path.with_name(path.name + ".part")
    part.unlink(missing_ok=True)
    try:
        writer(part)
        return part
    except Exception:
        part.unlink(missing_ok=True)
        raise


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    _atomic_write(path, lambda part: _dump_jsonl(part, rows))


def _write_json(path: Path, value: object) -> None:
    _atomic_write(path, lambda part: _dump_json(part, value))


def _dump_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _dump_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _manifest(raw_manifest: list[dict], corpus: list[dict], evaluation: list[dict], *, query_count: int, corpus_size: int, seed: int) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "source": {"repo": SOURCE_REPO, "url": SOURCE_URL, "revision": REVISION, "license": LICENSE},
        "source_last_modified_utc": SOURCE_LAST_MODIFIED_UTC,
        "generated_at_utc": now,
        "parameters": {"query_count": query_count, "corpus_size": corpus_size, "seed": seed},
        "raw_files": raw_manifest,
        "outputs": {"corpus_count": len(corpus), "query_count": len(evaluation)},
        "subset_not_official_full_benchmark": True,
        "evaluation_boundary": "T2Retrieval Demo Subset; retrieval only, not the official full T2Ranking score",
    }


def _stage_outputs(output_dir: Path, corpus: list[dict], evaluation: list[dict], raw_manifest: list[dict], expected_bytes: int, *, query_count: int, corpus_size: int, seed: int) -> tuple[dict[str, Path], dict[str, Path]]:
    paths = {name: output_dir / filename for name, filename in {"corpus": "corpus.jsonl", "eval": "eval.json", "manifest": "manifest.json"}.items()}
    parts: dict[str, Path] = {}
    try:
        parts["corpus"] = _write_part(paths["corpus"], lambda part: _dump_jsonl(part, corpus))
        parts["eval"] = _write_part(paths["eval"], lambda part: _dump_json(part, evaluation))
        manifest = _manifest(raw_manifest, corpus, evaluation, query_count=query_count, corpus_size=corpus_size, seed=seed)
        manifest["raw_download_bytes_expected"] = expected_bytes
        manifest["content_files"] = {
            name: {"bytes": part.stat().st_size, "sha256": _sha256(part)}
            for name, part in (("corpus", parts["corpus"]), ("eval", parts["eval"]))
        }
        parts["manifest"] = _write_part(paths["manifest"], lambda part: _dump_json(part, manifest))
        return paths, parts
    except Exception:
        for part in parts.values():
            part.unlink(missing_ok=True)
        raise


def _commit_output_group(paths: dict[str, Path], parts: dict[str, Path], replace: object = Path.replace) -> None:
    try:
        paths["manifest"].unlink(missing_ok=True)
        replace(parts["corpus"], paths["corpus"])
        replace(parts["eval"], paths["eval"])
        replace(parts["manifest"], paths["manifest"])
    except Exception:
        for part in parts.values():
            part.unlink(missing_ok=True)
        raise


def prepare(args: argparse.Namespace) -> None:
    root = PROJECT_ROOT
    raw_dir = _resolve_project_path(root, Path(args.raw_dir) if args.raw_dir else root / "data/external/t2retrieval/raw", "raw_dir")
    output_dir = _resolve_project_path(root, Path(args.output_dir) if args.output_dir else root / "data/external/t2retrieval/subset", "output_dir")
    paths, expected = _download_raw(raw_dir)
    corpus, evaluation = build_subset(
        _rows(paths["queries"]),
        _rows(paths["qrels"]),
        _rows(paths["corpus"]),
        query_count=args.query_count,
        corpus_size=args.corpus_size,
        seed=args.seed,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_manifest = []
    for key, path in paths.items():
        raw_manifest.append({"name": key, "filename": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    final_paths, parts = _stage_outputs(output_dir, corpus, evaluation, raw_manifest, sum(expected.values()), query_count=args.query_count, corpus_size=args.corpus_size, seed=args.seed)
    _commit_output_group(final_paths, parts)
    print(json.dumps({"corpus": len(corpus), "queries": len(evaluation), "output_dir": str(output_dir)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-count", type=int, default=60)
    parser.add_argument("--corpus-size", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=202409)
    parser.add_argument("--raw-dir")
    parser.add_argument("--output-dir")
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
