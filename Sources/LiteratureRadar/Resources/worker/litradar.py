#!/usr/bin/env python3
"""Local-first literature radar worker.

The SwiftUI app talks to this script with JSON over stdin/stdout. The worker is
kept dependency-free on purpose so the first version can run on a clean macOS
machine with only Python 3.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time
from typing import Any
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET


APP_NAME = "LiteratureRadar"
KEYCHAIN_READER_SERVICE = "LiteratureRadarDeepSeekReaderAPIKey"
KEYCHAIN_FLASH_SERVICE = "LiteratureRadarDeepSeekFlashAPIKey"
KEYCHAIN_LEGACY_SERVICE = "LiteratureRadarDeepSeekAPIKey"
KEYCHAIN_ACCOUNT = "default"
USER_AGENT = "LiteratureRadar/0.1 (local research app; official APIs only)"
ACTIONS = {"save", "read", "like", "dislike", "not_relevant"}
NOTE_TYPES = {"overview", "claims", "open_questions", "weekly_digest"}


def default_db_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / APP_NAME
        / "literature_radar.sqlite3"
    )


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return dt.date.today().isoformat()


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def write_progress(
    progress_path: str | None,
    phase: str,
    current: int,
    total: int,
    message: str,
    detail: str | None = None,
) -> None:
    if not progress_path:
        return
    payload = {
        "phase": phase,
        "current": max(0, int(current)),
        "total": max(0, int(total)),
        "message": message,
        "detail": detail,
        "updated_at": now_iso(),
    }
    try:
        path = Path(progress_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        pass


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi
            ON papers(doi) WHERE doi IS NOT NULL AND doi != '';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_arxiv
            ON papers(arxiv_id) WHERE arxiv_id IS NOT NULL AND arxiv_id != '';

        CREATE TABLE IF NOT EXISTS research_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
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

        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            profile_id TEXT NOT NULL REFERENCES research_profiles(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(paper_id, profile_id, action)
        );

        CREATE TABLE IF NOT EXISTS paper_scores (
            profile_id TEXT NOT NULL REFERENCES research_profiles(id) ON DELETE CASCADE,
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            bm25_score REAL NOT NULL DEFAULT 0,
            embedding_score REAL NOT NULL DEFAULT 0,
            rule_score REAL NOT NULL DEFAULT 0,
            final_score REAL NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(profile_id, paper_id)
        );

        CREATE TABLE IF NOT EXISTS memory_notes (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES research_profiles(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            markdown_path TEXT,
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_analyses (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            profile_id TEXT NOT NULL REFERENCES research_profiles(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            json_content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_exports (
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            target TEXT NOT NULL,
            path TEXT NOT NULL,
            exported_at TEXT NOT NULL,
            PRIMARY KEY(paper_id, target)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    ensure_column(conn, "research_profiles", "arxiv_query", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "research_profiles", "biorxiv_query", "TEXT NOT NULL DEFAULT ''")
    count = conn.execute("SELECT COUNT(*) AS n FROM research_profiles").fetchone()["n"]
    if count == 0:
        upsert_profile(
            conn,
            {
                "name": "Default BioAI Radar",
                "weight": 1.0,
                "include_terms": [
                    "foundation model",
                    "single-cell",
                    "protein design",
                    "gene regulation",
                    "spatial transcriptomics",
                    "causal representation",
                ],
                "exclude_terms": ["editorial", "protocol only"],
                "seed_papers": [],
                "watch_authors": [],
                "watch_labs": [],
            },
        )
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = re.split(r"[\n,;]+", value)
        return [part.strip() for part in parts if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def json_list(value: Any) -> str:
    return json.dumps(as_list(value), ensure_ascii=False)


def load_list(row: sqlite3.Row, key: str) -> list[str]:
    raw = row[key]
    if raw is None:
        return []
    return json.loads(raw)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    arxiv_id = value.strip()
    arxiv_id = re.sub(r"^arxiv:", "", arxiv_id, flags=re.I)
    arxiv_id = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", arxiv_id, flags=re.I)
    arxiv_id = arxiv_id.removesuffix(".pdf")
    return arxiv_id or None


def paper_id_for(paper: dict[str, Any]) -> str:
    doi = normalize_doi(paper.get("doi"))
    arxiv_id = normalize_arxiv_id(paper.get("arxiv_id"))
    if doi:
        return f"doi:{doi}"
    if arxiv_id:
        return f"arxiv:{arxiv_id.lower()}"
    title = re.sub(r"\s+", " ", str(paper.get("title", "")).strip().lower())
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]
    source = str(paper.get("source", "unknown")).lower()
    return f"{source}:{digest}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def upsert_paper(conn: sqlite3.Connection, paper: dict[str, Any]) -> tuple[str, bool]:
    title = clean_text(paper.get("title"))
    if not title:
        raise ValueError("paper title is required")

    doi = normalize_doi(paper.get("doi"))
    arxiv_id = normalize_arxiv_id(paper.get("arxiv_id"))
    candidate_id = paper.get("id") or paper_id_for({**paper, "doi": doi, "arxiv_id": arxiv_id})

    existing = conn.execute(
        """
        SELECT * FROM papers
        WHERE id = ?
           OR (? IS NOT NULL AND doi = ?)
           OR (? IS NOT NULL AND arxiv_id = ?)
        LIMIT 1
        """,
        (candidate_id, doi, doi, arxiv_id, arxiv_id),
    ).fetchone()

    timestamp = now_iso()
    authors = as_list(paper.get("authors"))
    data = {
        "id": existing["id"] if existing else candidate_id,
        "source": str(paper.get("source") or (existing["source"] if existing else "unknown")),
        "doi": doi or (existing["doi"] if existing else None),
        "arxiv_id": arxiv_id or (existing["arxiv_id"] if existing else None),
        "title": title,
        "abstract": clean_text(paper.get("abstract")) or (existing["abstract"] if existing else ""),
        "authors_json": json.dumps(authors or (json.loads(existing["authors_json"]) if existing else []), ensure_ascii=False),
        "published_date": paper.get("published_date") or (existing["published_date"] if existing else None),
        "updated_date": paper.get("updated_date") or (existing["updated_date"] if existing else None),
        "url": paper.get("url") or (existing["url"] if existing else None),
        "pdf_url": paper.get("pdf_url") or (existing["pdf_url"] if existing else None),
        "category": paper.get("category") or (existing["category"] if existing else None),
        "version": paper.get("version") or (existing["version"] if existing else None),
        "created_at": existing["created_at"] if existing else timestamp,
        "updated_at": timestamp,
    }

    if existing:
        conn.execute(
            """
            UPDATE papers
            SET source=:source, doi=:doi, arxiv_id=:arxiv_id, title=:title,
                abstract=:abstract, authors_json=:authors_json,
                published_date=:published_date, updated_date=:updated_date,
                url=:url, pdf_url=:pdf_url, category=:category, version=:version,
                updated_at=:updated_at
            WHERE id=:id
            """,
            data,
        )
        return data["id"], False

    conn.execute(
        """
        INSERT INTO papers (
            id, source, doi, arxiv_id, title, abstract, authors_json,
            published_date, updated_date, url, pdf_url, category, version,
            created_at, updated_at
        )
        VALUES (
            :id, :source, :doi, :arxiv_id, :title, :abstract, :authors_json,
            :published_date, :updated_date, :url, :pdf_url, :category, :version,
            :created_at, :updated_at
        )
        """,
        data,
    )
    return data["id"], True


def row_to_paper(
    row: sqlite3.Row,
    score: sqlite3.Row | None = None,
    actions: list[str] | None = None,
    exports: list[str] | None = None,
    analysis_status: str | None = None,
) -> dict[str, Any]:
    item = {
        "id": row["id"],
        "source": row["source"],
        "doi": row["doi"],
        "arxiv_id": row["arxiv_id"],
        "title": row["title"],
        "abstract": row["abstract"],
        "authors": json.loads(row["authors_json"]),
        "published_date": row["published_date"],
        "updated_date": row["updated_date"],
        "url": row["url"],
        "pdf_url": row["pdf_url"],
        "category": row["category"],
        "version": row["version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "actions": actions or [],
        "exports": exports or [],
        "analysis_status": analysis_status,
    }
    if score:
        item["score"] = {
            "profile_id": score["profile_id"],
            "paper_id": score["paper_id"],
            "bm25_score": score["bm25_score"],
            "embedding_score": score["embedding_score"],
            "rule_score": score["rule_score"],
            "final_score": score["final_score"],
            "reason": score["reason"],
            "updated_at": score["updated_at"],
        }
    else:
        item["score"] = None
    return item


def row_to_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "weight": row["weight"],
        "include_terms": load_list(row, "include_terms_json"),
        "exclude_terms": load_list(row, "exclude_terms_json"),
        "seed_papers": load_list(row, "seed_papers_json"),
        "watch_authors": load_list(row, "watch_authors_json"),
        "watch_labs": load_list(row, "watch_labs_json"),
        "arxiv_query": row["arxiv_query"] if "arxiv_query" in row.keys() else "",
        "biorxiv_query": row["biorxiv_query"] if "biorxiv_query" in row.keys() else "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_profile(conn: sqlite3.Connection, payload: dict[str, Any]) -> str:
    timestamp = now_iso()
    profile_id = payload.get("id") or f"profile:{uuid.uuid4().hex}"
    name = clean_text(payload.get("name")) or "Untitled Profile"
    existing = conn.execute(
        "SELECT * FROM research_profiles WHERE id = ? OR name = ? LIMIT 1",
        (profile_id, name),
    ).fetchone()
    profile_id = existing["id"] if existing else profile_id
    data = {
        "id": profile_id,
        "name": name,
        "weight": float(payload.get("weight", existing["weight"] if existing else 1.0)),
        "include_terms_json": json_list(payload.get("include_terms")),
        "exclude_terms_json": json_list(payload.get("exclude_terms")),
        "seed_papers_json": json_list(payload.get("seed_papers")),
        "watch_authors_json": json_list(payload.get("watch_authors")),
        "watch_labs_json": json_list(payload.get("watch_labs")),
        "arxiv_query": clean_text(payload.get("arxiv_query")) or (existing["arxiv_query"] if existing and "arxiv_query" in existing.keys() else ""),
        "biorxiv_query": clean_text(payload.get("biorxiv_query")) or (existing["biorxiv_query"] if existing and "biorxiv_query" in existing.keys() else ""),
        "created_at": existing["created_at"] if existing else timestamp,
        "updated_at": timestamp,
    }
    if existing:
        conn.execute(
            """
            UPDATE research_profiles
            SET name=:name, weight=:weight,
                include_terms_json=:include_terms_json,
                exclude_terms_json=:exclude_terms_json,
                seed_papers_json=:seed_papers_json,
                watch_authors_json=:watch_authors_json,
                watch_labs_json=:watch_labs_json,
                arxiv_query=:arxiv_query,
                biorxiv_query=:biorxiv_query,
                updated_at=:updated_at
            WHERE id=:id
            """,
            data,
        )
    else:
        conn.execute(
            """
            INSERT INTO research_profiles (
                id, name, weight, include_terms_json, exclude_terms_json,
                seed_papers_json, watch_authors_json, watch_labs_json,
                arxiv_query, biorxiv_query, created_at, updated_at
            )
            VALUES (
                :id, :name, :weight, :include_terms_json, :exclude_terms_json,
                :seed_papers_json, :watch_authors_json, :watch_labs_json,
                :arxiv_query, :biorxiv_query, :created_at, :updated_at
            )
            """,
            data,
        )
    conn.commit()
    return profile_id


def delete_profile(conn: sqlite3.Connection, profile_id: str) -> None:
    total = conn.execute("SELECT COUNT(*) AS n FROM research_profiles").fetchone()["n"]
    if total <= 1:
        raise ValueError("Cannot delete the last research profile.")
    existing = conn.execute("SELECT id FROM research_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not existing:
        raise ValueError(f"profile not found: {profile_id}")
    conn.execute("DELETE FROM research_profiles WHERE id = ?", (profile_id,))
    conn.commit()


def or_query_for_terms(terms: list[str]) -> str:
    groups: list[str] = []
    used: set[str] = set()
    for term in terms:
        lower = term.lower()
        if lower in used:
            continue
        if lower == "single cell":
            groups.append('("single cell" OR "single-cell")')
            used.update({"single cell", "single-cell"})
        elif lower == "single-cell":
            continue
        elif " " in term or "-" in term:
            groups.append(f'"{term}"')
            used.add(lower)
        else:
            groups.append(term)
            used.add(lower)
    return " OR ".join(groups[:10]) or "all:*"


def fetch_url(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_json(url: str, timeout: int = 30) -> dict[str, Any]:
    return json.loads(fetch_url(url, timeout).decode("utf-8"))


def fetch_arxiv(query: str, limit: int = 25) -> list[dict[str, Any]]:
    search_query = query.strip() or "all:*"
    params = urllib.parse.urlencode(
        {
            "search_query": search_query,
            "start": 0,
            "max_results": min(limit, 100),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    url = f"https://export.arxiv.org/api/query?{params}"
    root = ET.fromstring(fetch_url(url).decode("utf-8"))
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    papers: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        arxiv_url = entry.findtext("atom:id", default="", namespaces=ns)
        arxiv_id = normalize_arxiv_id(arxiv_url)
        links = entry.findall("atom:link", ns)
        pdf_url = None
        for link in links:
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href")
                break
        category = None
        primary_category = entry.find("arxiv:primary_category", ns)
        if primary_category is not None:
            category = primary_category.attrib.get("term")
        papers.append(
            {
                "source": "arxiv",
                "arxiv_id": arxiv_id,
                "doi": entry.findtext("arxiv:doi", default="", namespaces=ns) or None,
                "title": clean_text(entry.findtext("atom:title", default="", namespaces=ns)),
                "abstract": clean_text(entry.findtext("atom:summary", default="", namespaces=ns)),
                "authors": [
                    clean_text(author.findtext("atom:name", default="", namespaces=ns))
                    for author in entry.findall("atom:author", ns)
                ],
                "published_date": (entry.findtext("atom:published", default="", namespaces=ns) or "")[:10],
                "updated_date": (entry.findtext("atom:updated", default="", namespaces=ns) or "")[:10],
                "url": arxiv_url,
                "pdf_url": pdf_url,
                "category": category,
                "version": None,
            }
        )
    return papers


def fetch_biorxiv(
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 25,
    category: str | None = None,
) -> list[dict[str, Any]]:
    date_from = date_from or today()
    date_to = date_to or date_from
    papers: list[dict[str, Any]] = []
    cursor = 0
    while len(papers) < limit:
        url = f"https://api.biorxiv.org/details/biorxiv/{date_from}/{date_to}/{cursor}/json"
        data = fetch_json(url)
        collection = data.get("collection", [])
        if not collection:
            break
        for item in collection:
            if category and item.get("category", "").lower() != category.lower():
                continue
            doi = normalize_doi(item.get("doi"))
            version = str(item.get("version") or "")
            papers.append(
                {
                    "source": "biorxiv",
                    "doi": doi,
                    "title": item.get("title", ""),
                    "abstract": item.get("abstract", ""),
                    "authors": item.get("authors", "").split("; "),
                    "published_date": item.get("date"),
                    "updated_date": item.get("date"),
                    "url": f"https://www.biorxiv.org/content/{doi}v{version}" if doi else item.get("jatsxml"),
                    "pdf_url": f"https://www.biorxiv.org/content/{doi}v{version}.full.pdf" if doi and version else None,
                    "category": item.get("category"),
                    "version": version,
                }
            )
            if len(papers) >= limit:
                break
        cursor += len(collection)
        if len(collection) < 100:
            break
        time.sleep(0.2)
    return papers


def fetch_europepmc(query: str, limit: int = 25) -> list[dict[str, Any]]:
    clean_query = query.strip() or "SRC:PPR"
    if "SRC:" not in clean_query.upper():
        clean_query = f"({clean_query}) AND SRC:PPR"
    params = urllib.parse.urlencode({"query": clean_query, "format": "json", "pageSize": limit})
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}"
    data = fetch_json(url)
    results = data.get("resultList", {}).get("result", [])
    papers: list[dict[str, Any]] = []
    for item in results:
        doi = normalize_doi(item.get("doi"))
        papers.append(
            {
                "source": "europepmc",
                "doi": doi,
                "title": item.get("title", ""),
                "abstract": item.get("abstractText", ""),
                "authors": item.get("authorString", "").split(", "),
                "published_date": item.get("firstPublicationDate") or item.get("firstIndexDate"),
                "updated_date": item.get("firstIndexDate"),
                "url": item.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url")
                if item.get("fullTextUrlList")
                else f"https://europepmc.org/article/{item.get('source', 'PPR')}/{item.get('id')}",
                "pdf_url": None,
                "category": item.get("source"),
                "version": None,
            }
        )
    return papers


def abstract_from_openalex(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, offsets in index.items():
        for offset in offsets:
            positions.append((offset, word))
    return " ".join(word for _, word in sorted(positions))


def fetch_openalex(query: str, limit: int = 25) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"search": query, "per-page": min(limit, 50), "sort": "publication_date:desc"})
    url = f"https://api.openalex.org/works?{params}"
    data = fetch_json(url)
    papers: list[dict[str, Any]] = []
    for item in data.get("results", []):
        authorships = item.get("authorships", [])
        papers.append(
            {
                "source": "openalex",
                "doi": normalize_doi(item.get("doi")),
                "title": item.get("title", ""),
                "abstract": abstract_from_openalex(item.get("abstract_inverted_index")),
                "authors": [
                    author.get("author", {}).get("display_name", "")
                    for author in authorships
                    if author.get("author", {}).get("display_name")
                ],
                "published_date": item.get("publication_date"),
                "updated_date": item.get("updated_date"),
                "url": item.get("id"),
                "pdf_url": (item.get("open_access") or {}).get("oa_url"),
                "category": item.get("type"),
                "version": None,
            }
        )
    return papers


def fetch_semantic_scholar(query: str, limit: int = 25) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "limit": min(limit, 100),
            "fields": "title,abstract,authors,year,externalIds,url,openAccessPdf,publicationDate,fieldsOfStudy",
        }
    )
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
    data = fetch_json(url)
    papers: list[dict[str, Any]] = []
    for item in data.get("data", []):
        external = item.get("externalIds") or {}
        open_pdf = item.get("openAccessPdf") or {}
        fields = item.get("fieldsOfStudy") or []
        papers.append(
            {
                "source": "semantic_scholar",
                "doi": normalize_doi(external.get("DOI")),
                "arxiv_id": normalize_arxiv_id(external.get("ArXiv")),
                "title": item.get("title", ""),
                "abstract": item.get("abstract", ""),
                "authors": [author.get("name", "") for author in item.get("authors", [])],
                "published_date": item.get("publicationDate") or str(item.get("year") or ""),
                "updated_date": None,
                "url": item.get("url"),
                "pdf_url": open_pdf.get("url"),
                "category": ", ".join(fields[:3]),
                "version": None,
            }
        )
    return papers


def demo_papers() -> list[dict[str, Any]]:
    return [
        {
            "source": "demo",
            "doi": "10.1101/2026.04.01.000001",
            "title": "A foundation model for perturbation-aware single-cell regulatory inference",
            "abstract": "We introduce a transformer model that integrates single-cell RNA-seq, perturbation screens, and chromatin accessibility to infer gene regulatory programs under unseen perturbations.",
            "authors": ["Lin Zhang", "Maya Chen", "Arjun Patel"],
            "published_date": "2026-04-01",
            "url": "https://example.org/paper/single-cell-foundation-model",
            "category": "bioinformatics",
        },
        {
            "source": "demo",
            "arxiv_id": "2604.00002",
            "title": "Causal representation learning for biological sequence design",
            "abstract": "This paper studies invariance constraints for protein and enhancer sequence design and shows improved out-of-distribution generalization on mutational scans.",
            "authors": ["Eva Muller", "Noah Smith"],
            "published_date": "2026-04-02",
            "url": "https://arxiv.org/abs/2604.00002",
            "pdf_url": "https://arxiv.org/pdf/2604.00002",
            "category": "cs.LG",
        },
        {
            "source": "demo",
            "doi": "10.1101/2026.04.03.000003",
            "title": "A protocol only benchmark for routine microscopy staining",
            "abstract": "We report a laboratory protocol and editorial-style checklist for staining workflows without computational modeling.",
            "authors": ["Taylor Green"],
            "published_date": "2026-04-03",
            "url": "https://example.org/paper/protocol-only",
            "category": "protocol",
        },
    ]


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-]{1,}", re.I)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


def paper_text(paper: sqlite3.Row) -> str:
    authors = " ".join(json.loads(paper["authors_json"]))
    return f"{paper['title']} {paper['abstract']} {authors} {paper['category'] or ''}".lower()


def cosine_hash(a_text: str, b_text: str, buckets: int = 512) -> float:
    def vector(text: str) -> dict[int, float]:
        counts: dict[int, float] = {}
        for token in tokenize(text):
            bucket = int(hashlib.sha1(token.encode()).hexdigest(), 16) % buckets
            counts[bucket] = counts.get(bucket, 0.0) + 1.0
        return counts

    a = vector(a_text)
    b = vector(b_text)
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(key, 0.0) for key, value in a.items())
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def feedback_weights(conn: sqlite3.Connection, profile_id: str) -> dict[str, dict[str, float]]:
    rows = conn.execute(
        "SELECT paper_id, action FROM feedback WHERE profile_id = ?",
        (profile_id,),
    ).fetchall()
    weights: dict[str, dict[str, float]] = {}
    for row in rows:
        weights.setdefault(row["paper_id"], {})
        action = row["action"]
        weights[row["paper_id"]][action] = 1.0
    return weights


def positive_profile_context(conn: sqlite3.Connection, profile: sqlite3.Row) -> str:
    profile_data = row_to_profile(profile)
    chunks = [profile_data["name"], *profile_data["include_terms"], *profile_data["watch_authors"]]
    rows = conn.execute(
        """
        SELECT p.title, p.abstract
        FROM papers p
        JOIN feedback f ON f.paper_id = p.id
        WHERE f.profile_id = ? AND f.action IN ('save', 'read', 'like')
        ORDER BY f.created_at DESC
        LIMIT 20
        """,
        (profile["id"],),
    ).fetchall()
    for row in rows:
        chunks.append(f"{row['title']} {row['abstract']}")
    seed_ids = profile_data["seed_papers"]
    if seed_ids:
        placeholders = ",".join("?" for _ in seed_ids)
        seed_rows = conn.execute(
            f"SELECT title, abstract FROM papers WHERE id IN ({placeholders})",
            seed_ids,
        ).fetchall()
        for row in seed_rows:
            chunks.append(f"{row['title']} {row['abstract']}")
    return " ".join(chunks)


def score_paper_for_profile(
    conn: sqlite3.Connection,
    paper: sqlite3.Row,
    profile: sqlite3.Row,
    feedback_by_paper: dict[str, dict[str, float]],
) -> tuple[float, float, float, float, str]:
    profile_data = row_to_profile(profile)
    doc = paper_text(paper)
    include_terms = profile_data["include_terms"] or tokenize(profile_data["name"])
    exclude_terms = profile_data["exclude_terms"]
    matched_terms = [term for term in include_terms if term.lower() in doc]
    excluded_terms = [term for term in exclude_terms if term.lower() in doc]

    query_tokens = tokenize(" ".join(include_terms))
    doc_tokens = tokenize(doc)
    doc_token_set = set(doc_tokens)
    token_hits = sum(1 for token in query_tokens if token in doc_token_set)
    bm25_score = min(1.0, token_hits / max(1.0, math.sqrt(len(set(query_tokens)) or 1)))

    context = positive_profile_context(conn, profile)
    embedding_score = cosine_hash(context, doc)

    authors = [author.lower() for author in json.loads(paper["authors_json"])]
    watch_authors = [author.lower() for author in profile_data["watch_authors"]]
    author_hits = [
        watched
        for watched in watch_authors
        if any(watched in author for author in authors)
    ]
    rule_score = 0.0
    rule_score += min(0.6, len(matched_terms) * 0.12)
    rule_score += min(0.4, len(author_hits) * 0.2)
    rule_score -= min(0.9, len(excluded_terms) * 0.45)
    rule_score = max(-1.0, min(1.0, rule_score))

    actions = feedback_by_paper.get(paper["id"], {})
    feedback_bonus = 0.0
    if "save" in actions:
        feedback_bonus += 14
    if "read" in actions:
        feedback_bonus += 8
    if "like" in actions:
        feedback_bonus += 18
    if "dislike" in actions:
        feedback_bonus -= 25
    if "not_relevant" in actions:
        feedback_bonus -= 55

    base = (45 * bm25_score) + (35 * embedding_score) + (20 * max(0.0, rule_score))
    if excluded_terms:
        base -= 50
    final_score = max(0.0, min(100.0, (base + feedback_bonus) * float(profile["weight"])))

    reasons: list[str] = []
    if matched_terms:
        reasons.append("matched " + ", ".join(matched_terms[:4]))
    if author_hits:
        reasons.append("watch author " + ", ".join(author_hits[:2]))
    if embedding_score > 0.18:
        reasons.append("similar to saved context")
    if excluded_terms:
        reasons.append("excluded term " + ", ".join(excluded_terms[:3]))
    if actions:
        reasons.append("feedback " + ", ".join(sorted(actions)))
    if not reasons:
        reasons.append("weak lexical match")
    return bm25_score, embedding_score, rule_score, final_score, "; ".join(reasons)


def rank_papers(conn: sqlite3.Connection, profile_ids: list[str] | None = None) -> int:
    if profile_ids:
        placeholders = ",".join("?" for _ in profile_ids)
        profiles = conn.execute(
            f"SELECT * FROM research_profiles WHERE id IN ({placeholders})",
            profile_ids,
        ).fetchall()
    else:
        profiles = conn.execute("SELECT * FROM research_profiles").fetchall()

    papers = conn.execute("SELECT * FROM papers").fetchall()
    scored = 0
    timestamp = now_iso()
    for profile in profiles:
        feedback_by_paper = feedback_weights(conn, profile["id"])
        for paper in papers:
            bm25_score, embedding_score, rule_score, final_score, reason = score_paper_for_profile(
                conn, paper, profile, feedback_by_paper
            )
            conn.execute(
                """
                INSERT INTO paper_scores (
                    profile_id, paper_id, bm25_score, embedding_score,
                    rule_score, final_score, reason, updated_at
                )
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
                    bm25_score,
                    embedding_score,
                    rule_score,
                    final_score,
                    reason,
                    timestamp,
                ),
            )
            scored += 1
    conn.commit()
    return scored


