"""Narrow Milvus, PostgreSQL, and Redis adapter boundaries for enterprise wiring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

import psycopg
import redis
from pymilvus import MilvusClient

from src.data_schema import Visibility


def build_visibility_filter(values: Iterable[Visibility | str]) -> str:
    """Build a Milvus filter only from the closed visibility enum."""

    allowed = tuple(dict.fromkeys(Visibility(value).value for value in values))
    if not allowed:
        raise ValueError("visibility filter must not be empty")
    quoted = ", ".join(f'"{value}"' for value in allowed)
    return f"visibility in [{quoted}]"


@dataclass(frozen=True)
class MilvusKnowledgeRepository:
    uri: str
    collection_name: str
    token: str | None = None

    def search(
        self,
        query_vector: list[float],
        allowed_visibilities: Iterable[Visibility | str],
        limit: int = 5,
    ) -> list[dict[str, object]]:
        client = MilvusClient(uri=self.uri, token=self.token)
        return client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            filter=build_visibility_filter(allowed_visibilities),
            limit=limit,
            output_fields=["doc_id", "title", "source_file", "visibility", "text"],
        )[0]


@dataclass(frozen=True)
class PostgresIdempotencyRepository:
    dsn: str

    def reserve(self, idempotency_key: str, ticket_id: str) -> str:
        """Insert once and return the original ticket ID on retries."""

        statement = """
            INSERT INTO ticket_idempotency (idempotency_key, ticket_id)
            VALUES (%s, %s)
            ON CONFLICT (idempotency_key)
            DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
            RETURNING ticket_id
        """
        with psycopg.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, (idempotency_key, ticket_id))
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("idempotency reservation returned no ticket")
        return str(row[0])


@dataclass(frozen=True)
class RedisTaskStateRepository:
    url: str
    ttl_seconds: int = 3600

    def save(self, task_id: str, payload: dict[str, object]) -> None:
        client = redis.Redis.from_url(self.url, decode_responses=True)
        client.setex(f"service-desk:task:{task_id}", self.ttl_seconds, json.dumps(payload))

    def load(self, task_id: str) -> dict[str, object] | None:
        client = redis.Redis.from_url(self.url, decode_responses=True)
        payload = client.get(f"service-desk:task:{task_id}")
        return None if payload is None else json.loads(payload)
