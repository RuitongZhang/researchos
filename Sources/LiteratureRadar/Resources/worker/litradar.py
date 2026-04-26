#!/usr/bin/env python3
"""LiteratureRadar worker.

Local-first SQLite backend for a macOS SwiftUI research radar.  This version
keeps the old lightweight paper-radar behavior, but upgrades long-term memory
from a pile of Markdown notes into a layered Research Memory OS:

L0 source/evidence, L1 episodic events, L2 semantic knowledge graph,
L3 methodology/procedural rules, L4 metacognitive insights and research
intent, and L5 per-task context packets with retrieval traces.

The script intentionally uses only the Python standard library so it can run on
a clean macOS installation. Optional PDF extraction libraries are used only when
available.
"""
from __future__ import annotations

import argparse
import base64
import csv
import dataclasses
import hashlib
import json
import os
import re
import sqlite3
import sys
import textwrap
import time
import traceback
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

APP_NAME = "LiteratureRadar"
DEFAULT_DB = Path.home() / "Library" / "Application Support" / APP_NAME / "literature_radar.sqlite3"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_READER_MODEL = "deepseek-v4-pro"
DEFAULT_FLASH_MODEL = "deepseek-v4-flash"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


def stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("\u241f".join(p or "" for p in parts).encode("utf-8", "ignore")).hexdigest()[:20]
    return f"{prefix}_{h}"


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def jload(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def normalize_ws(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_doi(value: str | None) -> str:
    text = normalize_ws(value)
    if not text:
        return ""
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
    text = re.sub(r"^doi:\s*", "", text, flags=re.I)
    return text.strip(" .;,").lower()


def tokenize(text: str | None) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+\-\.]{1,}", text or "")]


def unique_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        value = normalize_ws(value)
        if value and value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return out


def first_sentence(text: str | None, fallback: str = "No abstract available.") -> str:
    text = normalize_ws(text)
    if not text:
        return fallback
    pieces = re.split(r"(?<=[.!?])\s+", text)
    return pieces[0][:320]


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    return data


def success(data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"ok": True}
    if data:
        payload.update(data)
    return payload


class WorkerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

SCHEMA = r"""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    doi TEXT,
    arxiv_id TEXT,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL DEFAULT '',
    authors_json TEXT NOT NULL DEFAULT '[]',
    published_date TEXT,
    updated_date TEXT,
    url TEXT,
    pdf_url TEXT,
    category TEXT,
    version TEXT,
    analysis_status TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    include_terms_json TEXT NOT NULL DEFAULT '[]',
    exclude_terms_json TEXT NOT NULL DEFAULT '[]',
    seed_papers_json TEXT NOT NULL DEFAULT '[]',
    watch_authors_json TEXT NOT NULL DEFAULT '[]',
    watch_labs_json TEXT NOT NULL DEFAULT '[]',
    arxiv_query TEXT NOT NULL DEFAULT '',
    biorxiv_query TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_scores (
    profile_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    bm25_score REAL NOT NULL DEFAULT 0,
    embedding_score REAL NOT NULL DEFAULT 0,
    rule_score REAL NOT NULL DEFAULT 0,
    final_score REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(profile_id, paper_id)
);

CREATE TABLE IF NOT EXISTS paper_actions (
    profile_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(profile_id, paper_id, action)
);

CREATE TABLE IF NOT EXISTS paper_exports (
    paper_id TEXT NOT NULL,
    export_type TEXT NOT NULL,
    path TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(paper_id, export_type)
);

CREATE TABLE IF NOT EXISTS memory_notes (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    markdown_path TEXT,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_chunks (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    page INTEGER,
    section TEXT,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'abstract',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_spans (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    chunk_id TEXT,
    page INTEGER,
    section TEXT,
    char_start INTEGER,
    char_end INTEGER,
    quote_hash TEXT NOT NULL,
    raw_quote TEXT NOT NULL,
    extraction_model TEXT,
    extraction_prompt_version TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodic_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    object_type TEXT,
    object_id TEXT,
    profile_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL,
    decay_policy TEXT NOT NULL DEFAULT 'standard',
    importance REAL NOT NULL DEFAULT 0.5,
    trust_score REAL NOT NULL DEFAULT 0.5
);

CREATE TABLE IF NOT EXISTS knowledge_nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    properties_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    trust_score REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'draft',
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_node_key
ON knowledge_nodes(type, canonical_name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS knowledge_edges (
    id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    trust_score REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_edge_key
ON knowledge_edges(source_node_id, relation_type, target_node_id);

CREATE TABLE IF NOT EXISTS atomic_knowledge_units (
    id TEXT PRIMARY KEY,
    paper_id TEXT,
    node_id TEXT,
    unit_type TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metacognitive_items (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    item_type TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'hypothesis',
    confidence REAL NOT NULL DEFAULT 0.5,
    linked_node_ids_json TEXT NOT NULL DEFAULT '[]',
    supporting_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    counter_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    next_actions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS methodology_rules (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    rule TEXT NOT NULL,
    applies_to_json TEXT NOT NULL DEFAULT '[]',
    reason TEXT NOT NULL DEFAULT '',
    examples_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0.7,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interest_states (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    topic_node_id TEXT,
    topic TEXT NOT NULL,
    intensity REAL NOT NULL DEFAULT 0.1,
    half_life_days REAL NOT NULL DEFAULT 14,
    positive_signal_count INTEGER NOT NULL DEFAULT 0,
    negative_signal_count INTEGER NOT NULL DEFAULT 0,
    last_activated_at TEXT,
    source_event_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_interest_key
ON interest_states(profile_id, topic COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS memory_change_sets (
    id TEXT PRIMARY KEY,
    trigger_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT 'low',
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL,
    applied_at TEXT,
    model_name TEXT,
    prompt_version TEXT
);

CREATE TABLE IF NOT EXISTS memory_change_log (
    id TEXT PRIMARY KEY,
    change_set_id TEXT,
    operation_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    before_json TEXT,
    after_json TEXT,
    actor TEXT NOT NULL DEFAULT 'system',
    model_name TEXT,
    prompt_version TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    change_set_id TEXT,
    item_json TEXT NOT NULL DEFAULT '{}',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS taxonomy_versions (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    title TEXT NOT NULL,
    tree_json TEXT NOT NULL DEFAULT '{}',
    markdown TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    source_snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_packets (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    task TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    packet_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_traces (
    id TEXT PRIMARY KEY,
    context_packet_id TEXT,
    query TEXT NOT NULL DEFAULT '',
    retrieved_json TEXT NOT NULL DEFAULT '{}',
    used_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


DEFAULT_METHODOLOGY_RULES = [
    {
        "rule": "深度阅读论文时必须拆分为 Problem、Method、Claim、Evidence、Limitation、Open Question，而不是只保存整篇阅读报告。",
        "applies_to": ["deep_read", "paper_integration"],
        "reason": "避免长期记忆变成 Markdown 拼接；支持证据追溯和跨文献重构。",
        "examples": ["usefulness", "integrate-papers"],
    },
    {
        "rule": "搜索、浅读、点击、收藏等浅层信号只能更新 episodic_events 和 interest_states，不能直接晋升为事实知识。",
        "applies_to": ["radar", "search", "feedback"],
        "reason": "防止摘要和兴趣污染语义知识图谱。",
        "examples": ["radar_candidate_found", "skim_event"],
    },
    {
        "rule": "任何 Claim 或 Finding 进入语义知识层前都必须绑定 evidence_span；无法绑定则保持 draft 或 needs_review。",
        "applies_to": ["claim", "finding", "knowledge_graph"],
        "reason": "让系统出错时可以定位原文证据并回滚。",
        "examples": ["evidence_backed", "needs_review"],
    },
]


DEMO_PAPERS = [
    {
        "id": "demo_single_cell_regulatory_memory",
        "source": "demo",
        "doi": "10.0000/demo.singlecell",
        "title": "Single-cell regulatory memory maps reveal durable perturbation programs",
        "abstract": "We introduce a single-cell perturbation map for regulatory memory. The method links transcription factor activity, perturbation response, and durable cell-state transitions across time points.",
        "authors": ["Jane Doe", "A. Regev"],
        "published_date": "2025-04-10",
        "updated_date": "2025-04-11",
        "url": "https://example.org/single-cell-memory",
        "pdf_url": None,
        "category": "q-bio.GN",
        "version": "v1",
    },
    {
        "id": "demo_graph_agent_memory",
        "source": "demo",
        "doi": "10.0000/demo.graphmemory",
        "title": "Graph-based agent memory for cross-session scientific reasoning",
        "abstract": "This paper studies long-term memory for research agents. A graph memory connects claims, methods, datasets, and failures, improving multi-hop retrieval over pure vector stores.",
        "authors": ["Rui Zhang", "Ada Chen"],
        "published_date": "2025-05-02",
        "updated_date": "2025-05-03",
        "url": "https://example.org/agent-memory",
        "pdf_url": None,
        "category": "cs.AI",
        "version": "v1",
    },
    {
        "id": "demo_spatial_transcriptomics_atlas",
        "source": "demo",
        "doi": "10.0000/demo.spatial",
        "title": "Spatial transcriptomics atlas for tissue-scale perturbation inference",
        "abstract": "A spatial transcriptomics atlas is used to infer perturbation effects across tissue neighborhoods. The work highlights benchmark limitations and uncertainty in cell-cell communication inference.",
        "authors": ["Min Lee", "Fabian Theis"],
        "published_date": "2024-12-15",
        "updated_date": "2025-01-08",
        "url": "https://example.org/spatial-atlas",
        "pdf_url": None,
        "category": "q-bio.QM",
        "version": "v2",
    },
]


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self.conn.close()

    def init(self, seed_demo: bool = False) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.migrate_legacy_schema()
        self.ensure_default_profile()
        self.ensure_default_methodology_rules()
        if seed_demo:
            self.seed_demo()
            self.rank_all()

    def migrate_legacy_schema(self) -> None:
        def columns(table: str) -> set[str]:
            rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            return {row["name"] for row in rows}

        def ensure_column(table: str, name: str, ddl: str) -> None:
            if name not in columns(table):
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

        ensure_column("papers", "analysis_status", "TEXT")
        ensure_column("papers", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        ensure_column("memory_notes", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        ensure_column("memory_notes", "created_at", "TEXT NOT NULL DEFAULT ''")
        self.conn.execute("UPDATE memory_notes SET created_at=updated_at WHERE created_at='' OR created_at IS NULL")
        ensure_column("paper_exports", "export_type", "TEXT NOT NULL DEFAULT ''")
        ensure_column("paper_exports", "created_at", "TEXT NOT NULL DEFAULT ''")
        export_cols = columns("paper_exports")
        if "target" in export_cols:
            self.conn.execute("UPDATE paper_exports SET export_type=target WHERE export_type='' OR export_type IS NULL")
        if "exported_at" in export_cols:
            self.conn.execute("UPDATE paper_exports SET created_at=exported_at WHERE created_at='' OR created_at IS NULL")

        tables = {
            row["name"]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "feedback" in tables:
            feedback_cols = columns("feedback")
            required = {"profile_id", "paper_id", "action", "created_at"}
            if required.issubset(feedback_cols):
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO paper_actions (profile_id, paper_id, action, created_at)
                    SELECT profile_id, paper_id, action, created_at FROM feedback
                    WHERE profile_id IS NOT NULL AND paper_id IS NOT NULL AND action IS NOT NULL
                    """
                )
        max_score_row = self.conn.execute("SELECT MAX(final_score) AS max_score FROM paper_scores").fetchone()
        if max_score_row and safe_float(max_score_row["max_score"], 0.0) > 1.0:
            self.conn.execute(
                """
                UPDATE paper_scores
                SET final_score=MIN(final_score / 100.0, 1.0),
                    bm25_score=MIN(bm25_score, 1.0),
                    embedding_score=MIN(embedding_score, 1.0),
                    rule_score=MIN(rule_score, 1.0)
                WHERE final_score > 1.0
                """
            )
        self.conn.commit()

    def ensure_default_profile(self) -> str:
        row = self.conn.execute("SELECT id FROM research_profiles ORDER BY created_at LIMIT 1").fetchone()
        if row:
            return row["id"]
        now = utcnow()
        profile_id = "default_profile"
        self.conn.execute(
            """
            INSERT INTO research_profiles
            (id, name, weight, include_terms_json, exclude_terms_json, seed_papers_json,
             watch_authors_json, watch_labs_json, arxiv_query, biorxiv_query, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                "Research Memory OS",
                1.0,
                jdump(["single-cell", "regulatory memory", "agent memory", "knowledge graph", "long-term memory"]),
                jdump(["editorial", "protocol only"]),
                jdump([]),
                jdump([]),
                jdump([]),
                'all:("agent memory" OR "knowledge graph" OR "single-cell" OR "regulatory memory")',
                '"single-cell" OR "regulatory memory" OR "agent memory"',
                now,
                now,
            ),
        )
        self.conn.commit()
        return profile_id

    def ensure_default_methodology_rules(self) -> None:
        profile_id = self.ensure_default_profile()
        count = self.conn.execute("SELECT COUNT(*) AS c FROM methodology_rules").fetchone()["c"]
        if count:
            return
        now = utcnow()
        for item in DEFAULT_METHODOLOGY_RULES:
            self.conn.execute(
                """
                INSERT INTO methodology_rules
                (id, profile_id, rule, applies_to_json, reason, examples_json, status, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'active', 0.82, ?, ?)
                """,
                (
                    make_id("rule"),
                    profile_id,
                    item["rule"],
                    jdump(item["applies_to"]),
                    item["reason"],
                    jdump(item["examples"]),
                    now,
                    now,
                ),
            )
        self.conn.commit()

    def seed_demo(self) -> None:
        for paper in DEMO_PAPERS:
            upsert_paper(self.conn, paper)
            ensure_paper_chunk(self.conn, paper["id"], paper.get("abstract") or "", source="abstract")
        self.conn.commit()

    def rank_all(self, profile_ids: list[str] | None = None) -> int:
        profiles = list_profiles(self.conn)
        if profile_ids:
            profiles = [p for p in profiles if p["id"] in set(profile_ids)]
        papers = [row_to_paper(self.conn, r) for r in self.conn.execute("SELECT * FROM papers")]
        scored = 0
        for profile in profiles:
            for paper in papers:
                score = calculate_score(self.conn, profile, paper)
                self.conn.execute(
                    """
                    INSERT INTO paper_scores
                    (profile_id, paper_id, bm25_score, embedding_score, rule_score, final_score, reason, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id, paper_id) DO UPDATE SET
                        bm25_score=excluded.bm25_score,
                        embedding_score=excluded.embedding_score,
                        rule_score=excluded.rule_score,
                        final_score=excluded.final_score,
                        reason=excluded.reason,
                        updated_at=excluded.updated_at
                    """,
                    (
                        profile["id"],
                        paper["id"],
                        score["bm25_score"],
                        score["embedding_score"],
                        score["rule_score"],
                        score["final_score"],
                        score["reason"],
                        utcnow(),
                    ),
                )
                scored += 1
        self.conn.commit()
        return scored


# ---------------------------------------------------------------------------
# Rows and serialization
# ---------------------------------------------------------------------------


def list_profiles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM research_profiles ORDER BY updated_at DESC, name").fetchall()
    return [row_to_profile(r) for r in rows]


def row_to_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "weight": row["weight"],
        "include_terms": jload(row["include_terms_json"], []),
        "exclude_terms": jload(row["exclude_terms_json"], []),
        "seed_papers": jload(row["seed_papers_json"], []),
        "watch_authors": jload(row["watch_authors_json"], []),
        "watch_labs": jload(row["watch_labs_json"], []),
        "arxiv_query": row["arxiv_query"] or "",
        "biorxiv_query": row["biorxiv_query"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def paper_actions(conn: sqlite3.Connection, paper_id: str, profile_id: str | None = None) -> list[str]:
    if profile_id:
        rows = conn.execute(
            "SELECT action FROM paper_actions WHERE paper_id=? AND profile_id=? ORDER BY created_at",
            (paper_id, profile_id),
        ).fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT action FROM paper_actions WHERE paper_id=? ORDER BY action", (paper_id,)).fetchall()
    return [r["action"] for r in rows]


def paper_exports(conn: sqlite3.Connection, paper_id: str) -> list[str]:
    rows = conn.execute("SELECT export_type FROM paper_exports WHERE paper_id=? ORDER BY export_type", (paper_id,)).fetchall()
    return [r["export_type"] for r in rows]


def row_to_paper(conn: sqlite3.Connection, row: sqlite3.Row, profile_id: str | None = None) -> dict[str, Any]:
    metadata = jload(row["metadata_json"], {})
    score = None
    if profile_id:
        s = conn.execute(
            "SELECT * FROM paper_scores WHERE paper_id=? AND profile_id=?",
            (row["id"], profile_id),
        ).fetchone()
        if s:
            score = {
                "profile_id": s["profile_id"],
                "paper_id": s["paper_id"],
                "bm25_score": s["bm25_score"],
                "embedding_score": s["embedding_score"],
                "rule_score": s["rule_score"],
                "final_score": s["final_score"],
                "reason": s["reason"],
                "updated_at": s["updated_at"],
            }
    return {
        "id": row["id"],
        "source": row["source"],
        "doi": row["doi"],
        "arxiv_id": row["arxiv_id"],
        "title": row["title"],
        "abstract": row["abstract"],
        "authors": jload(row["authors_json"], []),
        "published_date": row["published_date"],
        "updated_date": row["updated_date"],
        "url": row["url"],
        "pdf_url": row["pdf_url"],
        "category": row["category"],
        "version": row["version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "score": score,
        "analysis_status": row["analysis_status"],
        "actions": paper_actions(conn, row["id"], profile_id),
        "exports": paper_exports(conn, row["id"]),
        "metadata": metadata,
        "pdf_path": metadata.get("pdf_path") or (row["pdf_url"] if row["pdf_url"] and not str(row["pdf_url"]).startswith("http") else None),
    }


def row_to_memory(row: sqlite3.Row, include_content: bool = True) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "type": row["type"],
        "title": row["title"],
        "markdown_path": row["markdown_path"],
        "content": row["content"] if include_content else "",
        "updated_at": row["updated_at"],
    }


def upsert_paper(conn: sqlite3.Connection, data: dict[str, Any]) -> str:
    now = utcnow()
    doi = normalize_doi(data.get("doi")) or None
    arxiv_id = normalize_ws(data.get("arxiv_id") or data.get("arxivId")) or None
    title = normalize_ws(data.get("title")) or "Untitled"
    abstract = normalize_ws(data.get("abstract"))

    paper_id = None
    if doi:
        row = conn.execute("SELECT id FROM papers WHERE doi = ? COLLATE NOCASE", (doi,)).fetchone()
        if row:
            paper_id = row["id"]
    if paper_id is None and arxiv_id:
        row = conn.execute("SELECT id FROM papers WHERE arxiv_id = ? COLLATE NOCASE", (arxiv_id,)).fetchone()
        if row:
            paper_id = row["id"]

    if paper_id is not None:
        pass
    elif data.get("id"):
        paper_id = str(data["id"])
    elif doi:
        paper_id = stable_id("paper", doi.lower())
    elif arxiv_id:
        paper_id = stable_id("paper", arxiv_id.lower())
    else:
        paper_id = stable_id("paper", title.lower(), abstract[:180])
    authors = data.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in re.split(r";|, and | and ", authors) if a.strip()]
    metadata = dict(data.get("metadata") or {})
    if data.get("pdf_path"):
        metadata["pdf_path"] = data.get("pdf_path")
    elif data.get("pdf_url") and not re.match(r"^https?://", str(data.get("pdf_url"))):
        metadata["pdf_path"] = data.get("pdf_url")
    conn.execute(
        """
        INSERT INTO papers
        (id, source, doi, arxiv_id, title, abstract, authors_json, published_date, updated_date,
         url, pdf_url, category, version, analysis_status, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            source=excluded.source,
            doi=COALESCE(excluded.doi, papers.doi),
            arxiv_id=COALESCE(excluded.arxiv_id, papers.arxiv_id),
            title=excluded.title,
            abstract=excluded.abstract,
            authors_json=excluded.authors_json,
            published_date=COALESCE(excluded.published_date, papers.published_date),
            updated_date=COALESCE(excluded.updated_date, papers.updated_date),
            url=COALESCE(excluded.url, papers.url),
            pdf_url=COALESCE(excluded.pdf_url, papers.pdf_url),
            category=COALESCE(excluded.category, papers.category),
            version=COALESCE(excluded.version, papers.version),
            metadata_json=excluded.metadata_json,
            updated_at=excluded.updated_at
        """,
        (
            paper_id,
            data.get("source") or "local",
            doi,
            arxiv_id,
            title,
            abstract,
            jdump(authors),
            data.get("published_date") or data.get("publishedDate"),
            data.get("updated_date") or data.get("updatedDate"),
            data.get("url"),
            data.get("pdf_url") or data.get("pdfUrl"),
            data.get("category"),
            data.get("version"),
            data.get("analysis_status"),
            jdump(metadata),
            now,
            now,
        ),
    )
    return paper_id


def ensure_paper_chunk(conn: sqlite3.Connection, paper_id: str, text: str, source: str = "abstract") -> str | None:
    text = normalize_ws(text)
    if not text:
        return None
    chunk_id = stable_id("chunk", paper_id, source, text[:300])
    conn.execute(
        """
        INSERT OR IGNORE INTO paper_chunks
        (id, paper_id, chunk_index, page, section, text, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (chunk_id, paper_id, 0, None, source.title(), text, source, utcnow()),
    )
    return chunk_id


# ---------------------------------------------------------------------------
# DeepSeek and prompts
# ---------------------------------------------------------------------------


def load_prompt(name: str, fallback: str) -> str:
    path = PROMPT_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def get_reader_key() -> str | None:
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_READER_API_KEY")


def get_flash_key() -> str | None:
    return os.environ.get("DEEPSEEK_FLASH_API_KEY")


def call_deepseek(
    *,
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    timeout: int = 120,
    temperature: float = 0.1,
    thinking: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if thinking:
        body["thinking"] = {"type": thinking}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise WorkerError(f"DeepSeek API call failed: {exc}") from exc
    try:
        return payload["choices"][0]["message"]["content"]
    except Exception as exc:
        raise WorkerError(f"DeepSeek API returned an unexpected payload: {payload}") from exc


def parse_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("DeepSeek response must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Scoring and retrieval
# ---------------------------------------------------------------------------


def term_score(text: str, terms: list[str]) -> tuple[float, list[str]]:
    text_l = text.lower()
    hits = []
    score = 0.0
    for term in terms:
        t = term.lower().strip()
        if not t:
            continue
        if t in text_l:
            hits.append(term)
            score += min(1.0, max(0.1, len(tokenize(term)) * 0.25))
    return score, hits


def calculate_score(conn: sqlite3.Connection, profile: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    haystack = " ".join([paper.get("title") or "", paper.get("abstract") or "", " ".join(paper.get("authors") or [])])
    include_score, include_hits = term_score(haystack, profile.get("include_terms", []))
    exclude_score, exclude_hits = term_score(haystack, profile.get("exclude_terms", []))
    author_score, author_hits = term_score(" ".join(paper.get("authors") or []), profile.get("watch_authors", []))
    feedback_rows = conn.execute(
        "SELECT action FROM paper_actions WHERE paper_id=? AND profile_id=?",
        (paper["id"], profile["id"]),
    ).fetchall()
    feedback_bonus = 0.0
    feedback_names = []
    for r in feedback_rows:
        action = r["action"]
        feedback_names.append(action)
        if action in {"like", "save", "read"}:
            feedback_bonus += {"like": 0.35, "save": 0.45, "read": 0.25}[action]
        elif action in {"dislike", "skip"}:
            feedback_bonus -= 0.45
    bm25 = min(1.0, include_score / 3.0)
    rule = clamp(0.35 + include_score * 0.15 + author_score * 0.2 + feedback_bonus - exclude_score * 0.35, 0.0, 1.0)
    final = clamp((bm25 * 0.55 + rule * 0.45) * safe_float(profile.get("weight"), 1.0), 0.0, 1.0)
    reason_parts = []
    if include_hits:
        reason_parts.append("matches " + ", ".join(include_hits[:5]))
    if author_hits:
        reason_parts.append("watch author " + ", ".join(author_hits[:3]))
    if feedback_names:
        reason_parts.append("feedback " + ", ".join(feedback_names))
    if exclude_hits:
        reason_parts.append("down-ranked by " + ", ".join(exclude_hits[:3]))
    reason = "; ".join(reason_parts) or "local lexical baseline"
    return {
        "bm25_score": round(bm25, 4),
        "embedding_score": 0.0,
        "rule_score": round(rule, 4),
        "final_score": round(final, 4),
        "reason": reason,
    }


def update_interest(conn: sqlite3.Connection, profile_id: str | None, topic: str, delta: float, event_id: str | None = None) -> None:
    topic = normalize_ws(topic)
    if not topic:
        return
    row = conn.execute(
        "SELECT * FROM interest_states WHERE profile_id IS ? AND lower(topic)=lower(?)",
        (profile_id, topic),
    ).fetchone()
    now = utcnow()
    if row:
        intensity = clamp(row["intensity"] + delta, 0.0, 1.0)
        pos = row["positive_signal_count"] + (1 if delta > 0 else 0)
        neg = row["negative_signal_count"] + (1 if delta < 0 else 0)
        source_ids = jload(row["source_event_ids_json"], [])
        if event_id:
            source_ids = unique_keep_order(source_ids + [event_id])[-50:]
        conn.execute(
            """
            UPDATE interest_states
            SET intensity=?, positive_signal_count=?, negative_signal_count=?, last_activated_at=?, source_event_ids_json=?, status='active'
            WHERE id=?
            """,
            (intensity, pos, neg, now, jdump(source_ids), row["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO interest_states
            (id, profile_id, topic_node_id, topic, intensity, half_life_days,
             positive_signal_count, negative_signal_count, last_activated_at, source_event_ids_json, status)
            VALUES (?, ?, NULL, ?, ?, 14, ?, ?, ?, ?, 'active')
            """,
            (
                make_id("interest"),
                profile_id,
                topic,
                clamp(0.2 + delta, 0, 1),
                1 if delta > 0 else 0,
                1 if delta < 0 else 0,
                now,
                jdump([event_id] if event_id else []),
            ),
        )


def log_event(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    actor: str = "system",
    object_type: str | None = None,
    object_id: str | None = None,
    profile_id: str | None = None,
    payload: dict[str, Any] | None = None,
    importance: float = 0.5,
    trust_score: float = 0.6,
) -> str:
    event_id = make_id("evt")
    conn.execute(
        """
        INSERT INTO episodic_events
        (id, event_type, actor, object_type, object_id, profile_id, payload_json,
         occurred_at, decay_policy, importance, trust_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'standard', ?, ?)
        """,
        (event_id, event_type, actor, object_type, object_id, profile_id, jdump(payload or {}), utcnow(), importance, trust_score),
    )
    return event_id


# ---------------------------------------------------------------------------
# Knowledge and memory write path
# ---------------------------------------------------------------------------


def upsert_node(
    conn: sqlite3.Connection,
    node_type: str,
    name: str,
    *,
    summary: str = "",
    aliases: list[str] | None = None,
    properties: dict[str, Any] | None = None,
    confidence: float = 0.55,
    trust_score: float = 0.55,
    status: str = "draft",
    source_ids: list[str] | None = None,
) -> str:
    name = normalize_ws(name)
    if not name:
        name = "Untitled"
    now = utcnow()
    existing = conn.execute(
        "SELECT * FROM knowledge_nodes WHERE type=? AND lower(canonical_name)=lower(?)",
        (node_type, name),
    ).fetchone()
    if existing:
        merged_sources = unique_keep_order(jload(existing["source_ids_json"], []) + (source_ids or []))
        merged_aliases = unique_keep_order(jload(existing["aliases_json"], []) + (aliases or []))
        new_conf = max(existing["confidence"], confidence)
        new_trust = max(existing["trust_score"], trust_score)
        new_summary = summary or existing["summary"]
        props = jload(existing["properties_json"], {})
        props.update(properties or {})
        conn.execute(
            """
            UPDATE knowledge_nodes
            SET aliases_json=?, summary=?, properties_json=?, confidence=?, trust_score=?, status=?, source_ids_json=?, updated_at=?
            WHERE id=?
            """,
            (jdump(merged_aliases), new_summary, jdump(props), new_conf, new_trust, status, jdump(merged_sources), now, existing["id"]),
        )
        return existing["id"]
    node_id = stable_id("node", node_type, name)
    conn.execute(
        """
        INSERT OR IGNORE INTO knowledge_nodes
        (id, type, canonical_name, aliases_json, summary, properties_json, confidence, trust_score, status, source_ids_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, node_type, name, jdump(aliases or []), summary, jdump(properties or {}), confidence, trust_score, status, jdump(source_ids or []), now, now),
    )
    return node_id


def add_edge(
    conn: sqlite3.Connection,
    source_node_id: str,
    relation_type: str,
    target_node_id: str,
    *,
    evidence_ids: list[str] | None = None,
    confidence: float = 0.55,
    trust_score: float = 0.55,
    status: str = "draft",
) -> str:
    now = utcnow()
    existing = conn.execute(
        "SELECT * FROM knowledge_edges WHERE source_node_id=? AND relation_type=? AND target_node_id=?",
        (source_node_id, relation_type, target_node_id),
    ).fetchone()
    if existing:
        merged_evidence = unique_keep_order(jload(existing["evidence_ids_json"], []) + (evidence_ids or []))
        conn.execute(
            """
            UPDATE knowledge_edges
            SET evidence_ids_json=?, confidence=?, trust_score=?, status=?, updated_at=?
            WHERE id=?
            """,
            (jdump(merged_evidence), max(existing["confidence"], confidence), max(existing["trust_score"], trust_score), status, now, existing["id"]),
        )
        return existing["id"]
    edge_id = stable_id("edge", source_node_id, relation_type, target_node_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO knowledge_edges
        (id, source_node_id, relation_type, target_node_id, evidence_ids_json, confidence, trust_score, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (edge_id, source_node_id, relation_type, target_node_id, jdump(evidence_ids or []), confidence, trust_score, status, now, now),
    )
    return edge_id


def create_evidence_span(
    conn: sqlite3.Connection,
    paper_id: str,
    quote: str,
    *,
    chunk_id: str | None = None,
    section: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> str:
    quote = normalize_ws(quote)[:1200]
    if not quote:
        quote = "Evidence unavailable; generated from paper metadata."
    qhash = hashlib.sha1(quote.encode("utf-8", "ignore")).hexdigest()
    evidence_id = stable_id("evidence", paper_id, qhash)
    conn.execute(
        """
        INSERT OR IGNORE INTO evidence_spans
        (id, paper_id, chunk_id, page, section, char_start, char_end, quote_hash, raw_quote,
         extraction_model, extraction_prompt_version, created_at)
        VALUES (?, ?, ?, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?)
        """,
        (evidence_id, paper_id, chunk_id, section or "Abstract/PDF excerpt", qhash, quote, model, prompt_version, utcnow()),
    )
    return evidence_id


def create_atomic_unit(
    conn: sqlite3.Connection,
    paper_id: str,
    unit_type: str,
    content: str,
    evidence_ids: list[str],
    *,
    node_id: str | None = None,
    confidence: float = 0.55,
    status: str = "evidence_backed",
) -> str:
    content = normalize_ws(content)
    if not content:
        return ""
    unit_id = stable_id("aku", paper_id, unit_type, content[:240])
    now = utcnow()
    conn.execute(
        """
        INSERT INTO atomic_knowledge_units
        (id, paper_id, node_id, unit_type, content, evidence_ids_json, confidence, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            node_id=COALESCE(excluded.node_id, atomic_knowledge_units.node_id),
            evidence_ids_json=excluded.evidence_ids_json,
            confidence=max(atomic_knowledge_units.confidence, excluded.confidence),
            status=excluded.status,
            updated_at=excluded.updated_at
        """,
        (unit_id, paper_id, node_id, unit_type, content, jdump(evidence_ids), confidence, status, now, now),
    )
    return unit_id


def create_change_set(
    conn: sqlite3.Connection,
    *,
    trigger: dict[str, Any],
    summary: str,
    risk_level: str = "low",
    status: str = "applied",
    model_name: str | None = None,
    prompt_version: str | None = None,
) -> str:
    cs_id = make_id("changeset")
    now = utcnow()
    conn.execute(
        """
        INSERT INTO memory_change_sets
        (id, trigger_json, summary, risk_level, status, created_at, applied_at, model_name, prompt_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cs_id, jdump(trigger), summary, risk_level, status, now, now if status == "applied" else None, model_name, prompt_version),
    )
    return cs_id


def log_change(
    conn: sqlite3.Connection,
    change_set_id: str,
    operation_type: str,
    target_type: str,
    target_id: str | None,
    after: dict[str, Any] | list[Any] | str | None,
    *,
    before: Any = None,
    actor: str = "system",
    model_name: str | None = None,
    prompt_version: str | None = None,
    reason: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO memory_change_log
        (id, change_set_id, operation_type, target_type, target_id, before_json, after_json,
         actor, model_name, prompt_version, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            make_id("chg"),
            change_set_id,
            operation_type,
            target_type,
            target_id,
            jdump(before) if before is not None else None,
            jdump(after) if after is not None else None,
            actor,
            model_name,
            prompt_version,
            reason,
            utcnow(),
        ),
    )


def extract_structured_memory(conn: sqlite3.Connection, profile_id: str | None, paper: dict[str, Any], analysis: dict[str, Any], model: str) -> dict[str, Any]:
    """Convert a DeepSeek paper analysis or local synthesis into layered memory."""
    paper_id = paper["id"]
    source_text = normalize_ws(paper.get("abstract")) or normalize_ws(analysis.get("one_sentence"))
    chunk_id = ensure_paper_chunk(conn, paper_id, source_text, source="abstract")
    evidence_id = create_evidence_span(conn, paper_id, source_text, chunk_id=chunk_id, model=model, prompt_version="research_memory_os_v1")
    cs_id = create_change_set(
        conn,
        trigger={"event": "paper_deep_read", "paper_id": paper_id, "profile_id": profile_id},
        summary=f"Integrated {paper.get('title')} into layered memory.",
        risk_level="low",
        model_name=model,
        prompt_version="research_memory_os_v1",
    )

    title_node = upsert_node(
        conn,
        "Paper",
        paper.get("title") or paper_id,
        summary=first_sentence(paper.get("abstract"), "Paper imported without abstract."),
        properties={"paper_id": paper_id, "source": paper.get("source"), "doi": paper.get("doi")},
        confidence=0.95,
        trust_score=0.9,
        status="evidence_backed",
        source_ids=[paper_id],
    )
    log_change(conn, cs_id, "upsert_node", "knowledge_node", title_node, {"type": "Paper", "paper_id": paper_id})

    # Topics from profile matches and model output.
    candidate_topics: list[str] = []
    for key in ["useful_for", "connects_to_memory", "knowledge_map_updates", "methods_or_data"]:
        value = analysis.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    candidate_topics.append(str(item.get("node") or item.get("claim") or item.get("topic") or item))
                else:
                    candidate_topics.append(str(item))
        elif isinstance(value, str):
            candidate_topics.append(value)
    if profile_id:
        profile = conn.execute("SELECT * FROM research_profiles WHERE id=?", (profile_id,)).fetchone()
        if profile:
            profile_dict = row_to_profile(profile)
            score, hits = term_score((paper.get("title") or "") + " " + (paper.get("abstract") or ""), profile_dict.get("include_terms", []))
            candidate_topics.extend(hits)
    if not candidate_topics:
        candidate_topics.extend(tokenize(paper.get("title"))[:4])

    topic_nodes = []
    for topic in unique_keep_order(candidate_topics)[:8]:
        topic_name = normalize_ws(topic)
        if len(topic_name) > 90:
            topic_name = topic_name[:90].rsplit(" ", 1)[0]
        if not topic_name or len(topic_name) < 3:
            continue
        node_id = upsert_node(
            conn,
            "Concept",
            topic_name,
            summary=f"Topic connected to {paper.get('title')}",
            confidence=0.62,
            trust_score=0.58,
            status="evidence_backed",
            source_ids=[paper_id],
        )
        add_edge(conn, title_node, "connects_to", node_id, evidence_ids=[evidence_id], confidence=0.62, trust_score=0.58, status="evidence_backed")
        topic_nodes.append(node_id)
        log_change(conn, cs_id, "upsert_node", "knowledge_node", node_id, {"type": "Concept", "topic": topic_name})
        update_interest(conn, profile_id, topic_name, 0.08)

    # Claims: from model JSON or local fallback.
    claims = []
    for key in ["new_claims_or_updates", "core_claims", "claims", "claim_evidence_candidates"]:
        value = analysis.get(key)
        if isinstance(value, list):
            claims.extend(value)
    if not claims and analysis.get("one_sentence"):
        claims.append(analysis.get("one_sentence"))
    for claim in claims[:12]:
        if isinstance(claim, dict):
            claim_text = normalize_ws(claim.get("claim") or claim.get("content") or claim.get("update") or jdump(claim))
            conf = safe_float(claim.get("confidence"), 0.62)
        else:
            claim_text = normalize_ws(str(claim))
            conf = 0.6
        if not claim_text:
            continue
        claim_node = upsert_node(
            conn,
            "Claim",
            claim_text[:160],
            summary=claim_text,
            confidence=conf,
            trust_score=0.6,
            status="evidence_backed",
            source_ids=[paper_id],
        )
        add_edge(conn, title_node, "supports", claim_node, evidence_ids=[evidence_id], confidence=conf, trust_score=0.6, status="evidence_backed")
        create_atomic_unit(conn, paper_id, "claim", claim_text, [evidence_id], node_id=claim_node, confidence=conf)
        log_change(conn, cs_id, "create_atomic_unit", "claim", claim_node, {"claim": claim_text, "evidence_ids": [evidence_id]})

    # Insights/open questions stay metacognitive, not factual knowledge.
    next_actions = analysis.get("next_actions") if isinstance(analysis.get("next_actions"), list) else []
    open_questions = analysis.get("open_questions") if isinstance(analysis.get("open_questions"), list) else []
    risks = analysis.get("risks_and_caveats") if isinstance(analysis.get("risks_and_caveats"), list) else []
    meta_items = []
    for content, kind, conf in (
        [(q, "open_question", 0.55) for q in open_questions[:6]]
        + [(r, "caveat", 0.6) for r in risks[:6]]
        + [(a, "next_action", 0.52) for a in next_actions[:6]]
    ):
        text = normalize_ws(str(content))
        if not text:
            continue
        meta_id = stable_id("meta", profile_id or "global", kind, text[:260])
        conn.execute(
            """
            INSERT INTO metacognitive_items
            (id, profile_id, item_type, content, status, confidence, linked_node_ids_json,
             supporting_evidence_ids_json, counter_evidence_ids_json, next_actions_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, confidence=max(metacognitive_items.confidence, excluded.confidence)
            """,
            (
                meta_id,
                profile_id,
                kind,
                text,
                "hypothesis" if kind == "open_question" else "active",
                conf,
                jdump(topic_nodes[:5]),
                jdump([evidence_id]),
                jdump(next_actions[:3]),
                utcnow(),
                utcnow(),
            ),
        )
        meta_items.append(meta_id)
        log_change(conn, cs_id, "create_metacognitive_item", "metacognitive_item", meta_id, {"type": kind, "content": text})

    conn.commit()
    return {"change_set_id": cs_id, "evidence_ids": [evidence_id], "topic_node_ids": topic_nodes, "metacognitive_item_ids": meta_items}


# ---------------------------------------------------------------------------
# PDF and Zotero import
# ---------------------------------------------------------------------------


def read_pdf_or_text(path: str | None, max_chars: int = 12000) -> str:
    if not path:
        return ""
    if path.startswith("file://"):
        path = urllib.parse.urlparse(path).path
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return ""
    if p.suffix.lower() == ".pdf":
        for module_name in ["pypdf", "PyPDF2"]:
            try:
                if module_name == "pypdf":
                    from pypdf import PdfReader  # type: ignore
                else:
                    from PyPDF2 import PdfReader  # type: ignore
                reader = PdfReader(str(p))
                parts = []
                for page in reader.pages[:20]:
                    parts.append(page.extract_text() or "")
                    if sum(len(x) for x in parts) > max_chars:
                        break
                return normalize_ws("\n".join(parts))[:max_chars]
            except Exception:
                pass
    try:
        return normalize_ws(p.read_text(encoding="utf-8", errors="ignore"))[:max_chars]
    except Exception:
        try:
            return normalize_ws(p.read_bytes().decode("latin-1", errors="ignore"))[:max_chars]
        except Exception:
            return ""


def parse_ris(text: str, base_dir: Path | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    authors: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("TY  -") or line.startswith("TY -"):
            current = {"source": "zotero"}
            authors = []
            continue
        if line.startswith("ER  -") or line.startswith("ER -"):
            if current:
                current["authors"] = authors
                items.append(current)
            current = {}
            continue
        if len(line) < 6:
            continue
        tag = line[:2]
        value = line[5:].strip() if " - " in line[:6] else line[6:].strip()
        if tag == "TI":
            current["title"] = value
        elif tag == "AB":
            current["abstract"] = value
        elif tag == "AU":
            authors.append(value)
        elif tag == "PY":
            current["published_date"] = value[:4]
        elif tag == "DO":
            current["doi"] = value
        elif tag == "UR":
            current["url"] = value
        elif tag in {"L1", "L2", "N1"} and value.lower().endswith(".pdf"):
            current["pdf_url"] = resolve_zotero_path(value, base_dir)
    return items


def bib_entries(text: str) -> list[str]:
    entries: list[str] = []
    i = 0
    while True:
        start = text.find("@", i)
        if start < 0:
            break
        brace = text.find("{", start)
        if brace < 0:
            break
        depth = 0
        in_quote = False
        escaped = False
        j = brace
        while j < len(text):
            ch = text[j]
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"' and depth > 0:
                in_quote = not in_quote
            elif not in_quote:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        entries.append(text[start : j + 1])
                        i = j + 1
                        break
            j += 1
        else:
            entries.append(text[start:])
            break
    return entries


def parse_bib_fields(entry: str) -> dict[str, str]:
    open_brace = entry.find("{")
    close_brace = entry.rfind("}")
    if open_brace < 0 or close_brace <= open_brace:
        return {}
    body = entry[open_brace + 1 : close_brace]
    first_comma = body.find(",")
    if first_comma < 0:
        return {}
    text = body[first_comma + 1 :]
    fields: dict[str, str] = {}
    i = 0
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        key_start = i
        while i < len(text) and re.match(r"[A-Za-z0-9_\-]", text[i]):
            i += 1
        key = text[key_start:i].strip().lower()
        while i < len(text) and text[i].isspace():
            i += 1
        if not key or i >= len(text) or text[i] != "=":
            i += 1
            continue
        i += 1
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        if text[i] == "{":
            i += 1
            value_start = i
            depth = 1
            while i < len(text) and depth > 0:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            value = text[value_start:i]
            i += 1
        elif text[i] == '"':
            i += 1
            value_start = i
            escaped = False
            while i < len(text):
                if escaped:
                    escaped = False
                elif text[i] == "\\":
                    escaped = True
                elif text[i] == '"':
                    break
                i += 1
            value = text[value_start:i]
            i += 1
        else:
            value_start = i
            while i < len(text) and text[i] != ",":
                i += 1
            value = text[value_start:i]
        fields[key] = normalize_ws(value.replace("{", "").replace("}", ""))
    return fields


def extract_zotero_pdf_path(value: str) -> str | None:
    clean = urllib.parse.unquote(value)
    candidates = re.findall(r"(?:file://)?/[^:;{}]+?\.pdf|[^:;{}]*files/[^:;{}]+?\.pdf|[^:;{}]+?\.pdf", clean, flags=re.I)
    if not candidates:
        return None
    preferred = [c for c in candidates if "/" in c or c.startswith("file://")]
    return (preferred or candidates)[-1].strip()


def parse_bib(text: str, base_dir: Path | None = None) -> list[dict[str, Any]]:
    entries = bib_entries(text)
    items: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.strip():
            continue
        data: dict[str, Any] = {"source": "zotero"}
        fields = parse_bib_fields(entry)
        if fields.get("title"):
            data["title"] = fields["title"]
        if fields.get("doi"):
            data["doi"] = fields["doi"]
        if fields.get("author"):
            data["authors"] = [normalize_ws(a) for a in re.split(r"\s+and\s+", fields["author"]) if normalize_ws(a)]
        if fields.get("year"):
            data["published_date"] = fields["year"][:4]
        elif fields.get("date"):
            data["published_date"] = fields["date"][:4]
        if fields.get("abstract"):
            data["abstract"] = fields["abstract"]
        if fields.get("url"):
            data["url"] = fields["url"]
        if fields.get("file"):
            pdf = extract_zotero_pdf_path(fields["file"])
            if pdf:
                resolved = resolve_zotero_path(pdf, base_dir)
                data["pdf_url"] = resolved
                if not re.match(r"^https?://", resolved):
                    data["pdf_path"] = resolved
        if data.get("title"):
            data.setdefault("abstract", "")
            data.setdefault("authors", [])
            items.append(data)
    return items


def resolve_zotero_path(value: str, base_dir: Path | None) -> str:
    value = urllib.parse.unquote(value.strip())
    if value.startswith("file://") or re.match(r"^https?://", value):
        return value
    path = Path(value)
    if path.is_absolute():
        return str(path)
    if base_dir:
        return str((base_dir / value).resolve(strict=False))
    return value


def zotero_export_files(path: Path) -> list[Path]:
    suffixes = {".ris", ".bib", ".bibtex", ".json", ".csljson"}
    if path.is_dir():
        return sorted(f for f in path.rglob("*") if f.is_file() and f.suffix.lower() in suffixes)
    return [path] if path.is_file() and path.suffix.lower() in suffixes else []


def zotero_import_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise WorkerError(f"Zotero export path does not exist: {path}")
    if path.is_dir():
        items: list[dict[str, Any]] = []
        for f in zotero_export_files(path):
            items.extend(zotero_import_items(f))
        return items
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".ris":
        return parse_ris(text, path.parent)
    if path.suffix.lower() in {".bib", ".bibtex"}:
        return parse_bib(text, path.parent)
    if path.suffix.lower() in {".json", ".csljson"}:
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        items = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("title-short") or "Untitled Zotero item"
            authors = []
            for author in item.get("author") or []:
                if isinstance(author, dict):
                    authors.append(normalize_ws(" ".join([author.get("given", ""), author.get("family", "")])) or author.get("literal", ""))
            items.append(
                {
                    "source": "zotero",
                    "title": title,
                    "abstract": item.get("abstract") or "",
                    "authors": authors,
                    "doi": item.get("DOI") or item.get("doi"),
                    "url": item.get("URL") or item.get("url"),
                    "published_date": str(item.get("issued", {}).get("date-parts", [[""]])[0][0]) if isinstance(item.get("issued"), dict) else None,
                }
            )
        return items
    return []


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(seed_demo=bool(payload.get("seed_demo")))
    return success({"message": "initialized"})


def cmd_profile_list(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    return success({"profiles": list_profiles(db.conn)})


def cmd_profile_upsert(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    now = utcnow()
    profile_id = payload.get("id") or make_id("profile")
    existing = db.conn.execute("SELECT * FROM research_profiles WHERE id=?", (profile_id,)).fetchone()
    name = normalize_ws(payload.get("name")) or (existing["name"] if existing else "New Profile")
    weight = safe_float(payload.get("weight"), existing["weight"] if existing else 1.0)
    include_terms = payload.get("include_terms") if "include_terms" in payload else (jload(existing["include_terms_json"], []) if existing else [])
    exclude_terms = payload.get("exclude_terms") if "exclude_terms" in payload else (jload(existing["exclude_terms_json"], []) if existing else [])
    seed_papers = payload.get("seed_papers") if "seed_papers" in payload else (jload(existing["seed_papers_json"], []) if existing else [])
    watch_authors = payload.get("watch_authors") if "watch_authors" in payload else (jload(existing["watch_authors_json"], []) if existing else [])
    watch_labs = payload.get("watch_labs") if "watch_labs" in payload else (jload(existing["watch_labs_json"], []) if existing else [])
    arxiv_query = payload.get("arxiv_query") if "arxiv_query" in payload else (existing["arxiv_query"] if existing else "")
    biorxiv_query = payload.get("biorxiv_query") if "biorxiv_query" in payload else (existing["biorxiv_query"] if existing else "")
    db.conn.execute(
        """
        INSERT INTO research_profiles
        (id, name, weight, include_terms_json, exclude_terms_json, seed_papers_json, watch_authors_json,
         watch_labs_json, arxiv_query, biorxiv_query, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            weight=excluded.weight,
            include_terms_json=excluded.include_terms_json,
            exclude_terms_json=excluded.exclude_terms_json,
            seed_papers_json=excluded.seed_papers_json,
            watch_authors_json=excluded.watch_authors_json,
            watch_labs_json=excluded.watch_labs_json,
            arxiv_query=excluded.arxiv_query,
            biorxiv_query=excluded.biorxiv_query,
            updated_at=excluded.updated_at
        """,
        (
            profile_id,
            name,
            weight,
            jdump(include_terms or []),
            jdump(exclude_terms or []),
            jdump(seed_papers or []),
            jdump(watch_authors or []),
            jdump(watch_labs or []),
            arxiv_query or "",
            biorxiv_query or "",
            now,
            now,
        ),
    )
    event_id = log_event(db.conn, "research_direction_updated", actor="user", object_type="profile", object_id=profile_id, profile_id=profile_id, payload=payload, importance=0.85)
    for term in include_terms or []:
        update_interest(db.conn, profile_id, term, 0.07, event_id)
    db.conn.commit()
    row = db.conn.execute("SELECT * FROM research_profiles WHERE id=?", (profile_id,)).fetchone()
    return success({"message": "profile saved", "profile": row_to_profile(row)})


def cmd_profile_delete(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    profile_id = payload.get("id")
    if not profile_id:
        raise WorkerError("profile id is required")
    count = db.conn.execute("SELECT COUNT(*) AS c FROM research_profiles").fetchone()["c"]
    if count <= 1:
        return success({"message": "kept the last profile"})
    db.conn.execute("DELETE FROM paper_scores WHERE profile_id=?", (profile_id,))
    db.conn.execute("DELETE FROM paper_actions WHERE profile_id=?", (profile_id,))
    db.conn.execute("DELETE FROM memory_notes WHERE profile_id=?", (profile_id,))
    db.conn.execute("DELETE FROM interest_states WHERE profile_id=?", (profile_id,))
    db.conn.execute("DELETE FROM research_profiles WHERE id=?", (profile_id,))
    db.conn.commit()
    return success({"message": "profile deleted"})


def arxiv_search(query: str, limit: int) -> list[dict[str, Any]]:
    # Lightweight official API client. Fail closed; radar can still work locally.
    if not query:
        return []
    params = urllib.parse.urlencode({"search_query": query, "start": 0, "max_results": limit, "sortBy": "submittedDate", "sortOrder": "descending"})
    url = f"https://export.arxiv.org/api/query?{params}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            xml = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    entries = re.findall(r"<entry>(.*?)</entry>", xml, flags=re.S)
    out = []
    for entry in entries:
        title = normalize_ws(re.sub(r"<.*?>", "", re.search(r"<title>(.*?)</title>", entry, flags=re.S).group(1))) if re.search(r"<title>(.*?)</title>", entry, flags=re.S) else "Untitled"
        summary = normalize_ws(re.sub(r"<.*?>", "", re.search(r"<summary>(.*?)</summary>", entry, flags=re.S).group(1))) if re.search(r"<summary>(.*?)</summary>", entry, flags=re.S) else ""
        arxiv_id = None
        url_match = re.search(r"<id>(.*?)</id>", entry)
        url_value = url_match.group(1) if url_match else None
        if url_value:
            arxiv_id = url_value.rstrip("/").split("/")[-1]
        authors = [normalize_ws(a) for a in re.findall(r"<author>\s*<name>(.*?)</name>", entry, flags=re.S)]
        published = re.search(r"<published>(.*?)</published>", entry)
        pdf = None
        pdf_match = re.search(r'href="(https://arxiv.org/pdf/[^"]+)"', entry)
        if pdf_match:
            pdf = pdf_match.group(1)
        out.append({"source": "arxiv", "arxiv_id": arxiv_id, "title": title, "abstract": summary, "authors": authors, "published_date": (published.group(1)[:10] if published else None), "url": url_value, "pdf_url": pdf})
    return out


def cmd_ingest(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    inserted = updated = 0
    before = db.conn.execute("SELECT COUNT(*) AS c FROM papers").fetchone()["c"]
    if payload.get("demo"):
        db.seed_demo()
    else:
        limit = int(payload.get("limit") or 20)
        profile_ids = payload.get("profiles") or []
        profiles = list_profiles(db.conn)
        if profile_ids:
            profiles = [p for p in profiles if p["id"] in set(profile_ids)]
        seen = 0
        for profile in profiles:
            for item in arxiv_search(profile.get("arxiv_query") or " OR ".join(profile.get("include_terms", [])[:4]), max(5, limit // max(1, len(profiles)))):
                pid = upsert_paper(db.conn, item)
                ensure_paper_chunk(db.conn, pid, item.get("abstract") or "", source="abstract")
                event_id = log_event(db.conn, "radar_candidate_found", object_type="paper", object_id=pid, profile_id=profile["id"], payload={"source": item.get("source"), "query": profile.get("arxiv_query")}, importance=0.4)
                for term in profile.get("include_terms", [])[:4]:
                    if term.lower() in ((item.get("title") or "") + " " + (item.get("abstract") or "")).lower():
                        update_interest(db.conn, profile["id"], term, 0.03, event_id)
                seen += 1
                if seen >= limit:
                    break
    after = db.conn.execute("SELECT COUNT(*) AS c FROM papers").fetchone()["c"]
    inserted = max(0, after - before)
    db.conn.commit()
    db.rank_all(payload.get("profiles") or None)
    return success({"inserted": inserted, "updated": updated, "total": after, "errors": []})


def cmd_rank(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    profile_ids = payload.get("profile_ids") or payload.get("profiles")
    scored = db.rank_all(profile_ids)
    return success({"scored": scored})


def cmd_list_papers(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    profile_id = payload.get("profile_id") or None
    limit = int(payload.get("limit") or 50)
    if profile_id:
        rows = db.conn.execute(
            """
            SELECT p.* FROM papers p
            LEFT JOIN paper_scores s ON s.paper_id=p.id AND s.profile_id=?
            ORDER BY COALESCE(s.final_score, 0) DESC, COALESCE(p.published_date, p.updated_date, p.created_at) DESC
            LIMIT ?
            """,
            (profile_id, limit),
        ).fetchall()
    else:
        rows = db.conn.execute("SELECT * FROM papers ORDER BY COALESCE(published_date, updated_date, created_at) DESC LIMIT ?", (limit,)).fetchall()
    return success({"papers": [row_to_paper(db.conn, r, profile_id) for r in rows]})


def cmd_read_papers(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    profile_id = payload.get("profile_id") or None
    limit = int(payload.get("limit") or 200)
    if profile_id:
        rows = db.conn.execute(
            """
            SELECT DISTINCT p.* FROM papers p
            JOIN paper_actions a ON a.paper_id=p.id
            WHERE a.profile_id=? AND a.action IN ('read','save')
            ORDER BY a.created_at DESC LIMIT ?
            """,
            (profile_id, limit),
        ).fetchall()
    else:
        rows = db.conn.execute(
            """
            SELECT DISTINCT p.* FROM papers p
            JOIN paper_actions a ON a.paper_id=p.id
            WHERE a.action IN ('read','save')
            ORDER BY a.created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return success({"papers": [row_to_paper(db.conn, r, profile_id) for r in rows]})


def cmd_feedback(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    paper_id = payload.get("paper_id")
    profile_id = payload.get("profile_id") or db.ensure_default_profile()
    action = payload.get("action") or "like"
    if not paper_id:
        raise WorkerError("paper_id is required")
    now = utcnow()
    db.conn.execute(
        "INSERT OR REPLACE INTO paper_actions (profile_id, paper_id, action, created_at) VALUES (?, ?, ?, ?)",
        (profile_id, paper_id, action, now),
    )
    event_id = log_event(db.conn, "paper_feedback", actor="user", object_type="paper", object_id=paper_id, profile_id=profile_id, payload={"action": action}, importance=0.6 if action in {"like", "save", "read"} else 0.45)
    paper_row = db.conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if paper_row:
        text = (paper_row["title"] or "") + " " + (paper_row["abstract"] or "")
        profile_row = db.conn.execute("SELECT * FROM research_profiles WHERE id=?", (profile_id,)).fetchone()
        if profile_row:
            profile = row_to_profile(profile_row)
            for term in profile.get("include_terms", []):
                if term.lower() in text.lower():
                    update_interest(db.conn, profile_id, term, 0.08 if action in {"like", "save", "read"} else -0.08, event_id)
    db.conn.commit()
    db.rank_all([profile_id])
    return success({"message": "feedback saved"})


def cmd_search(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    query = normalize_ws(payload.get("query"))
    profile_id = payload.get("profile_id") or None
    limit = int(payload.get("limit") or 40)
    if not query:
        return success({"papers": []})
    if payload.get("live"):
        for item in arxiv_search(f'all:("{query}")', min(limit, 20)):
            pid = upsert_paper(db.conn, item)
            ensure_paper_chunk(db.conn, pid, item.get("abstract") or "", source="abstract")
    log_event(db.conn, "search_query", actor="user", object_type="query", object_id=stable_id("query", query), profile_id=profile_id, payload={"query": query, "mode": payload.get("mode"), "live": bool(payload.get("live"))}, importance=0.35)
    for term in tokenize(query)[:6]:
        update_interest(db.conn, profile_id, term, 0.025)
    db.conn.commit()
    tokens = tokenize(query)
    rows = db.conn.execute("SELECT * FROM papers").fetchall()
    scored = []
    for row in rows:
        paper = row_to_paper(db.conn, row, profile_id)
        text = ((paper["title"] or "") + " " + (paper["abstract"] or "")).lower()
        s = sum(1 for t in tokens if t in text)
        if s > 0:
            scored.append((s, paper))
    scored.sort(key=lambda x: (x[0], ((x[1].get("score") or {}).get("final_score") or 0.0)), reverse=True)
    return success({"papers": [p for _, p in scored[:limit]]})


def local_analysis(paper: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    text = (paper.get("title") or "") + " " + (paper.get("abstract") or "")
    matches = []
    if profile:
        _, matches = term_score(text, profile.get("include_terms", []))
    return {
        "one_sentence": first_sentence(paper.get("abstract"), f"{paper.get('title')} has no abstract."),
        "useful_for": matches[:6] or tokenize(paper.get("title"))[:4],
        "connects_to_memory": matches[:6],
        "new_claims_or_updates": [first_sentence(paper.get("abstract"), "No concrete claim can be extracted without text.")],
        "risks_and_caveats": ["Local triage only; no DeepSeek deep reading was performed."],
        "next_actions": ["Run deep usefulness reading with the reader API key before writing long-term memory."],
        "markdown": f"# Local triage: {paper.get('title')}\n\n{paper.get('abstract') or 'No abstract.'}",
    }


def cmd_analyze(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    paper_id = payload.get("paper_id")
    profile_id = payload.get("profile_id") or None
    if not paper_id:
        raise WorkerError("paper_id is required")
    row = db.conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if not row:
        raise WorkerError("paper not found")
    profile = None
    if profile_id:
        pr = db.conn.execute("SELECT * FROM research_profiles WHERE id=?", (profile_id,)).fetchone()
        profile = row_to_profile(pr) if pr else None
    analysis = local_analysis(row_to_paper(db.conn, row, profile_id), profile)
    db.conn.execute("UPDATE papers SET analysis_status=?, updated_at=? WHERE id=?", ("local_triage", utcnow(), paper_id))
    log_event(db.conn, "shallow_analysis", object_type="paper", object_id=paper_id, profile_id=profile_id, payload={"model": payload.get("model")}, importance=0.35, trust_score=0.45)
    db.conn.commit()
    return success({"status": "local_triage", "analysis": analysis})


def cmd_usefulness(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    api_key = get_reader_key()
    if not api_key:
        raise WorkerError("DeepSeek V4 Pro API key is required before writing long-term memory.")
    paper_id = payload.get("paper_id")
    profile_id = payload.get("profile_id") or db.ensure_default_profile()
    if not paper_id:
        raise WorkerError("paper_id is required")
    row = db.conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if not row:
        raise WorkerError("paper not found")
    paper = row_to_paper(db.conn, row, profile_id)
    profile_row = db.conn.execute("SELECT * FROM research_profiles WHERE id=?", (profile_id,)).fetchone()
    profile = row_to_profile(profile_row) if profile_row else None
    existing_notes = [row_to_memory(r, include_content=False) for r in db.conn.execute("SELECT * FROM memory_notes WHERE profile_id=? ORDER BY updated_at DESC LIMIT 12", (profile_id,)).fetchall()]
    prompt = load_prompt("paper_usefulness.md", "Return strict JSON for paper usefulness and memory update.")
    model = payload.get("model") or DEFAULT_READER_MODEL
    content = {
        "profile": profile,
        "paper": paper,
        "existing_memory_notes": existing_notes,
        "instruction": "Return strict JSON only. Separate facts from hypotheses. Do not create claims without evidence from supplied text.",
    }
    text = call_deepseek(
        model=model,
        api_key=api_key,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(content, ensure_ascii=False)}],
        timeout=150,
        thinking="enabled",
        reasoning_effort="high",
    )
    analysis = parse_json_text(text)
    markdown = analysis.get("markdown") or f"# Usefulness: {paper['title']}\n\n{analysis.get('one_sentence', '')}"
    note_id = stable_id("note", profile_id, "paper_usefulness", paper_id)
    now = utcnow()
    path = None
    if payload.get("obsidian_path"):
        path = write_obsidian_note(Path(payload["obsidian_path"]), f"Memory/Usefulness-{sanitize_filename(paper['title'])}.md", markdown)
    db.conn.execute(
        """
        INSERT INTO memory_notes
        (id, profile_id, type, title, markdown_path, content, metadata_json, created_at, updated_at)
        VALUES (?, ?, 'paper_usefulness', ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET content=excluded.content, markdown_path=excluded.markdown_path, metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
        """,
        (note_id, profile_id, f"Usefulness: {paper['title']}", path, markdown, jdump({"paper_id": paper_id, "analysis": analysis}), now, now),
    )
    for action in ["save", "read"]:
        db.conn.execute("INSERT OR IGNORE INTO paper_actions (profile_id, paper_id, action, created_at) VALUES (?, ?, ?, ?)", (profile_id, paper_id, action, now))
    trace = extract_structured_memory(db.conn, profile_id, paper, analysis, model)
    db.conn.execute("UPDATE papers SET analysis_status=?, updated_at=? WHERE id=?", ("deep_read", utcnow(), paper_id))
    db.conn.commit()
    db.rank_all([profile_id])
    analysis["memory_trace"] = trace
    return success({"status": "deep_read", "analysis": analysis})


def cmd_synthesize(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    api_key = get_reader_key()
    if not api_key:
        raise WorkerError("DeepSeek V4 Pro API key is required before writing long-term memory.")
    profile_id = payload.get("profile_id") or db.ensure_default_profile()
    model = payload.get("model") or DEFAULT_READER_MODEL
    notes = [row_to_memory(r, True) for r in db.conn.execute("SELECT * FROM memory_notes WHERE profile_id=? ORDER BY updated_at DESC LIMIT 24", (profile_id,)).fetchall()]
    dashboard = build_dashboard(db.conn, profile_id)
    prompt = "You synthesize a weekly research memory digest. Return strict JSON with markdown, open_questions, reading_priorities, and methodology_updates."
    text = call_deepseek(
        model=model,
        api_key=api_key,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": jdump({"notes": notes, "dashboard": dashboard})}],
        timeout=150,
        thinking="enabled",
        reasoning_effort="high",
    )
    data = parse_json_text(text)
    markdown = data.get("markdown") or "# Weekly Research Memory Digest\n\nNo synthesis returned."
    now = utcnow()
    note_id = stable_id("note", profile_id, payload.get("type") or "weekly_digest", now[:10])
    path = None
    if payload.get("obsidian_path"):
        path = write_obsidian_note(Path(payload["obsidian_path"]), f"Memory/Weekly-{now[:10]}.md", markdown)
    db.conn.execute(
        """
        INSERT INTO memory_notes
        (id, profile_id, type, title, markdown_path, content, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (note_id, profile_id, payload.get("type") or "weekly_digest", f"Weekly Research Memory Digest {now[:10]}", path, markdown, jdump(data), now, now),
    )
    db.conn.commit()
    notes = [row_to_memory(r, False) for r in db.conn.execute("SELECT * FROM memory_notes WHERE profile_id=? ORDER BY updated_at DESC", (profile_id,)).fetchall()]
    return success({"notes": notes})


def cmd_memory_list(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    profile_id = payload.get("profile_id") or None
    include_content = bool(payload.get("include_content", True))
    if profile_id:
        rows = db.conn.execute("SELECT * FROM memory_notes WHERE profile_id=? ORDER BY updated_at DESC", (profile_id,)).fetchall()
    else:
        rows = db.conn.execute("SELECT * FROM memory_notes ORDER BY updated_at DESC").fetchall()
    return success({"notes": [row_to_memory(r, include_content=include_content) for r in rows]})


def cmd_memory_get(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    note_id = payload.get("id")
    row = db.conn.execute("SELECT * FROM memory_notes WHERE id=?", (note_id,)).fetchone()
    if not row:
        raise WorkerError("memory note not found")
    return success({"note": row_to_memory(row, include_content=True)})


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9\-_\.\u4e00-\u9fff]+", "-", name).strip("-")
    return safe[:90] or "note"


def write_obsidian_note(root: Path, relative: str, content: str) -> str:
    path = root.expanduser() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def cmd_export(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    export_format = payload.get("format") or "obsidian"
    profile_id = payload.get("profile_id") or db.ensure_default_profile()
    root = Path(payload.get("path") or (Path.home() / "Documents" / "LiteratureRadarExport")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    if export_format == "obsidian":
        profile_row = db.conn.execute("SELECT * FROM research_profiles WHERE id=?", (profile_id,)).fetchone()
        profile = row_to_profile(profile_row) if profile_row else {}
        files.append(write_obsidian_note(root, f"Profiles/{sanitize_filename(profile.get('name','Profile'))}.md", "# Research Profile\n\n```json\n" + json.dumps(profile, ensure_ascii=False, indent=2) + "\n```\n"))
        for r in db.conn.execute("SELECT * FROM memory_notes WHERE profile_id=? ORDER BY updated_at DESC", (profile_id,)).fetchall():
            note = row_to_memory(r, True)
            files.append(write_obsidian_note(root, f"Memory/{sanitize_filename(note['title'])}.md", note["content"]))
        dashboard = build_dashboard(db.conn, profile_id)
        files.append(write_obsidian_note(root, "MemoryOS/Dashboard.json.md", "# Memory OS Dashboard\n\n```json\n" + json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n```\n"))
    elif export_format == "zotero":
        rows = db.conn.execute("SELECT * FROM papers ORDER BY published_date DESC, created_at DESC").fetchall()
        papers = [row_to_paper(db.conn, r, profile_id) for r in rows]
        ris = root / "literature-radar.ris"
        bib = root / "literature-radar.bib"
        js = root / "literature-radar.json"
        ris.write_text(render_ris(papers), encoding="utf-8")
        bib.write_text(render_bib(papers), encoding="utf-8")
        js.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
        files = [str(ris), str(bib), str(js)]
        now = utcnow()
        for p in papers:
            db.conn.execute("INSERT OR REPLACE INTO paper_exports (paper_id, export_type, path, created_at) VALUES (?, 'zotero', ?, ?)", (p["id"], str(ris), now))
        db.conn.commit()
    else:
        raise WorkerError("unsupported export format")
    return success({"files": files})


def render_ris(papers: list[dict[str, Any]]) -> str:
    lines = []
    for p in papers:
        lines.append("TY  - JOUR")
        lines.append(f"TI  - {p['title']}")
        for a in p.get("authors") or []:
            lines.append(f"AU  - {a}")
        if p.get("published_date"):
            lines.append(f"PY  - {p['published_date'][:4]}")
        if p.get("doi"):
            lines.append(f"DO  - {p['doi']}")
        if p.get("url"):
            lines.append(f"UR  - {p['url']}")
        if p.get("abstract"):
            lines.append(f"AB  - {p['abstract']}")
        lines.append("ER  - ")
    return "\n".join(lines) + "\n"


def render_bib(papers: list[dict[str, Any]]) -> str:
    entries = []
    for p in papers:
        key = sanitize_filename((p.get("authors") or ["paper"])[0].split()[-1] + (p.get("published_date") or "")[:4] + p["id"][-4:])
        authors = " and ".join(p.get("authors") or [])
        entries.append(textwrap.dedent(f"""
        @article{{{key},
          title = {{{p['title']}}},
          author = {{{authors}}},
          year = {{{(p.get('published_date') or '')[:4]}}},
          doi = {{{p.get('doi') or ''}}},
          url = {{{p.get('url') or ''}}},
        }}
        """).strip())
    return "\n\n".join(entries) + "\n"


def cmd_profile_from_description(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    progress_path = payload.get("progress_path")
    write_progress(progress_path, "preparing", 0, 3, "Preparing profile generation")
    api_key = get_flash_key()
    if not api_key:
        write_progress(progress_path, "failed", 0, 3, "Profile generation failed.", "DeepSeek V4 Flash API key is required for profile generation.")
        raise WorkerError("DeepSeek V4 Flash API key is required for profile generation.")
    desc = normalize_ws(payload.get("description"))
    if not desc:
        write_progress(progress_path, "failed", 0, 3, "Profile generation failed.", "description is required")
        raise WorkerError("description is required")
    prompt = load_prompt("profile_from_description.md", "Convert natural language research direction to strict JSON search profile.")
    model = payload.get("model") or DEFAULT_FLASH_MODEL
    write_progress(progress_path, "calling_llm", 1, 3, "Calling DeepSeek V4 Flash", model)
    text = call_deepseek(
        model=model,
        api_key=api_key,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": desc}],
        timeout=90,
        thinking="disabled",
    )
    data = parse_json_text(text)
    write_progress(progress_path, "saving", 2, 3, "Saving generated profile", data.get("name") or "Generated Profile")
    save_payload = {
        "name": data.get("name") or "Generated Profile",
        "weight": 1.0,
        "include_terms": data.get("include_terms") or [],
        "exclude_terms": data.get("exclude_terms") or [],
        "watch_authors": data.get("watch_authors") or [],
        "watch_labs": data.get("watch_labs") or [],
        "seed_papers": data.get("seed_papers") or [],
        "arxiv_query": data.get("arxiv_query") or "",
        "biorxiv_query": data.get("biorxiv_query") or "",
    }
    result = cmd_profile_upsert(db, save_payload)
    result["message"] = data.get("rationale") or "Generated profile"
    write_progress(progress_path, "done", 3, 3, "Generated profile", result.get("profile", {}).get("name"))
    return result


def cmd_zotero_import(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    path = payload.get("path")
    progress_path = payload.get("progress_path")
    if not path:
        raise WorkerError("path is required")
    source_path = Path(path).expanduser()
    write_progress(progress_path, "scanning", 0, 0, "Scanning Zotero export", str(source_path))
    files = zotero_export_files(source_path)
    if not files:
        write_progress(progress_path, "failed", 0, 0, "No Zotero items found in the selected path.", str(source_path))
        raise WorkerError("No Zotero items found in the selected path. Choose a BibTeX, RIS, CSL JSON file, or the folder that contains one.")
    items: list[dict[str, Any]] = []
    for idx, file_path in enumerate(files, start=1):
        write_progress(progress_path, "parsing", idx - 1, len(files), "Parsing Zotero export", str(file_path))
        items.extend(zotero_import_items(file_path))
        write_progress(progress_path, "parsing", idx, len(files), "Parsing Zotero export", str(file_path))
    if not items:
        write_progress(progress_path, "failed", 0, 0, "No Zotero items found in the selected path.", str(source_path))
        raise WorkerError("No Zotero items found in the selected path. Choose a BibTeX, RIS, CSL JSON file, or the folder that contains one.")
    papers = []
    seen_paper_ids: set[str] = set()
    for idx, item in enumerate(items, start=1):
        item.setdefault("abstract", "")
        write_progress(progress_path, "reading_pdfs", idx - 1, len(items), "Reading Zotero PDFs", item.get("title"))
        pid = upsert_paper(db.conn, item)
        text = item.get("abstract") or read_pdf_or_text(item.get("pdf_url"), 2000)
        ensure_paper_chunk(db.conn, pid, text, source="zotero")
        if pid not in seen_paper_ids:
            row = db.conn.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
            papers.append(row_to_paper(db.conn, row))
            seen_paper_ids.add(pid)
        write_progress(progress_path, "reading_pdfs", idx, len(items), "Reading Zotero PDFs", item.get("title"))
    write_progress(progress_path, "saving", len(papers), len(items), "Saving imported papers", str(source_path))
    db.conn.commit()
    write_progress(progress_path, "done", len(papers), len(papers), "Zotero import complete.", str(source_path))
    return success({"count": len(papers), "papers": papers})


def write_progress(path: str | None, phase: str, current: int, total: int, message: str, detail: str | None = None) -> None:
    if not path:
        return
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"phase": phase, "current": current, "completed": current, "total": total, "message": message, "detail": detail, "updated_at": utcnow()}, ensure_ascii=False), encoding="utf-8")


def cmd_integrate_papers(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    paper_ids = payload.get("paper_ids") or []
    profile_id = payload.get("profile_id") or db.ensure_default_profile()
    progress_path = payload.get("progress_path")
    total = len(paper_ids)
    write_progress(progress_path, "preparing", 0, total, "Preparing long-term memory integration")
    api_key = get_reader_key()
    if not api_key:
        write_progress(progress_path, "failed", 0, total, "Long-term memory integration failed.", "DeepSeek V4 Pro API key is required before writing long-term memory.")
        raise WorkerError("DeepSeek V4 Pro API key is required before writing long-term memory.")
    model = payload.get("model") or DEFAULT_READER_MODEL
    papers = []
    for i, pid in enumerate(paper_ids, start=1):
        row = db.conn.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
        if not row:
            continue
        paper = row_to_paper(db.conn, row, profile_id)
        write_progress(progress_path, "reading_pdfs", i - 1, total, "Reading PDFs before LLM synthesis", paper.get("title"))
        pdf_text = read_pdf_or_text(paper.get("pdf_url"), max_chars=9000)
        paper["pdf_excerpt"] = pdf_text or paper.get("abstract") or ""
        papers.append(paper)
        write_progress(progress_path, "reading_pdfs", i, total, "Reading PDFs before LLM synthesis", paper.get("title"))
    prompt = load_prompt("zotero_batch_synthesis.md", "Integrate papers into strict JSON layered memory.")
    write_progress(progress_path, "calling_llm", 0, 0, "Calling DeepSeek V4 Pro", f"{len(papers)} papers")
    text = call_deepseek(
        model=model,
        api_key=api_key,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": jdump({"papers": papers, "profile_id": profile_id})}],
        timeout=300,
        thinking="enabled",
        reasoning_effort="high",
    )
    analysis = parse_json_text(text)
    markdown = analysis.get("markdown") or "# Zotero Integration\n\nNo markdown returned."
    now = utcnow()
    note_id = stable_id("note", profile_id, "zotero_integration", ",".join(paper_ids), now[:10])
    path = None
    if payload.get("obsidian_path"):
        path = write_obsidian_note(Path(payload["obsidian_path"]), f"Memory/Zotero-Integration-{now[:10]}.md", markdown)
    db.conn.execute(
        """
        INSERT INTO memory_notes
        (id, profile_id, type, title, markdown_path, content, metadata_json, created_at, updated_at)
        VALUES (?, ?, 'zotero_integration', ?, ?, ?, ?, ?, ?)
        """,
        (note_id, profile_id, f"Zotero Integration: {now[:10]}", path, markdown, jdump(analysis), now, now),
    )
    for idx, paper in enumerate(papers, start=1):
        write_progress(progress_path, "writing_memory", idx - 1, max(1, len(papers)), "Writing memory graph", paper.get("title"))
        for action in ["save", "read"]:
            db.conn.execute("INSERT OR IGNORE INTO paper_actions (profile_id, paper_id, action, created_at) VALUES (?, ?, ?, ?)", (profile_id, paper["id"], action, now))
        per_paper_analysis = local_analysis(paper, None)
        # Merge batch-level hints so every paper produces graph/evidence nodes.
        per_paper_analysis.update({k: analysis.get(k) for k in ["shared_threads", "claim_evidence_candidates", "open_questions"] if k in analysis})
        extract_structured_memory(db.conn, profile_id, paper, per_paper_analysis, model)
        write_progress(progress_path, "writing_memory", idx, max(1, len(papers)), "Writing memory graph", paper.get("title"))
    db.conn.commit()
    db.rank_all([profile_id])
    write_progress(progress_path, "done", total, total, "Long-term memory integration complete.")
    rows = db.conn.execute("SELECT * FROM memory_notes WHERE profile_id=? ORDER BY updated_at DESC", (profile_id,)).fetchall()
    return success({"notes": [row_to_memory(r, include_content=False) for r in rows]})


# ---------------------------------------------------------------------------
# New Research Memory OS commands
# ---------------------------------------------------------------------------


def build_dashboard(conn: sqlite3.Connection, profile_id: str | None) -> dict[str, Any]:
    counts = {}
    for table in [
        "papers",
        "memory_notes",
        "evidence_spans",
        "episodic_events",
        "knowledge_nodes",
        "knowledge_edges",
        "atomic_knowledge_units",
        "metacognitive_items",
        "methodology_rules",
        "interest_states",
        "memory_change_sets",
        "review_queue",
        "taxonomy_versions",
        "context_packets",
    ]:
        counts[table] = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    interests = [dict(r) for r in conn.execute(
        "SELECT topic, intensity, positive_signal_count, negative_signal_count, last_activated_at FROM interest_states WHERE profile_id IS ? OR profile_id=? ORDER BY intensity DESC LIMIT 12",
        (profile_id, profile_id),
    ).fetchall()]
    recent_events = [
        {"event_type": r["event_type"], "object_type": r["object_type"], "object_id": r["object_id"], "occurred_at": r["occurred_at"], "importance": r["importance"]}
        for r in conn.execute("SELECT * FROM episodic_events ORDER BY occurred_at DESC LIMIT 10").fetchall()
    ]
    node_types = [dict(r) for r in conn.execute("SELECT type, COUNT(*) AS count FROM knowledge_nodes GROUP BY type ORDER BY count DESC").fetchall()]
    pending_review = conn.execute("SELECT COUNT(*) AS c FROM review_queue WHERE status='pending'").fetchone()["c"]
    health = memory_health(conn)
    return {"counts": counts, "interests": interests, "recent_events": recent_events, "node_types": node_types, "pending_review": pending_review, "health": health}


def cmd_memory_dashboard(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    return success({"dashboard": build_dashboard(db.conn, payload.get("profile_id") or None)})


def build_taxonomy(conn: sqlite3.Connection, profile_id: str | None) -> dict[str, Any]:
    concepts = [dict(r) for r in conn.execute("SELECT * FROM knowledge_nodes WHERE type IN ('Concept','Method','Problem','Task') ORDER BY confidence DESC, updated_at DESC LIMIT 80").fetchall()]
    claims = [dict(r) for r in conn.execute("SELECT * FROM knowledge_nodes WHERE type='Claim' ORDER BY confidence DESC, updated_at DESC LIMIT 60").fetchall()]
    papers = [dict(r) for r in conn.execute("SELECT * FROM knowledge_nodes WHERE type='Paper' ORDER BY updated_at DESC LIMIT 50").fetchall()]
    interests = [dict(r) for r in conn.execute("SELECT * FROM interest_states WHERE profile_id IS ? OR profile_id=? ORDER BY intensity DESC LIMIT 20", (profile_id, profile_id)).fetchall()]
    children = []
    for item in interests:
        topic = item["topic"]
        linked_concepts = [n for n in concepts if topic.lower() in n["canonical_name"].lower() or n["canonical_name"].lower() in topic.lower()]
        children.append({
            "title": topic,
            "kind": "interest_topic",
            "intensity": item["intensity"],
            "children": [
                {"title": n["canonical_name"], "kind": n["type"], "confidence": n["confidence"]}
                for n in linked_concepts[:8]
            ],
        })
    if not children:
        by_type: dict[str, list[dict[str, Any]]] = {}
        for n in concepts:
            by_type.setdefault(n["type"], []).append(n)
        children = [
            {"title": node_type, "kind": "node_type", "children": [{"title": n["canonical_name"], "kind": n["type"], "confidence": n["confidence"]} for n in nodes[:12]]}
            for node_type, nodes in by_type.items()
        ]
    tree = {
        "title": "Research Memory OS",
        "kind": "root",
        "children": children,
        "claim_count": len(claims),
        "paper_count": len(papers),
    }
    return tree


def cmd_mind_map(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    profile_id = payload.get("profile_id") or None
    tree = build_taxonomy(db.conn, profile_id)
    nodes = [
        {"id": r["id"], "type": r["type"], "name": r["canonical_name"], "summary": r["summary"], "confidence": r["confidence"], "status": r["status"]}
        for r in db.conn.execute("SELECT * FROM knowledge_nodes ORDER BY updated_at DESC LIMIT 200").fetchall()
    ]
    edges = [
        {"id": r["id"], "source": r["source_node_id"], "relation": r["relation_type"], "target": r["target_node_id"], "confidence": r["confidence"], "status": r["status"]}
        for r in db.conn.execute("SELECT * FROM knowledge_edges ORDER BY updated_at DESC LIMIT 300").fetchall()
    ]
    insights = [
        {"id": r["id"], "type": r["item_type"], "content": r["content"], "status": r["status"], "confidence": r["confidence"]}
        for r in db.conn.execute("SELECT * FROM metacognitive_items WHERE profile_id IS ? OR profile_id=? ORDER BY updated_at DESC LIMIT 40", (profile_id, profile_id)).fetchall()
    ]
    return success({"tree": tree, "nodes": nodes, "edges": edges, "insights": insights})


def assemble_context_packet(conn: sqlite3.Connection, profile_id: str | None, task: str, query: str) -> tuple[dict[str, Any], dict[str, Any]]:
    qtokens = set(tokenize(query))
    profile = None
    if profile_id:
        pr = conn.execute("SELECT * FROM research_profiles WHERE id=?", (profile_id,)).fetchone()
        profile = row_to_profile(pr) if pr else None
    nodes = []
    for r in conn.execute("SELECT * FROM knowledge_nodes ORDER BY confidence DESC, updated_at DESC LIMIT 200").fetchall():
        name = (r["canonical_name"] + " " + r["summary"]).lower()
        score = sum(1 for t in qtokens if t in name)
        if score or not qtokens:
            nodes.append({"id": r["id"], "type": r["type"], "name": r["canonical_name"], "summary": r["summary"], "confidence": r["confidence"], "score": score})
    nodes = sorted(nodes, key=lambda x: (x["score"], x["confidence"]), reverse=True)[:20]
    evidence = [
        {"id": r["id"], "paper_id": r["paper_id"], "section": r["section"], "quote": r["raw_quote"][:420]}
        for r in conn.execute("SELECT * FROM evidence_spans ORDER BY created_at DESC LIMIT 20").fetchall()
    ]
    episodes = [
        {"event_type": r["event_type"], "object_id": r["object_id"], "payload": jload(r["payload_json"], {}), "occurred_at": r["occurred_at"]}
        for r in conn.execute("SELECT * FROM episodic_events WHERE profile_id IS ? OR profile_id=? ORDER BY occurred_at DESC LIMIT 12", (profile_id, profile_id)).fetchall()
    ]
    methodology = [
        {"rule": r["rule"], "applies_to": jload(r["applies_to_json"], []), "confidence": r["confidence"]}
        for r in conn.execute("SELECT * FROM methodology_rules WHERE profile_id IS ? OR profile_id=? ORDER BY confidence DESC LIMIT 10", (profile_id, profile_id)).fetchall()
    ]
    meta = [
        {"type": r["item_type"], "content": r["content"], "status": r["status"], "confidence": r["confidence"]}
        for r in conn.execute("SELECT * FROM metacognitive_items WHERE profile_id IS ? OR profile_id=? ORDER BY updated_at DESC LIMIT 12", (profile_id, profile_id)).fetchall()
    ]
    packet = {
        "task": task,
        "query": query,
        "active_research_direction": profile,
        "semantic_context": nodes,
        "evidence_context": evidence,
        "episodic_context": episodes,
        "methodology_context": methodology,
        "metacognitive_context": meta,
        "forbidden_assumptions": ["Do not treat skim/search events as validated facts.", "Do not cite claims without evidence IDs when writing long-term knowledge."],
    }
    retrieved = {"nodes": [n["id"] for n in nodes], "evidence": [e["id"] for e in evidence], "episodes": episodes[:3]}
    return packet, retrieved


def cmd_context_packet(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    profile_id = payload.get("profile_id") or None
    task = payload.get("task") or "answer_question"
    query = normalize_ws(payload.get("query"))
    packet, retrieved = assemble_context_packet(db.conn, profile_id, task, query)
    packet_id = make_id("ctx")
    db.conn.execute("INSERT INTO context_packets (id, profile_id, task, query, packet_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (packet_id, profile_id, task, query, jdump(packet), utcnow()))
    trace_id = make_id("trace")
    db.conn.execute("INSERT INTO retrieval_traces (id, context_packet_id, query, retrieved_json, used_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (trace_id, packet_id, query, jdump(retrieved), jdump({"used_in_prompt": True}), utcnow()))
    db.conn.commit()
    return success({"context_packet_id": packet_id, "retrieval_trace_id": trace_id, "packet": packet})


def memory_health(conn: sqlite3.Connection) -> dict[str, Any]:
    unbacked_claims = conn.execute("SELECT COUNT(*) AS c FROM atomic_knowledge_units WHERE unit_type='claim' AND (evidence_ids_json='[]' OR evidence_ids_json IS NULL)").fetchone()["c"]
    orphan_edges = conn.execute(
        """
        SELECT COUNT(*) AS c FROM knowledge_edges e
        LEFT JOIN knowledge_nodes s ON s.id=e.source_node_id
        LEFT JOIN knowledge_nodes t ON t.id=e.target_node_id
        WHERE s.id IS NULL OR t.id IS NULL
        """
    ).fetchone()["c"]
    pending_review = conn.execute("SELECT COUNT(*) AS c FROM review_queue WHERE status='pending'").fetchone()["c"]
    draft_nodes = conn.execute("SELECT COUNT(*) AS c FROM knowledge_nodes WHERE status='draft'").fetchone()["c"]
    score = 1.0
    score -= min(0.35, unbacked_claims * 0.03)
    score -= min(0.25, orphan_edges * 0.04)
    score -= min(0.2, pending_review * 0.02)
    score -= min(0.15, draft_nodes * 0.005)
    return {"score": round(clamp(score), 3), "unbacked_claims": unbacked_claims, "orphan_edges": orphan_edges, "pending_review": pending_review, "draft_nodes": draft_nodes}


def cmd_repair_memory(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    before = memory_health(db.conn)
    repaired = []
    if payload.get("apply"):
        db.conn.execute(
            """
            DELETE FROM knowledge_edges
            WHERE source_node_id NOT IN (SELECT id FROM knowledge_nodes)
               OR target_node_id NOT IN (SELECT id FROM knowledge_nodes)
            """
        )
        repaired.append("removed_orphan_edges")
        db.conn.execute("UPDATE atomic_knowledge_units SET status='needs_review' WHERE unit_type='claim' AND (evidence_ids_json='[]' OR evidence_ids_json IS NULL)")
        repaired.append("flagged_unbacked_claims")
        db.conn.commit()
    after = memory_health(db.conn)
    return success({"before": before, "after": after, "repaired": repaired})


def cmd_review_list(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    rows = db.conn.execute("SELECT * FROM review_queue ORDER BY created_at DESC LIMIT ?", (int(payload.get("limit") or 100),)).fetchall()
    items = [
        {"id": r["id"], "change_set_id": r["change_set_id"], "item": jload(r["item_json"], {}), "risk_level": r["risk_level"], "status": r["status"], "created_at": r["created_at"], "resolved_at": r["resolved_at"]}
        for r in rows
    ]
    return success({"items": items})


def cmd_rebuild_taxonomy(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    db.init(False)
    profile_id = payload.get("profile_id") or None
    tree = build_taxonomy(db.conn, profile_id)
    title = f"Knowledge Tree {utcnow()[:10]}"
    markdown = render_tree_markdown(tree)
    version_id = make_id("tax")
    db.conn.execute("INSERT INTO taxonomy_versions (id, profile_id, title, tree_json, markdown, status, source_snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)", (version_id, profile_id, title, jdump(tree), markdown, jdump(build_dashboard(db.conn, profile_id).get("counts")), utcnow()))
    db.conn.commit()
    return success({"taxonomy_version_id": version_id, "tree": tree, "markdown": markdown})


def render_tree_markdown(node: dict[str, Any], level: int = 0) -> str:
    prefix = "  " * level + "- "
    line = prefix + str(node.get("title") or node.get("name") or "Untitled")
    lines = [line]
    for child in node.get("children") or []:
        lines.append(render_tree_markdown(child, level + 1))
    return "\n".join(lines)


COMMANDS = {
    "init": cmd_init,
    "profile-list": cmd_profile_list,
    "profile-upsert": cmd_profile_upsert,
    "profile-delete": cmd_profile_delete,
    "profile-from-description": cmd_profile_from_description,
    "ingest": cmd_ingest,
    "rank": cmd_rank,
    "list-papers": cmd_list_papers,
    "read-papers": cmd_read_papers,
    "search": cmd_search,
    "feedback": cmd_feedback,
    "analyze": cmd_analyze,
    "usefulness": cmd_usefulness,
    "synthesize": cmd_synthesize,
    "memory-list": cmd_memory_list,
    "memory-get": cmd_memory_get,
    "export": cmd_export,
    "zotero-import": cmd_zotero_import,
    "integrate-papers": cmd_integrate_papers,
    "memory-dashboard": cmd_memory_dashboard,
    "mind-map": cmd_mind_map,
    "context-packet": cmd_context_packet,
    "repair-memory": cmd_repair_memory,
    "review-list": cmd_review_list,
    "rebuild-taxonomy": cmd_rebuild_taxonomy,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LiteratureRadar local worker")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args(argv)
    try:
        payload = read_stdin_json()
        db = Database(Path(args.db).expanduser())
        try:
            result = COMMANDS[args.command](db, payload)
        finally:
            db.close()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        err = {"ok": False, "error": str(exc), "type": exc.__class__.__name__}
        if os.environ.get("LITRADAR_DEBUG"):
            err["traceback"] = traceback.format_exc()
        print(json.dumps(err, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