def list_papers(
    conn: sqlite3.Connection,
    profile_id: str | None = None,
    limit: int = 80,
    query: str | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if query:
        where = "WHERE lower(p.title || ' ' || p.abstract) LIKE ?"
        params.append(f"%{query.lower()}%")
    if profile_id:
        sql = f"""
            SELECT p.*, s.profile_id, s.paper_id, s.bm25_score, s.embedding_score,
                   s.rule_score, s.final_score, s.reason, s.updated_at AS score_updated_at
            FROM papers p
            LEFT JOIN paper_scores s ON s.paper_id = p.id AND s.profile_id = ?
            {where}
            ORDER BY COALESCE(s.final_score, 0) DESC, p.published_date DESC, p.created_at DESC
            LIMIT ?
        """
        params = [profile_id, *params, limit]
    else:
        sql = f"""
            SELECT p.*, NULL AS profile_id, NULL AS paper_id, NULL AS bm25_score,
                   NULL AS embedding_score, NULL AS rule_score, NULL AS final_score,
                   NULL AS reason, NULL AS score_updated_at
            FROM papers p
            {where}
            ORDER BY p.published_date DESC, p.created_at DESC
            LIMIT ?
        """
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    papers: list[dict[str, Any]] = []
    for row in rows:
        score = None
        if row["profile_id"]:
            score = {
                "profile_id": row["profile_id"],
                "paper_id": row["paper_id"],
                "bm25_score": row["bm25_score"],
                "embedding_score": row["embedding_score"],
                "rule_score": row["rule_score"],
                "final_score": row["final_score"],
                "reason": row["reason"],
                "updated_at": row["score_updated_at"],
            }
        action_rows = conn.execute(
            "SELECT action FROM feedback WHERE paper_id = ? AND (? IS NULL OR profile_id = ?) ORDER BY action",
            (row["id"], profile_id, profile_id),
        ).fetchall()
        analysis = conn.execute(
            """
            SELECT status FROM paper_analyses
            WHERE paper_id = ? AND (? IS NULL OR profile_id = ?)
            ORDER BY updated_at DESC LIMIT 1
            """,
            (row["id"], profile_id, profile_id),
        ).fetchone()
        export_rows = conn.execute(
            "SELECT target FROM paper_exports WHERE paper_id = ? ORDER BY target",
            (row["id"],),
        ).fetchall()
        papers.append(
            row_to_paper(
                row,
                score=dict_to_row(score) if score else None,
                actions=[action["action"] for action in action_rows],
                exports=[export_row["target"] for export_row in export_rows],
                analysis_status=analysis["status"] if analysis else None,
            )
        )
    return papers


def dict_to_row(data: dict[str, Any]) -> sqlite3.Row:
    class RowDict(dict):
        def __getitem__(self, key: str) -> Any:
            return dict.get(self, key)

    return RowDict(data)  # type: ignore[return-value]


def local_search(conn: sqlite3.Connection, query: str, limit: int, profile_id: str | None) -> list[dict[str, Any]]:
    rank_papers(conn, [profile_id] if profile_id else None)
    tokens = tokenize(query)
    rows = conn.execute("SELECT * FROM papers").fetchall()
    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        doc = paper_text(row)
        score = sum(2.0 if token in row["title"].lower() else 1.0 for token in tokens if token in doc)
        score += cosine_hash(query, doc) * 10
        scored.append((score, row))
    top_ids = [row["id"] for score, row in sorted(scored, reverse=True, key=lambda item: item[0]) if score > 0][:limit]
    if not top_ids:
        return []
    placeholders = ",".join("?" for _ in top_ids)
    if profile_id:
        rows = conn.execute(
            f"""
            SELECT p.*, s.profile_id, s.paper_id, s.bm25_score, s.embedding_score,
                   s.rule_score, s.final_score, s.reason, s.updated_at AS score_updated_at
            FROM papers p
            LEFT JOIN paper_scores s ON s.paper_id = p.id AND s.profile_id = ?
            WHERE p.id IN ({placeholders})
            """,
            [profile_id, *top_ids],
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        ordered = [by_id[paper_id] for paper_id in top_ids if paper_id in by_id]
        return [
            row_to_paper(
                row,
                dict_to_row(
                    {
                        "profile_id": row["profile_id"],
                        "paper_id": row["paper_id"],
                        "bm25_score": row["bm25_score"],
                        "embedding_score": row["embedding_score"],
                        "rule_score": row["rule_score"],
                        "final_score": row["final_score"],
                        "reason": row["reason"],
                        "updated_at": row["score_updated_at"],
                    }
                )
                if row["profile_id"]
                else None,
                actions=[],
                analysis_status=None,
            )
            for row in ordered
        ]
    rows = conn.execute(f"SELECT * FROM papers WHERE id IN ({placeholders})", top_ids).fetchall()
    by_id = {row["id"]: row for row in rows}
    return [row_to_paper(by_id[paper_id]) for paper_id in top_ids if paper_id in by_id]


def keychain_password(service: str) -> str:
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return ""
    return ""


def get_deepseek_api_key(purpose: str = "reader") -> str:
    if purpose == "flash":
        flash_env = os.environ.get("DEEPSEEK_FLASH_API_KEY", "").strip()
        if flash_env:
            return flash_env
        flash_key = keychain_password(KEYCHAIN_FLASH_SERVICE)
        if flash_key:
            return flash_key
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key
    return (
        keychain_password(KEYCHAIN_READER_SERVICE)
        or keychain_password(KEYCHAIN_LEGACY_SERVICE)
        or keychain_password(KEYCHAIN_FLASH_SERVICE)
    )


def deepseek_json(model: str, system: str, user: str, purpose: str = "reader") -> dict[str, Any]:
    key = get_deepseek_api_key(purpose)
    if not key:
        raise RuntimeError("missing DeepSeek API key")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                payload["messages"].append(
                    {
                        "role": "user",
                        "content": "The previous response was invalid. Return valid JSON only.",
                    }
                )
                body = json.dumps(payload).encode("utf-8")
                request.data = body  # type: ignore[attr-defined]
    raise RuntimeError(f"DeepSeek JSON call failed: {last_error}")


def local_analysis(paper: sqlite3.Row, profile: sqlite3.Row | None, score: sqlite3.Row | None) -> dict[str, Any]:
    title = paper["title"]
    abstract = paper["abstract"]
    first_sentence = re.split(r"(?<=[.!?])\s+", abstract)[0] if abstract else title
    fit = score["reason"] if score else "not ranked"
    worth = bool(score and score["final_score"] >= 45)
    return {
        "one_sentence": first_sentence[:400],
        "research_question": "Inferred from title and abstract; review full text before relying on this.",
        "methods_data": "Local triage did not inspect the full paper.",
        "core_findings": abstract[:700],
        "relationship_to_profile": fit,
        "limitations": "No LLM call was made, so this is a shallow abstract-level triage and is not written into long-term memory.",
        "worth_reading": worth,
        "memory_target": profile["name"] if profile else "Unassigned",
    }


def save_analysis(
    conn: sqlite3.Connection,
    paper_id: str,
    profile_id: str,
    model: str,
    status: str,
    analysis: dict[str, Any],
) -> None:
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO paper_analyses (
            id, paper_id, profile_id, model, status, json_content, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"analysis:{uuid.uuid4().hex}",
            paper_id,
            profile_id,
            model,
            status,
            json.dumps(analysis, ensure_ascii=False),
            timestamp,
            timestamp,
        ),
    )
    conn.commit()


def load_prompt(name: str) -> str:
    path = Path(__file__).resolve().parent / "prompts" / f"{name}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "Return strict JSON."


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "untitled"


def markdown_for_paper(paper: dict[str, Any]) -> str:
    authors = ", ".join(paper["authors"])
    score = paper.get("score") or {}
    return textwrap.dedent(
        f"""\
        ---
        id: {paper["id"]}
        source: {paper["source"]}
        doi: {paper.get("doi") or ""}
        arxiv_id: {paper.get("arxiv_id") or ""}
        published_date: {paper.get("published_date") or ""}
        category: {paper.get("category") or ""}
        score: {score.get("final_score", "")}
        ---

        # {paper["title"]}

        Authors: {authors}

        URL: {paper.get("url") or ""}

        ## Abstract

        {paper["abstract"]}

        ## Recommendation Reason

        {score.get("reason", "Not ranked")}
        """
    )


def export_obsidian(conn: sqlite3.Connection, root: Path, profile_id: str | None = None) -> list[str]:
    root.mkdir(parents=True, exist_ok=True)
    for directory in ["Profiles", "Papers", "Weekly", "Claims"]:
        (root / directory).mkdir(parents=True, exist_ok=True)

    profiles = (
        conn.execute("SELECT * FROM research_profiles WHERE id = ?", (profile_id,)).fetchall()
        if profile_id
        else conn.execute("SELECT * FROM research_profiles").fetchall()
    )
    files: list[str] = []
    for profile in profiles:
        profile_data = row_to_profile(profile)
        papers = list_papers(conn, profile["id"], limit=50)
        profile_file = root / "Profiles" / f"{sanitize_filename(profile['name'])}.md"
        top_links = "\n".join(
            f"- [[{sanitize_filename(paper['title'])}]] - {(paper.get('score') or {}).get('reason', '')}"
            for paper in papers[:15]
        )
        content = textwrap.dedent(
            f"""\
            ---
            profile_id: {profile["id"]}
            weight: {profile["weight"]}
            updated: {now_iso()}
            ---

            # {profile["name"]}

            ## Interest Terms

            {", ".join(profile_data["include_terms"]) or "No include terms yet."}

            ## Exclusions

            {", ".join(profile_data["exclude_terms"]) or "No exclude terms yet."}

            ## Top Papers

            {top_links or "No ranked papers yet."}

            ## Open Questions

            - Add questions during weekly synthesis.
            """
        )
        profile_file.write_text(content, encoding="utf-8")
        files.append(str(profile_file))

        claims_file = root / "Claims" / f"{sanitize_filename(profile['name'])} claims.md"
        claims_file.write_text(
            f"# {profile['name']} Claims\n\n- Capture claim -> evidence -> counterevidence here.\n",
            encoding="utf-8",
        )
        files.append(str(claims_file))

        for paper in papers:
            paper_file = root / "Papers" / f"{sanitize_filename(paper['title'])}.md"
            paper_file.write_text(markdown_for_paper(paper), encoding="utf-8")
            conn.execute(
                """
                INSERT INTO paper_exports (paper_id, target, path, exported_at)
                VALUES (?, 'obsidian', ?, ?)
                ON CONFLICT(paper_id, target) DO UPDATE SET
                    path=excluded.path,
                    exported_at=excluded.exported_at
                """,
                (paper["id"], str(paper_file), now_iso()),
            )
            files.append(str(paper_file))

        notes = conn.execute(
            "SELECT * FROM memory_notes WHERE profile_id = ? ORDER BY updated_at DESC",
            (profile["id"],),
        ).fetchall()
        for note in notes:
            note_file = root / "Weekly" / f"{sanitize_filename(note['title'])}.md"
            note_file.write_text(note["content"], encoding="utf-8")
            conn.execute(
                "UPDATE memory_notes SET markdown_path = ?, updated_at = ? WHERE id = ?",
                (str(note_file), now_iso(), note["id"]),
            )
            files.append(str(note_file))
    conn.commit()
    return files


def ris_record(paper: dict[str, Any]) -> str:
    lines = ["TY  - JOUR"]
    lines.append(f"TI  - {paper['title']}")
    for author in paper["authors"]:
        lines.append(f"AU  - {author}")
    if paper.get("published_date"):
        lines.append(f"PY  - {paper['published_date'][:4]}")
    if paper.get("doi"):
        lines.append(f"DO  - {paper['doi']}")
    if paper.get("url"):
        lines.append(f"UR  - {paper['url']}")
    lines.append(f"AB  - {paper['abstract']}")
    lines.append("ER  - ")
    return "\n".join(lines)


def bibtex_key(paper: dict[str, Any]) -> str:
    first_author = paper["authors"][0].split()[-1] if paper["authors"] else "paper"
    year = (paper.get("published_date") or "0000")[:4]
    word = tokenize(paper["title"])[0] if tokenize(paper["title"]) else "work"
    return re.sub(r"[^A-Za-z0-9_]", "", f"{first_author}{year}{word}")


def bibtex_record(paper: dict[str, Any]) -> str:
    fields = {
        "title": paper["title"],
        "author": " and ".join(paper["authors"]),
        "year": (paper.get("published_date") or "")[:4],
        "doi": paper.get("doi") or "",
        "url": paper.get("url") or "",
        "abstract": paper["abstract"],
    }
    body = ",\n".join(f"  {key} = {{{value}}}" for key, value in fields.items() if value)
    return f"@article{{{bibtex_key(paper)},\n{body}\n}}"


def export_zotero(conn: sqlite3.Connection, root: Path, profile_id: str | None = None) -> list[str]:
    root.mkdir(parents=True, exist_ok=True)
    papers = list_papers(conn, profile_id=profile_id, limit=500)
    ris_path = root / "literature-radar.ris"
    bib_path = root / "literature-radar.bib"
    csl_path = root / "literature-radar.csl.json"
    ris_path.write_text("\n\n".join(ris_record(paper) for paper in papers), encoding="utf-8")
    bib_path.write_text("\n\n".join(bibtex_record(paper) for paper in papers), encoding="utf-8")
    csl_items = []
    for paper in papers:
        csl_items.append(
            {
                "id": paper["id"],
                "type": "article-journal",
                "title": paper["title"],
                "author": [{"literal": author} for author in paper["authors"]],
                "DOI": paper.get("doi"),
                "URL": paper.get("url"),
                "abstract": paper["abstract"],
                "issued": {"date-parts": [[int((paper.get("published_date") or "0")[:4] or 0)]]},
            }
        )
    csl_path.write_text(json.dumps(csl_items, ensure_ascii=False, indent=2), encoding="utf-8")
    timestamp = now_iso()
    for paper in papers:
        conn.execute(
            """
            INSERT INTO paper_exports (paper_id, target, path, exported_at)
            VALUES (?, 'zotero', ?, ?)
            ON CONFLICT(paper_id, target) DO UPDATE SET
                path=excluded.path,
                exported_at=excluded.exported_at
            """,
            (paper["id"], str(root), timestamp),
        )
    conn.commit()
    return [str(ris_path), str(bib_path), str(csl_path)]


ZOTERO_EXPORT_SUFFIXES = {".bib", ".bibtex", ".ris", ".json"}


def zotero_export_priority(path: Path) -> tuple[int, str]:
    priority = {
        ".bib": 0,
        ".bibtex": 1,
        ".ris": 2,
        ".json": 3,
    }
    return (priority.get(path.suffix.lower(), 99), path.name.lower())


def resolve_zotero_export_input(path: Path) -> tuple[Path, Path]:
    expanded = path.expanduser()
    if expanded.is_dir():
        direct = [
            child
            for child in expanded.iterdir()
            if child.is_file() and child.suffix.lower() in ZOTERO_EXPORT_SUFFIXES
        ]
        candidates = direct
        if not candidates:
            candidates = [
                child
                for child in expanded.rglob("*")
                if child.is_file()
                and child.suffix.lower() in ZOTERO_EXPORT_SUFFIXES
                and "files" not in {part.lower() for part in child.relative_to(expanded).parts[:-1]}
            ]
        if not candidates:
            raise ValueError(f"No Zotero export file found in folder: {expanded}")
        return sorted(candidates, key=zotero_export_priority)[0], expanded
    if not expanded.exists():
        raise ValueError(f"Zotero export path does not exist: {expanded}")
    if expanded.suffix.lower() not in ZOTERO_EXPORT_SUFFIXES:
        raise ValueError(f"Unsupported Zotero export file: {expanded.name}")
    return expanded, expanded.parent


def resolve_attachment_path(raw_path: str, base_dir: Path | None) -> str | None:
    path_text = clean_text(raw_path).replace("\\:", ":").strip()
    if not path_text:
        return None
    if path_text.startswith("file://"):
        parsed = urllib.parse.urlparse(path_text)
        return urllib.parse.unquote(parsed.path)
    if re.match(r"^https?://", path_text, flags=re.I):
        return path_text
    candidate = Path(path_text).expanduser()
    if not candidate.is_absolute() and base_dir:
        candidate = base_dir / candidate
    return str(candidate.resolve(strict=False))


def extract_zotero_pdf_path(file_field: str | None, base_dir: Path | None) -> str | None:
    if not file_field:
        return None
    attachments = [part.strip() for part in re.split(r"\s*;\s*", file_field) if part.strip()]
    unresolved_candidate: str | None = None
    for attachment in attachments:
        pieces = attachment.rsplit(":", 2)
        if len(pieces) == 3:
            _, raw_path, mime = pieces
        else:
            raw_path = attachment
            mime = ""
        resolved = resolve_attachment_path(raw_path, base_dir)
        if not resolved:
            continue
        is_pdf = "pdf" in mime.lower() or resolved.lower().endswith(".pdf")
        if is_pdf and not re.match(r"^https?://", resolved, flags=re.I):
            if Path(resolved).exists():
                return resolved
            unresolved_candidate = unresolved_candidate or resolved
        elif is_pdf:
            unresolved_candidate = unresolved_candidate or resolved
    return unresolved_candidate


def parse_ris(text: str, base_dir: Path | None = None) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    records = re.split(r"^ER\s+-.*$", text, flags=re.M)
    for record in records:
        fields: dict[str, list[str]] = {}
        current_tag: str | None = None
        for line in record.splitlines():
            match = re.match(r"^([A-Z0-9]{2})\s+-\s*(.*)$", line)
            if match:
                current_tag = match.group(1)
                fields.setdefault(current_tag, []).append(match.group(2).strip())
            elif current_tag and line.strip():
                fields[current_tag][-1] += " " + line.strip()
        title = first_value(fields, ["TI", "T1", "CT"])
        if not title:
            continue
        pdf_url = first_value(fields, ["L1"])
        if pdf_url:
            pdf_url = resolve_attachment_path(pdf_url, base_dir) or pdf_url
        papers.append(
            {
                "source": "zotero",
                "doi": first_value(fields, ["DO"]),
                "title": title,
                "abstract": first_value(fields, ["AB", "N2"]),
                "authors": fields.get("AU", []) or fields.get("A1", []),
                "published_date": first_value(fields, ["DA", "Y1", "PY"]),
                "updated_date": None,
                "url": first_value(fields, ["UR", "L1"]),
                "pdf_url": pdf_url,
                "category": first_value(fields, ["KW", "JF", "JO"]),
                "version": None,
            }
        )
    return papers


def first_value(fields: dict[str, list[str]], keys: list[str]) -> str | None:
    for key in keys:
        values = fields.get(key)
        if values:
            return clean_text(values[0])
    return None


def parse_bibtex(text: str, base_dir: Path | None = None) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    entries = re.split(r"\n@", "\n" + text)
    for raw_entry in entries:
        entry = raw_entry.strip()
        if not entry:
            continue
        if not entry.startswith("@"):
            entry = "@" + entry
        head = re.match(r"@\w+\s*\{\s*([^,]+),", entry, flags=re.S)
        if not head:
            continue
        body = entry[head.end() :]
        fields: dict[str, str] = {}
        for match in re.finditer(
            r"(?im)^\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"(?:[^\"\\]|\\.)*\")\s*,?",
            body,
        ):
            key = match.group(1).lower()
            value = match.group(2).strip()
            value = value[1:-1] if len(value) >= 2 else value
            fields[key] = clean_text(value)
        title = fields.get("title")
        if not title:
            continue
        pdf_path = extract_zotero_pdf_path(fields.get("file"), base_dir)
        papers.append(
            {
                "source": "zotero",
                "doi": fields.get("doi"),
                "arxiv_id": fields.get("eprint") if fields.get("archiveprefix", "").lower() == "arxiv" else None,
                "title": title,
                "abstract": fields.get("abstract", ""),
                "authors": re.split(r"\s+and\s+", fields.get("author", "")) if fields.get("author") else [],
                "published_date": fields.get("date") or fields.get("year"),
                "updated_date": None,
                "url": fields.get("url"),
                "pdf_url": pdf_path or fields.get("file"),
                "category": fields.get("journal") or fields.get("booktitle"),
                "version": None,
            }
        )
    return papers


def parse_csl_json(text: str, base_dir: Path | None = None) -> list[dict[str, Any]]:
    raw = json.loads(text)
    items = raw if isinstance(raw, list) else raw.get("items", [])
    papers: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"))
        if not title:
            continue
        authors = []
        for author in item.get("author", []) or []:
            if "literal" in author:
                authors.append(clean_text(author["literal"]))
            else:
                authors.append(clean_text(" ".join([author.get("given", ""), author.get("family", "")])))
        date_parts = (item.get("issued") or {}).get("date-parts") or []
        date_text = ""
        if date_parts and date_parts[0]:
            date_text = "-".join(str(part) for part in date_parts[0])
        papers.append(
            {
                "source": "zotero",
                "doi": item.get("DOI") or item.get("doi"),
                "title": title,
                "abstract": item.get("abstract") or item.get("note") or "",
                "authors": authors,
                "published_date": date_text,
                "updated_date": None,
                "url": item.get("URL") or item.get("url"),
                "pdf_url": None,
                "category": item.get("container-title") or item.get("type"),
                "version": None,
            }
        )
    return papers


def parse_zotero_export(path: Path) -> list[dict[str, Any]]:
    export_path, base_dir = resolve_zotero_export_input(path)
    text = export_path.read_text(encoding="utf-8-sig")
    suffix = export_path.suffix.lower()
    if suffix == ".json":
        return parse_csl_json(text, base_dir)
    if suffix in {".bib", ".bibtex"}:
        return parse_bibtex(text, base_dir)
    if suffix == ".ris":
        return parse_ris(text, base_dir)
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return parse_csl_json(text, base_dir)
    if stripped.startswith("@"):
        return parse_bibtex(text, base_dir)
    return parse_ris(text, base_dir)


def papers_by_ids(conn: sqlite3.Connection, paper_ids: list[str], profile_id: str | None = None) -> list[dict[str, Any]]:
    if not paper_ids:
        return []
    rank_papers(conn, [profile_id] if profile_id else None)
    placeholders = ",".join("?" for _ in paper_ids)
    rows = conn.execute(f"SELECT * FROM papers WHERE id IN ({placeholders})", paper_ids).fetchall()
    by_id = {row["id"]: row for row in rows}
    output: list[dict[str, Any]] = []
    for paper_id in paper_ids:
        row = by_id.get(paper_id)
        if not row:
            continue
        score = None
        if profile_id:
            score = conn.execute(
                "SELECT * FROM paper_scores WHERE paper_id = ? AND profile_id = ?",
                (paper_id, profile_id),
            ).fetchone()
        output.append(row_to_paper(row, score))
    return output


def normalize_plain_text(value: str) -> str:
    text = value.replace("\x00", " ")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def local_pdf_path(value: str | None) -> Path | None:
    if not value:
        return None
    if re.match(r"^https?://", value, flags=re.I):
        return None
    resolved = resolve_attachment_path(value, None)
    if not resolved:
        return None
    path = Path(resolved).expanduser()
    if path.suffix.lower() != ".pdf":
        return None
    return path if path.exists() else None


def truncate_text(text: str, max_chars: int) -> str:
    cleaned = normalize_plain_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    head = int(max_chars * 0.72)
    tail = max_chars - head
    return cleaned[:head].rstrip() + "\n\n[... middle omitted for context budget ...]\n\n" + cleaned[-tail:].lstrip()


def extract_pdf_with_pypdf(path: Path, max_chars: int) -> str:
    import pypdf  # type: ignore

    reader = pypdf.PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages[:35]:
        parts.append(page.extract_text() or "")
        if sum(len(part) for part in parts) >= max_chars * 1.3:
            break
    return normalize_plain_text("\n".join(parts))


def extract_pdf_with_pypdf2(path: Path, max_chars: int) -> str:
    import PyPDF2  # type: ignore

    reader = PyPDF2.PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages[:35]:
        parts.append(page.extract_text() or "")
        if sum(len(part) for part in parts) >= max_chars * 1.3:
            break
    return normalize_plain_text("\n".join(parts))


def extract_pdf_with_pdfminer(path: Path, max_chars: int) -> str:
    from pdfminer.high_level import extract_text  # type: ignore

    return normalize_plain_text(extract_text(str(path), maxpages=35)[: max_chars * 2])


def extract_pdf_with_pdftotext(path: Path, max_chars: int) -> str:
    executable = shutil.which("pdftotext")
    if not executable:
        raise RuntimeError("pdftotext not installed")
    result = subprocess.run(
        [executable, "-layout", "-f", "1", "-l", "35", str(path), "-"],
        check=False,
        capture_output=True,
        text=True,
        timeout=25,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "pdftotext failed")
    return normalize_plain_text(result.stdout[: max_chars * 2])


def extract_pdf_raw_text_scan(path: Path, max_chars: int) -> str:
    raw = path.read_bytes()[: min(4_000_000, max_chars * 8)]
    text = raw.decode("utf-8", errors="ignore")
    if not text.strip():
        text = raw.decode("latin-1", errors="ignore")
    printable = sum(1 for char in text if char.isprintable() or char.isspace())
    if not text or printable / max(len(text), 1) < 0.65:
        return ""
    return normalize_plain_text(text)


def extract_pdf_text(path: Path, max_chars: int) -> dict[str, Any]:
    attempts = [
        ("pypdf", extract_pdf_with_pypdf),
        ("PyPDF2", extract_pdf_with_pypdf2),
        ("pdfminer.six", extract_pdf_with_pdfminer),
        ("pdftotext", extract_pdf_with_pdftotext),
        ("raw_text_scan", extract_pdf_raw_text_scan),
    ]
    errors: list[str] = []
    for name, extractor in attempts:
        try:
            text = truncate_text(extractor(path, max_chars), max_chars)
            if len(text) >= 200 or (name == "raw_text_scan" and text):
                return {
                    "path": str(path),
                    "status": name,
                    "chars": len(text),
                    "excerpt": text,
                }
            errors.append(f"{name}: extracted too little text")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return {
        "path": str(path),
        "status": "unreadable_pdf",
        "chars": 0,
        "excerpt": "",
        "error": "; ".join(errors[-4:]),
    }


def pdf_excerpt_budget(paper_count: int) -> int:
    if paper_count <= 12:
        return 12_000
    if paper_count <= 40:
        return 7_000
    if paper_count <= 80:
        return 4_500
    return 3_000


def integration_chunk_size(paper_count: int) -> int:
    if paper_count <= 12:
        return 4
    if paper_count <= 40:
        return 6
    if paper_count <= 80:
        return 8
    return 10


def chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_zotero_reading_contexts(
    papers: list[dict[str, Any]],
    progress_path: str | None = None,
) -> list[dict[str, Any]]:
    max_chars = pdf_excerpt_budget(len(papers))
    contexts: list[dict[str, Any]] = []
    total = len(papers)
    write_progress(progress_path, "reading_pdfs", 0, total, "Reading local PDFs")
    for index, paper in enumerate(papers, start=1):
        write_progress(
            progress_path,
            "reading_pdfs",
            index - 1,
            total,
            f"Reading PDF {index} of {total}",
            paper.get("title", ""),
        )
        pdf_path = local_pdf_path(paper.get("pdf_url"))
        pdf = (
            extract_pdf_text(pdf_path, max_chars)
            if pdf_path
            else {
                "path": paper.get("pdf_url") or "",
                "status": "no_local_pdf",
                "chars": 0,
                "excerpt": "",
            }
        )
        paper_payload = {
            "id": paper["id"],
            "title": paper["title"],
            "authors": paper.get("authors", []),
            "year_or_date": paper.get("published_date"),
            "doi": paper.get("doi"),
            "url": paper.get("url"),
            "journal_or_category": paper.get("category"),
            "abstract": paper.get("abstract", ""),
            "score_reason": (paper.get("score") or {}).get("reason", ""),
        }
        contexts.append({"paper": paper_payload, "pdf": pdf})
        write_progress(
            progress_path,
            "reading_pdfs",
            index,
            total,
            f"Read PDF context {index} of {total}",
            f"{paper.get('title', '')} · {pdf.get('status')}",
        )
    return contexts


def synthesize_zotero_batches(
    profile: sqlite3.Row,
    memory_notes: list[dict[str, Any]],
    contexts: list[dict[str, Any]],
    model: str,
    progress_path: str | None = None,
) -> list[dict[str, Any]]:
    batch_prompt = load_prompt("zotero_batch_synthesis")
    chunked_contexts = chunks(contexts, integration_chunk_size(len(contexts)))
    results: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunked_contexts, start=1):
        write_progress(
            progress_path,
            "batch_synthesis",
            index - 1,
            len(chunked_contexts),
            f"Synthesizing batch {index} of {len(chunked_contexts)}",
            f"{len(chunk)} papers in this batch",
        )
        user = json.dumps(
            {
                "profile": row_to_profile(profile),
                "existing_memory_notes": memory_notes,
                "batch_index": index,
                "batch_count": len(chunked_contexts),
                "papers": chunk,
            },
            ensure_ascii=False,
        )
        result = deepseek_json(model, batch_prompt, user, purpose="reader")
        results.append(
            {
                "batch_index": index,
                "paper_ids": [item["paper"]["id"] for item in chunk],
                "result": result,
            }
        )
        write_progress(
            progress_path,
            "batch_synthesis",
            index,
            len(chunked_contexts),
            f"Finished batch {index} of {len(chunked_contexts)}",
            f"{len(chunk)} papers synthesized",
        )
    return results


def final_zotero_memory_merge(
    profile: sqlite3.Row,
    memory_notes: list[dict[str, Any]],
    batch_results: list[dict[str, Any]],
    contexts: list[dict[str, Any]],
    model: str,
    progress_path: str | None = None,
) -> str:
    write_progress(
        progress_path,
        "final_merge",
        0,
        1,
        "Merging batch syntheses into long-term memory",
        f"{len(contexts)} papers, {len(batch_results)} batches",
    )
    paper_index = [
        {
            "id": item["paper"]["id"],
            "title": item["paper"]["title"],
            "authors": item["paper"].get("authors", [])[:4],
            "date": item["paper"].get("year_or_date"),
            "pdf_status": item["pdf"].get("status"),
        }
        for item in contexts
    ]
    user = json.dumps(
        {
            "profile": row_to_profile(profile),
            "existing_memory_notes": memory_notes,
            "paper_index": paper_index,
            "batch_syntheses": batch_results,
        },
        ensure_ascii=False,
    )
    result = deepseek_json(model, load_prompt("zotero_final_memory_merge"), user, purpose="reader")
    write_progress(progress_path, "final_merge", 1, 1, "Merged long-term memory update")
    return result.get("markdown") or json.dumps(result, ensure_ascii=False, indent=2)


def cmd_init(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    init_db(conn)
    if payload.get("seed_demo"):
        inserted = 0
        for paper in demo_papers():
            _, was_inserted = upsert_paper(conn, paper)
            inserted += int(was_inserted)
        conn.commit()
        rank_papers(conn)
        return {"ok": True, "message": f"Initialized database and inserted {inserted} demo papers."}
    return {"ok": True, "message": "Initialized database."}


def cmd_profile_list(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM research_profiles ORDER BY name").fetchall()
    return {"ok": True, "profiles": [row_to_profile(row) for row in rows]}


def cmd_profile_upsert(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = upsert_profile(conn, payload)
    return {"ok": True, "message": f"Saved profile {profile_id}."}


def cmd_profile_delete(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = payload.get("id")
    if not profile_id:
        raise ValueError("profile id is required")
    delete_profile(conn, profile_id)
    return {"ok": True, "message": f"Deleted profile {profile_id}."}


def cmd_profile_from_description(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    description = clean_text(payload.get("description"))
    if not description:
        raise ValueError("description is required")
    system = load_prompt("profile_from_description")
    user = json.dumps({"description": description}, ensure_ascii=False)
    model = payload.get("model") or "deepseek-v4-flash"
    if not get_deepseek_api_key("flash"):
        raise RuntimeError(
            "DeepSeek API key is required to generate a research profile from natural language."
        )
    generated = deepseek_json(model, system, user, purpose="flash")
    profile_payload = {
        "name": generated.get("name") or "Generated Profile",
        "weight": float(payload.get("weight", 1.0)),
        "include_terms": as_list(generated.get("include_terms")),
        "exclude_terms": as_list(generated.get("exclude_terms")),
        "seed_papers": as_list(generated.get("seed_papers")),
        "watch_authors": as_list(generated.get("watch_authors")),
        "watch_labs": as_list(generated.get("watch_labs")),
        "arxiv_query": generated.get("arxiv_query") or "",
        "biorxiv_query": generated.get("biorxiv_query") or "",
    }
    profile_id = upsert_profile(conn, profile_payload)
    profile = conn.execute("SELECT * FROM research_profiles WHERE id = ?", (profile_id,)).fetchone()
    return {
        "ok": True,
        "message": generated.get("rationale", "Generated profile from description."),
        "profile": row_to_profile(profile),
    }


def cmd_ingest(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    sources = as_list(payload.get("sources")) or ["arxiv", "biorxiv", "europepmc"]
    limit = int(payload.get("limit", 30))
    date_from = payload.get("date_from")
    date_to = payload.get("date_to")
    query = payload.get("query") or ""
    profile_ids = as_list(payload.get("profiles"))
    profile_query = ""
    profile_biorxiv_query = ""
    if not query and profile_ids:
        profile = conn.execute("SELECT * FROM research_profiles WHERE id = ? LIMIT 1", (profile_ids[0],)).fetchone()
        if profile:
            profile_query = profile["arxiv_query"] or or_query_for_terms(load_list(profile, "include_terms_json"))
            profile_biorxiv_query = profile["biorxiv_query"] or profile_query
    papers: list[dict[str, Any]] = []
    errors: list[str] = []
    if payload.get("demo"):
        papers.extend(demo_papers())
    for source in sources:
        try:
            if source == "arxiv":
                papers.extend(fetch_arxiv(query or profile_query or "cat:cs.LG OR cat:q-bio.GN OR cat:q-bio.QM", limit))
            elif source == "biorxiv":
                papers.extend(fetch_biorxiv(date_from, date_to, limit))
            elif source == "europepmc":
                papers.extend(fetch_europepmc(query or profile_biorxiv_query or "single cell OR protein design OR gene regulation", limit))
            elif source == "openalex":
                papers.extend(fetch_openalex(query or "single cell protein design", limit))
            elif source == "semantic_scholar":
                papers.extend(fetch_semantic_scholar(query or "single cell protein design", limit))
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    inserted = 0
    updated = 0
    for paper in papers:
        try:
            _, was_inserted = upsert_paper(conn, paper)
            inserted += int(was_inserted)
            updated += int(not was_inserted)
        except Exception as exc:
            errors.append(f"upsert: {exc}")
    conn.commit()
    return {"ok": True, "inserted": inserted, "updated": updated, "total": len(papers), "errors": errors}


def cmd_search(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query", "")).strip()
    if not query:
        return {"ok": True, "papers": []}
    mode = payload.get("mode", "relevance")
    profile_id = payload.get("profile_id")
    limit = int(payload.get("limit", 40))
    if payload.get("live"):
        sources = ["arxiv", "europepmc"]
        if mode == "explore":
            sources.extend(["openalex", "semantic_scholar"])
        cmd_ingest(conn, {"sources": sources, "query": query, "limit": min(limit, 50)})
    rank_papers(conn, [profile_id] if profile_id else None)
    return {"ok": True, "papers": local_search(conn, query, limit, profile_id)}


def cmd_rank(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    profile_ids = as_list(payload.get("profile_ids")) or None
    scored = rank_papers(conn, profile_ids)
    return {"ok": True, "scored": scored}


def cmd_list_papers(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = payload.get("profile_id")
    limit = int(payload.get("limit", 80))
    query = payload.get("query")
    return {"ok": True, "papers": list_papers(conn, profile_id, limit, query)}


def cmd_feedback(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    paper_id = payload["paper_id"]
    profile_id = payload.get("profile_id")
    if not profile_id:
        profile = conn.execute("SELECT id FROM research_profiles ORDER BY name LIMIT 1").fetchone()
        profile_id = profile["id"]
    action = payload["action"]
    if action not in ACTIONS:
        raise ValueError(f"unknown feedback action: {action}")
    conn.execute(
        """
        INSERT OR IGNORE INTO feedback (id, paper_id, profile_id, action, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (f"feedback:{uuid.uuid4().hex}", paper_id, profile_id, action, now_iso()),
    )
    conn.commit()
    return {"ok": True, "message": f"Saved {action} feedback."}


def cmd_read_papers(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = payload.get("profile_id")
    limit = int(payload.get("limit", 200))
    if not profile_id:
        profile = conn.execute("SELECT id FROM research_profiles ORDER BY name LIMIT 1").fetchone()
        profile_id = profile["id"] if profile else None
    if not profile_id:
        return {"ok": True, "papers": []}
    rows = conn.execute(
        """
        SELECT DISTINCT p.*
        FROM papers p
        JOIN feedback f ON f.paper_id = p.id
        WHERE f.profile_id = ? AND f.action = 'read'
        ORDER BY COALESCE(p.published_date, p.created_at) DESC
        LIMIT ?
        """,
        (profile_id, limit),
    ).fetchall()
    papers = []
    for row in rows:
        score = conn.execute(
            "SELECT * FROM paper_scores WHERE paper_id = ? AND profile_id = ?",
            (row["id"], profile_id),
        ).fetchone()
        action_rows = conn.execute(
            "SELECT action FROM feedback WHERE paper_id = ? AND profile_id = ? ORDER BY action",
            (row["id"], profile_id),
        ).fetchall()
        export_rows = conn.execute(
            "SELECT target FROM paper_exports WHERE paper_id = ? ORDER BY target",
            (row["id"],),
        ).fetchall()
        analysis = conn.execute(
            """
            SELECT status FROM paper_analyses
            WHERE paper_id = ? AND profile_id = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (row["id"], profile_id),
        ).fetchone()
        papers.append(
            row_to_paper(
                row,
                score,
                actions=[action["action"] for action in action_rows],
                exports=[export_row["target"] for export_row in export_rows],
                analysis_status=analysis["status"] if analysis else None,
            )
        )
    return {"ok": True, "papers": papers}


def cmd_analyze(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    paper_id = payload["paper_id"]
    profile_id = payload.get("profile_id")
    paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if not paper:
        raise ValueError(f"paper not found: {paper_id}")
    if not profile_id:
        profile = conn.execute("SELECT * FROM research_profiles ORDER BY name LIMIT 1").fetchone()
    else:
        profile = conn.execute("SELECT * FROM research_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not profile:
        raise ValueError("profile not found")
    profile_id = profile["id"]
    score = conn.execute(
        "SELECT * FROM paper_scores WHERE paper_id = ? AND profile_id = ?",
        (paper_id, profile_id),
    ).fetchone()
    model = payload.get("model") or "deepseek-v4-flash"
    system = (
        "You are a scientific literature triage assistant. Return strict JSON with keys: "
        "one_sentence, research_question, methods_data, core_findings, relationship_to_profile, "
        "limitations, worth_reading, memory_target."
    )
    user = json.dumps(
        {
            "profile": row_to_profile(profile),
            "paper": row_to_paper(paper, score),
            "instruction": "Analyze only from the supplied title, abstract, metadata, and profile.",
        },
        ensure_ascii=False,
    )
    try:
        analysis = deepseek_json(model, system, user)
        status = "llm"
    except Exception as exc:
        analysis = local_analysis(paper, profile, score)
        analysis["llm_error"] = str(exc)
        status = "local_triage"
    save_analysis(conn, paper_id, profile_id, model, status, analysis)
    return {"ok": True, "status": status, "analysis": analysis}


def cmd_usefulness(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    paper_id = payload["paper_id"]
    profile_id = payload.get("profile_id")
    paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if not paper:
        raise ValueError(f"paper not found: {paper_id}")
    if not profile_id:
        profile = conn.execute("SELECT * FROM research_profiles ORDER BY name LIMIT 1").fetchone()
    else:
        profile = conn.execute("SELECT * FROM research_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not profile:
        raise ValueError("profile not found")
    profile_id = profile["id"]
    score = conn.execute(
        "SELECT * FROM paper_scores WHERE paper_id = ? AND profile_id = ?",
        (paper_id, profile_id),
    ).fetchone()
    memory_notes = [
        row_to_note(row)
        for row in conn.execute(
            "SELECT * FROM memory_notes WHERE profile_id = ? ORDER BY updated_at DESC LIMIT 8",
            (profile_id,),
        ).fetchall()
    ]
    read_context = cmd_read_papers(conn, {"profile_id": profile_id, "limit": 12})["papers"]
    paper_payload = row_to_paper(paper, score)
    model = payload.get("model") or "deepseek-v4-pro"
    system = load_prompt("paper_usefulness")
    user = json.dumps(
        {
            "profile": row_to_profile(profile),
            "candidate_paper": paper_payload,
            "existing_memory_notes": memory_notes,
            "saved_or_read_papers": read_context,
        },
        ensure_ascii=False,
    )
    if not get_deepseek_api_key("reader"):
        raise RuntimeError(
            "DeepSeek reader API key is required to write usefulness analysis into long-term memory."
        )
    analysis = deepseek_json(model, system, user)
    status = "llm_usefulness"
    save_analysis(conn, paper_id, profile_id, model, status, analysis)
    conn.execute(
        """
        INSERT OR IGNORE INTO feedback (id, paper_id, profile_id, action, created_at)
        VALUES (?, ?, ?, 'read', ?)
        """,
        (f"feedback:{uuid.uuid4().hex}", paper_id, profile_id, now_iso()),
    )
    note_id = f"note:{uuid.uuid4().hex}"
    title = f"Usefulness: {paper['title'][:96]}"
    content = analysis.get("markdown") or json.dumps(analysis, ensure_ascii=False, indent=2)
    conn.execute(
        """
        INSERT INTO memory_notes (id, profile_id, type, title, markdown_path, content, updated_at)
        VALUES (?, ?, 'overview', ?, NULL, ?, ?)
        """,
        (note_id, profile_id, title, content, now_iso()),
    )
    conn.commit()
    if payload.get("obsidian_path"):
        export_obsidian(conn, Path(payload["obsidian_path"]), profile_id)
    return {"ok": True, "status": status, "analysis": analysis}


def cmd_synthesize(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = payload.get("profile_id")
    if not profile_id:
        profile = conn.execute("SELECT * FROM research_profiles ORDER BY name LIMIT 1").fetchone()
    else:
        profile = conn.execute("SELECT * FROM research_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not profile:
        raise ValueError("profile not found")
    profile_id = profile["id"]
    note_type = payload.get("type", "weekly_digest")
    if note_type not in NOTE_TYPES:
        raise ValueError(f"unknown note type: {note_type}")
    papers = list_papers(conn, profile_id, limit=12)
    title = f"{profile['name']} weekly digest {today()}"
    model = payload.get("model") or "deepseek-v4-pro"
    if not get_deepseek_api_key("reader"):
        raise RuntimeError("DeepSeek reader API key is required to synthesize long-term memory.")
    system = (
        "You synthesize a research profile's weekly literature updates. "
        "Return strict JSON with a markdown field. This is long-term memory, not a paper list: "
        "focus on knowledge-map updates, claim/evidence changes, open questions, and preference updates."
    )
    user = json.dumps({"profile": row_to_profile(profile), "papers": papers}, ensure_ascii=False)
    result = deepseek_json(model, system, user)
    content = result.get("markdown")
    if not content:
        raise RuntimeError("DeepSeek synthesis returned no markdown field.")
    status = "llm"

    note_id = f"note:{uuid.uuid4().hex}"
    conn.execute(
        """
        INSERT INTO memory_notes (id, profile_id, type, title, markdown_path, content, updated_at)
        VALUES (?, ?, ?, ?, NULL, ?, ?)
        """,
        (note_id, profile_id, note_type, title, content, now_iso()),
    )
    conn.commit()
    if payload.get("obsidian_path"):
        export_obsidian(conn, Path(payload["obsidian_path"]), profile_id)
    notes = conn.execute(
        "SELECT * FROM memory_notes WHERE profile_id = ? ORDER BY updated_at DESC",
        (profile_id,),
    ).fetchall()
    return {
        "ok": True,
        "status": status,
        "notes": [row_to_note(row) for row in notes],
    }


def row_to_note(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "type": row["type"],
        "title": row["title"],
        "markdown_path": row["markdown_path"],
        "content": row["content"],
        "updated_at": row["updated_at"],
    }


def cmd_memory_list(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = payload.get("profile_id")
    include_content = bool(payload.get("include_content", True))
    content_expr = "content" if include_content else "substr(content, 1, 700) AS content"
    select_expr = f"id, profile_id, type, title, markdown_path, {content_expr}, updated_at"
    if profile_id:
        rows = conn.execute(
            f"SELECT {select_expr} FROM memory_notes WHERE profile_id = ? ORDER BY updated_at DESC",
            (profile_id,),
        ).fetchall()
    else:
        rows = conn.execute(f"SELECT {select_expr} FROM memory_notes ORDER BY updated_at DESC").fetchall()
    return {"ok": True, "notes": [row_to_note(row) for row in rows]}


def cmd_memory_get(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = payload.get("id")
    if not note_id:
        raise ValueError("memory note id is required")
    row = conn.execute("SELECT * FROM memory_notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        raise ValueError(f"memory note not found: {note_id}")
    return {"ok": True, "note": row_to_note(row)}


def cmd_export(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    fmt = payload.get("format", "obsidian")
    path = payload.get("path")
    if not path:
        raise ValueError("export path is required")
    profile_id = payload.get("profile_id")
    if fmt == "obsidian":
        files = export_obsidian(conn, Path(path), profile_id)
    elif fmt == "zotero":
        files = export_zotero(conn, Path(path), profile_id)
    else:
        raise ValueError(f"unknown export format: {fmt}")
    return {"ok": True, "files": files}


def cmd_zotero_import(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    path = payload.get("path")
    if not path:
        raise ValueError("Zotero export path is required")
    papers = parse_zotero_export(Path(path))
    inserted_ids: list[str] = []
    for paper in papers:
        paper["source"] = "zotero"
        paper_id, _ = upsert_paper(conn, paper)
        inserted_ids.append(paper_id)
    conn.commit()
    rank_papers(conn)
    return {"ok": True, "papers": papers_by_ids(conn, inserted_ids)}


def cmd_integrate_papers(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    paper_ids = as_list(payload.get("paper_ids"))
    if not paper_ids:
        raise ValueError("paper_ids is required")
    progress_path = payload.get("progress_path")
    write_progress(
        progress_path,
        "preparing",
        0,
        len(paper_ids),
        f"Preparing {len(paper_ids)} papers for long-term memory integration",
    )
    profile_id = payload.get("profile_id")
    if not profile_id:
        profile = conn.execute("SELECT * FROM research_profiles ORDER BY name LIMIT 1").fetchone()
    else:
        profile = conn.execute("SELECT * FROM research_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not profile:
        raise ValueError("profile not found")
    profile_id = profile["id"]

    if not get_deepseek_api_key("reader"):
        write_progress(
            progress_path,
            "failed",
            0,
            1,
            "DeepSeek reader API key is required for long-term memory integration",
        )
        raise RuntimeError(
            "DeepSeek reader API key is required for Zotero long-term memory integration. "
            "Add it in Settings > DeepSeek > Reading and synthesis API key."
        )

    write_progress(progress_path, "ranking", 0, 1, "Refreshing relevance scores")
    rank_papers(conn, [profile_id])
    write_progress(progress_path, "ranking", 1, 1, "Relevance scores refreshed")

    papers = papers_by_ids(conn, paper_ids, profile_id)
    contexts = build_zotero_reading_contexts(papers, progress_path)
    memory_notes = [
        row_to_note(row)
        for row in conn.execute(
            "SELECT * FROM memory_notes WHERE profile_id = ? ORDER BY updated_at DESC LIMIT 10",
            (profile_id,),
        ).fetchall()
    ]

    title = f"{profile['name']} Zotero integration {today()} ({len(papers)} papers)"
    model = payload.get("model") or "deepseek-v4-pro"
    try:
        batch_results = synthesize_zotero_batches(profile, memory_notes, contexts, model, progress_path)
        content = final_zotero_memory_merge(profile, memory_notes, batch_results, contexts, model, progress_path)
        status = "llm_chunked"
    except Exception as exc:
        write_progress(
            progress_path,
            "failed",
            0,
            1,
            "DeepSeek synthesis failed; memory note was not written",
            str(exc),
        )
        raise RuntimeError(f"DeepSeek long-term memory integration failed: {exc}") from exc

    write_progress(progress_path, "saving_feedback", 0, len(paper_ids), "Saving selected papers as read/saved")
    for paper_id in paper_ids:
        conn.execute(
            """
            INSERT OR IGNORE INTO feedback (id, paper_id, profile_id, action, created_at)
            VALUES (?, ?, ?, 'save', ?)
            """,
            (f"feedback:{uuid.uuid4().hex}", paper_id, profile_id, now_iso()),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO feedback (id, paper_id, profile_id, action, created_at)
            VALUES (?, ?, ?, 'read', ?)
            """,
            (f"feedback:{uuid.uuid4().hex}", paper_id, profile_id, now_iso()),
        )
    conn.commit()
    write_progress(progress_path, "saving_feedback", len(paper_ids), len(paper_ids), "Selected papers saved as read")

    write_progress(progress_path, "writing_memory", 0, 1, "Writing memory note")
    note_id = f"note:{uuid.uuid4().hex}"
    conn.execute(
        """
        INSERT INTO memory_notes (id, profile_id, type, title, markdown_path, content, updated_at)
        VALUES (?, ?, 'overview', ?, NULL, ?, ?)
        """,
        (note_id, profile_id, title, content, now_iso()),
    )
    conn.commit()
    write_progress(progress_path, "writing_memory", 1, 1, "Memory note saved")

    if payload.get("obsidian_path"):
        write_progress(progress_path, "exporting_obsidian", 0, 1, "Exporting updated Obsidian notes")
        export_obsidian(conn, Path(payload["obsidian_path"]), profile_id)
        write_progress(progress_path, "exporting_obsidian", 1, 1, "Obsidian export complete")

    rows = conn.execute(
        "SELECT * FROM memory_notes WHERE profile_id = ? ORDER BY updated_at DESC",
        (profile_id,),
    ).fetchall()
    write_progress(progress_path, "done", len(papers), len(papers), "Long-term memory integration complete")
    return {"ok": True, "status": status, "notes": [row_to_note(row) for row in rows]}


COMMANDS = {
    "init": cmd_init,
    "profile-list": cmd_profile_list,
    "profile-upsert": cmd_profile_upsert,
    "profile-delete": cmd_profile_delete,
    "profile-from-description": cmd_profile_from_description,
    "ingest": cmd_ingest,
    "search": cmd_search,
    "rank": cmd_rank,
    "list-papers": cmd_list_papers,
    "read-papers": cmd_read_papers,
    "feedback": cmd_feedback,
    "analyze": cmd_analyze,
    "usefulness": cmd_usefulness,
    "synthesize": cmd_synthesize,
    "memory-list": cmd_memory_list,
    "memory-get": cmd_memory_get,
    "export": cmd_export,
    "zotero-import": cmd_zotero_import,
    "integrate-papers": cmd_integrate_papers,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="LiteratureRadar worker")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--db", default=os.environ.get("LITRADAR_DB", str(default_db_path())))
    args = parser.parse_args()

    try:
        payload = read_payload()
        with connect(Path(args.db)) as conn:
            init_db(conn)
            result = COMMANDS[args.command](conn, payload)
        emit(result)
        return 0
    except Exception as exc:
        emit({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
