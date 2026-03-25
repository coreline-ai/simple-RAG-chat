"""임베딩 캐시 — SQLite 기반

동일 텍스트의 중복 임베딩 요청을 방지한다.
모델명 + 텍스트를 키로 사용하여 모델 변경 시 캐시가 자동 무효화된다.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from app.config import settings

_CACHE_DB = Path(settings.chroma_persist_dir) / "embedding_cache.db"


class EmbeddingCache:
    """SQLite 기반 임베딩 캐시"""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or _CACHE_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, embedding TEXT)"
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._hits = 0
        self._misses = 0

    def _key(self, text: str) -> str:
        raw = f"{settings.embedding_model}:{text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, text: str) -> list[float] | None:
        """캐시에서 임베딩 조회"""
        row = self._conn.execute(
            "SELECT embedding FROM cache WHERE key = ?",
            (self._key(text),),
        ).fetchone()
        if row:
            self._hits += 1
            return json.loads(row[0])
        self._misses += 1
        return None

    def put(self, text: str, embedding: list[float]) -> None:
        """임베딩 저장"""
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, embedding) VALUES (?, ?)",
            (self._key(text), json.dumps(embedding)),
        )
        self._conn.commit()

    def get_batch(self, texts: list[str]) -> dict[int, list[float]]:
        """배치 캐시 조회 — {인덱스: 임베딩} 반환"""
        hits: dict[int, list[float]] = {}
        for i, text in enumerate(texts):
            cached = self.get(text)
            if cached is not None:
                hits[i] = cached
        return hits

    def put_batch(self, texts: list[str], embeddings: list[list[float]]) -> None:
        """배치 캐시 저장"""
        for text, emb in zip(texts, embeddings):
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, embedding) VALUES (?, ?)",
                (self._key(text), json.dumps(emb)),
            )
        self._conn.commit()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self._hits / total * 100:.1f}%" if total > 0 else "N/A",
        }

    def clear(self) -> None:
        self._conn.execute("DELETE FROM cache")
        self._conn.commit()
        self._hits = 0
        self._misses = 0

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()
        return row[0] if row else 0


# 글로벌 캐시 인스턴스
_cache: EmbeddingCache | None = None


def get_cache() -> EmbeddingCache:
    global _cache
    if _cache is None:
        _cache = EmbeddingCache()
    return _cache
