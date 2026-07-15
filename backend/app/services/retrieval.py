"""资料检索：向量语义检索优先（配置 EMBEDDING_API_KEY 时），关键词打分兜底。"""
import json
import logging
import re
from dataclasses import dataclass
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Material, MaterialChunk
from . import embeddings
from .embeddings import EmbeddingUnavailableError

logger = logging.getLogger(__name__)

MAX_SCAN_CHUNKS = 3000


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    material_id: int
    material_name: str
    content: str
    score: float


def _load_rows(db: Session, course_id: int):
    return db.execute(
        select(MaterialChunk, Material.filename)
        .join(Material, Material.id == MaterialChunk.material_id)
        .where(MaterialChunk.course_id == course_id)
        .limit(MAX_SCAN_CHUNKS)
    ).all()


def search_chunks(
    db: Session, course_id: int, query: str, limit: int = 6
) -> list[RetrievedChunk]:
    """课程内检索：向量可用时按余弦相似度排序，否则退回关键词打分。"""
    rows = _load_rows(db, course_id)
    if embeddings.is_configured():
        try:
            hits = _vector_search(rows, query, limit)
            if hits:
                return hits
        except EmbeddingUnavailableError:
            logger.warning("向量检索失败，退回关键词检索")
    return _keyword_search(rows, query, limit)


# ---------------------------------------------------------------- 向量检索

def _vector_search(rows, query: str, limit: int) -> list[RetrievedChunk]:
    query_vec = embeddings.embed_texts([query])[0]
    scored = []
    for chunk, filename in rows:
        if not chunk.embedding_json:
            continue  # 旧数据无向量时由关键词兜底覆盖
        try:
            vec = json.loads(chunk.embedding_json)
        except json.JSONDecodeError:
            continue
        score = embeddings.cosine(query_vec, vec)
        scored.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                material_id=chunk.material_id,
                material_name=filename,
                content=chunk.content,
                score=round(score, 4),
            )
        )
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:limit]


# ---------------------------------------------------------------- 关键词检索

def _query_terms(query: str) -> list[str]:
    """英文按空格分词；中文补充二元词组（bigram）提升召回。"""
    terms = [t.lower() for t in query.split() if t.strip()]
    cjk = [ch for ch in query if "一" <= ch <= "鿿"]
    bigrams = ["".join(cjk[i : i + 2]) for i in range(len(cjk) - 1)]
    combined = list(dict.fromkeys(terms + bigrams))
    return combined or [query.strip().lower()]


def _keyword_search(rows, query: str, limit: int) -> list[RetrievedChunk]:
    terms = _query_terms(query)
    scored = []
    for chunk, filename in rows:
        lowered = chunk.content.lower()
        score = float(sum(lowered.count(term) for term in terms if term))
        if score > 0:
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    material_id=chunk.material_id,
                    material_name=filename,
                    content=chunk.content,
                    score=score,
                )
            )
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:limit]


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _chinese_number(value: str) -> int | None:
    """解析常见中文章节数字，覆盖一至九十九。"""
    if not value:
        return None
    if "十" in value:
        left, right = value.split("十", 1)
        tens = _CHINESE_DIGITS.get(left, 1) if left else 1
        ones = _CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    digits = [_CHINESE_DIGITS.get(char) for char in value]
    if any(digit is None for digit in digits):
        return None
    number = 0
    for digit in digits:
        number = number * 10 + digit
    return number


def _chapter_number(text: str) -> int | None:
    lowered = text.casefold()
    patterns = (
        r"(?:chapter|chap)[\s._-]*(\d+)",
        r"第\s*(\d+)\s*[章节讲单元篇]",
        r"^\s*(\d+)\s*[._、-]",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            return int(match.group(1))
    match = re.search(r"第\s*([零〇一二三四五六七八九十]+)\s*[章节讲单元篇]", text)
    return _chinese_number(match.group(1)) if match else None


def _natural_key(value: str):
    """让 Chap2 排在 Chap10 前，同时保持无数字文件名排序稳定。"""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", value.casefold())
        if part
    )


def ordered_course_chunks(db: Session, course_id: int) -> list[RetrievedChunk]:
    """读取课程全部切片，按章节自然顺序和资料内原文顺序排列。

    优先从文件名识别 Chapter/Chap/第N章；文件名没有章节号时，再检查资料
    首个切片。无法识别章节的资料按自然文件名排序，并以资料 ID 保证稳定性。
    """
    rows = db.execute(
        select(MaterialChunk, Material)
        .join(Material, Material.id == MaterialChunk.material_id)
        .where(MaterialChunk.course_id == course_id)
        .order_by(Material.id, MaterialChunk.seq)
    ).all()
    materials = []
    for material_id, grouped in groupby(rows, key=lambda row: row[0].material_id):
        group_rows = list(grouped)
        material = group_rows[0][1]
        first_content = group_rows[0][0].content[:300] if group_rows else ""
        chapter = _chapter_number(material.filename)
        if chapter is None:
            chapter = _chapter_number(first_content)
        order_key = (
            0 if chapter is not None else 1,
            chapter if chapter is not None else 0,
            _natural_key(material.filename),
            material_id,
        )
        materials.append((order_key, material, group_rows))
    materials.sort(key=lambda item: item[0])

    ordered = []
    for _, material, group_rows in materials:
        for chunk, _ in sorted(group_rows, key=lambda row: row[0].seq):
            ordered.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    material_id=chunk.material_id,
                    material_name=material.filename,
                    content=chunk.content,
                    score=0.0,
                )
            )
    return ordered
