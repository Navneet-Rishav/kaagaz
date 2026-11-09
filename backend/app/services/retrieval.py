"""Keyword retrieval over a document's chunks, behind a small interface so embeddings (pgvector) can be added later.

1. Postgres full-text search with the 'simple' config (no stemming; Devanagari is tokenised on whitespace),
   OR-ing keywords in both Hindi and English.
2. If that finds nothing: pg_trgm word similarity (tolerates typos and OCR noise), or ILIKE where the
   extension is not installed (the bundled local test Postgres).
"""

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

# Devanagari letters and signs, but not the danda (।, U+0964) or double danda (॥, U+0965): those are punctuation.
_TOKEN = re.compile(r"[\wऀ-ॣ०-ॿ]+", re.UNICODE)


@dataclass
class Hit:
    chunk_id: int
    page: int
    text: str
    score: float


class Retriever(Protocol):
    def search(self, db: Session, document_id: str, keywords: list[str], k: int = 5) -> list[Hit]: ...


def clean_keywords(keywords: list[str]) -> list[str]:
    out: list[str] = []
    for kw in keywords:
        toks = _TOKEN.findall(kw.lower())
        if toks:
            out.append(" ".join(toks))
    return list(dict.fromkeys(out))[:12]


_trgm_cache: dict[str, bool] = {}


def has_trgm(db: Session) -> bool:
    url = str(db.get_bind().url)
    if url not in _trgm_cache:
        _trgm_cache[url] = bool(db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).first())
    return _trgm_cache[url]


class KeywordRetriever:
    def search(self, db: Session, document_id: str, keywords: list[str], k: int = 5) -> list[Hit]:
        kws = clean_keywords(keywords)
        if not kws:
            return []
        # websearch_to_tsquery: quoted multi-word keywords become phrases; OR joins alternatives.
        query = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in kws)
        rows = db.execute(
            text(
                """
                SELECT id, page, text, ts_rank_cd(tsv, q) AS score
                FROM chunks, websearch_to_tsquery('simple', :q) AS q
                WHERE document_id = :doc AND tsv @@ q
                ORDER BY score DESC, idx
                LIMIT :k
                """
            ),
            {"q": query, "doc": document_id, "k": k},
        ).all()
        if not rows:
            rows = self._fuzzy(db, document_id, kws, k)
        return [Hit(chunk_id=r[0], page=r[1], text=r[2], score=float(r[3])) for r in rows]

    def _fuzzy(self, db: Session, document_id: str, kws: list[str], k: int):
        params: dict = {"doc": document_id, "k": k}
        if has_trgm(db):
            terms = []
            for i, kw in enumerate(kws):
                params[f"w{i}"] = kw
                terms.append(f"word_similarity(:w{i}, text)")
            score = f"GREATEST({', '.join(terms)})"
            sql = f"SELECT id, page, text, {score} AS score FROM chunks WHERE document_id = :doc AND {score} >= 0.5 ORDER BY score DESC, idx LIMIT :k"
        else:
            terms = []
            for i, kw in enumerate(kws):
                params[f"w{i}"] = f"%{kw}%"
                terms.append(f"(CASE WHEN text ILIKE :w{i} THEN 1 ELSE 0 END)")
            score = " + ".join(terms)
            sql = f"SELECT id, page, text, ({score})::float AS score FROM chunks WHERE document_id = :doc AND ({score}) > 0 ORDER BY score DESC, idx LIMIT :k"
        return db.execute(text(sql), params).all()


retriever: Retriever = KeywordRetriever()
