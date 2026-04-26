import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "Sources" / "LiteratureRadar" / "Resources" / "worker" / "litradar.py"

spec = importlib.util.spec_from_file_location("litradar_worker", WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class WorkerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="litradar-test-"))
        self.db_path = self.tmp / "radar.sqlite3"
        for key in ["DEEPSEEK_API_KEY", "DEEPSEEK_READER_API_KEY", "DEEPSEEK_FLASH_API_KEY"]:
            os.environ.pop(key, None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_worker(self, command, payload=None, expect_ok=True):
        payload = payload or {}
        db = worker.Database(self.db_path)
        try:
            try:
                data = worker.COMMANDS[command](db, payload)
            except Exception as exc:
                data = {"ok": False, "error": str(exc), "type": exc.__class__.__name__}
        finally:
            db.close()
        if expect_ok:
            self.assertTrue(data.get("ok"), data)
        else:
            self.assertFalse(data.get("ok"), data)
        return data

    def test_init_demo_rank_search_and_dashboard(self):
        self.run_worker("init", {"seed_demo": True})
        profiles = self.run_worker("profile-list")
        self.assertEqual(len(profiles["profiles"]), 1)
        profile_id = profiles["profiles"][0]["id"]

        papers = self.run_worker("list-papers")
        self.assertGreaterEqual(len(papers["papers"]), 3)

        ranked = self.run_worker("rank", {"profile_id": profile_id})
        self.assertGreaterEqual(ranked["scored"], 3)

        found = self.run_worker("search", {"query": "graph memory", "limit": 5})
        titles = "\n".join(p["title"] for p in found["papers"])
        self.assertIn("Graph-based agent memory", titles)

        dashboard = self.run_worker("memory-dashboard", {"profile_id": profile_id})["dashboard"]
        self.assertEqual(dashboard["counts"]["papers"], 3)
        self.assertEqual(dashboard["counts"]["methodology_rules"], 3)
        self.assertGreater(dashboard["health"]["score"], 0.8)

    def test_local_analyze_does_not_write_memory_without_key(self):
        self.run_worker("init", {"seed_demo": True})
        out = self.run_worker("analyze", {"paper_id": "demo_graph_agent_memory"})
        self.assertEqual(out["status"], "local_triage")
        notes = self.run_worker("memory-list")
        self.assertEqual(notes["notes"], [])

    def test_usefulness_requires_reader_key_before_writing(self):
        self.run_worker("init", {"seed_demo": True})
        out = self.run_worker("usefulness", {"paper_id": "demo_graph_agent_memory", "profile_id": "default_profile"}, expect_ok=False)
        self.assertIn("DeepSeek V4 Pro API key is required", out["error"])
        notes = self.run_worker("memory-list")
        self.assertEqual(notes["notes"], [])
        read = self.run_worker("read-papers")
        self.assertEqual(read["papers"], [])

    def test_profile_generation_requires_api_key(self):
        self.run_worker("init", {"seed_demo": True})
        out = self.run_worker("profile-from-description", {"description": "agent memory and GraphRAG"}, expect_ok=False)
        self.assertIn("DeepSeek V4 Flash API key is required", out["error"])

    def test_feedback_updates_interest_and_events(self):
        self.run_worker("init", {"seed_demo": True})
        self.run_worker("feedback", {"paper_id": "demo_graph_agent_memory", "profile_id": "default_profile", "action": "like"})
        with sqlite3.connect(self.db_path) as conn:
            event_count = conn.execute("SELECT COUNT(*) FROM episodic_events").fetchone()[0]
            liked = conn.execute("SELECT COUNT(*) FROM interest_states WHERE topic IN ('agent memory', 'long-term memory')").fetchone()[0]
        self.assertGreaterEqual(event_count, 1)
        self.assertGreaterEqual(liked, 1)

    def test_context_packet_and_taxonomy_are_logged(self):
        self.run_worker("init", {"seed_demo": True})
        ctx = self.run_worker("context-packet", {"query": "agent memory", "profile_id": "default_profile"})
        self.assertIn("context_packet_id", ctx)
        self.assertIn("forbidden_assumptions", ctx["packet"])
        tax = self.run_worker("rebuild-taxonomy", {"profile_id": "default_profile"})
        self.assertIn("taxonomy_version_id", tax)
        with sqlite3.connect(self.db_path) as conn:
            ctx_count = conn.execute("SELECT COUNT(*) FROM context_packets").fetchone()[0]
            trace_count = conn.execute("SELECT COUNT(*) FROM retrieval_traces").fetchone()[0]
            tax_count = conn.execute("SELECT COUNT(*) FROM taxonomy_versions").fetchone()[0]
        self.assertEqual(ctx_count, 1)
        self.assertEqual(trace_count, 1)
        self.assertEqual(tax_count, 1)

    def test_zotero_import_and_integrate_failure_has_progress(self):
        self.run_worker("init", {"seed_demo": True})
        export_dir = self.tmp / "zotero"
        pdf_dir = export_dir / "files" / "399"
        pdf_dir.mkdir(parents=True)
        (pdf_dir / "Bergen 2020 scVelo.pdf").write_text("not really a pdf", encoding="utf-8")
        (export_dir / "library.bib").write_text(
            """
@article{bergen_generalizing_2020,
  title = {Generalizing RNA velocity to transient cell states through dynamical modeling},
  author = {Bergen, Volker and Lange, Marius},
  year = {2020},
  journal = {Nature Biotechnology},
  doi = {10.1038/s41587-020-0591-3},
  url = {https://doi.org/10.1038/s41587-020-0591-3},
  file = {Bergen 等 - 2020 - Generalizing RNA velocity.pdf:files/399/Bergen 2020 scVelo.pdf:application/pdf}
}
""".strip(),
            encoding="utf-8",
        )
        import_progress = self.tmp / "import-progress.json"
        imported = self.run_worker("zotero-import", {"path": str(export_dir), "progress_path": str(import_progress)})
        self.assertEqual(imported["count"], 1)
        self.assertEqual(json.loads(import_progress.read_text(encoding="utf-8"))["phase"], "done")
        paper_id = imported["papers"][0]["id"]
        self.assertTrue(imported["papers"][0]["pdf_path"].endswith("Bergen 2020 scVelo.pdf"))
        out = self.run_worker(
            "integrate-papers",
            {"paper_ids": [paper_id], "profile_id": "default_profile", "progress_path": str(self.tmp / "progress.json")},
            expect_ok=False,
        )
        self.assertIn("DeepSeek V4 Pro API key is required", out["error"])
        progress = json.loads((self.tmp / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["phase"], "failed")
        self.assertEqual(progress["completed"], 0)
        read = self.run_worker("read-papers")
        self.assertEqual(read["papers"], [])

    def test_zotero_import_direct_bib_handles_nested_braces_and_multiple_files(self):
        self.run_worker("init", {"seed_demo": True})
        export_dir = self.tmp / "zotero-direct"
        pdf_dir = export_dir / "files" / "ABC"
        pdf_dir.mkdir(parents=True)
        (pdf_dir / "Nested Title Paper.pdf").write_text("pdf text", encoding="utf-8")
        bib = export_dir / "export.bib"
        bib.write_text(
            """
@article{demo_nested_2024,
  title = {{GraphRAG} for {Long-Term} Agent Memory},
  author = {Zhang, Rui and Smith, Ada},
  date = {2024-03-01},
  abstract = {A Zotero export with nested braces should still import.},
  file = {Snapshot:/tmp/not-a-paper.html:text/html;Full Text:files/ABC/Nested Title Paper.pdf:application/pdf}
}
""".strip(),
            encoding="utf-8",
        )

        imported = self.run_worker("zotero-import", {"path": str(bib)})
        self.assertEqual(imported["count"], 1)
        paper = imported["papers"][0]
        self.assertEqual(paper["title"], "GraphRAG for Long-Term Agent Memory")
        self.assertEqual(paper["published_date"], "2024")
        self.assertTrue(paper["pdf_path"].endswith("Nested Title Paper.pdf"))

    def test_zotero_import_updates_existing_doi_without_unique_conflict(self):
        self.run_worker("init", {"seed_demo": False})
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            worker.upsert_paper(
                conn,
                {
                    "id": "manual_existing",
                    "source": "local",
                    "doi": "10.5555/existing",
                    "title": "Old local title",
                    "abstract": "already here",
                    "authors": [],
                },
            )
            conn.execute("CREATE UNIQUE INDEX idx_test_papers_doi ON papers(doi)")
            conn.commit()

        bib = self.tmp / "duplicate-doi.bib"
        bib.write_text(
            """
@article{new_export,
  title = {Updated Zotero title},
  author = {Zotero, Export},
  year = {2026},
  doi = {https://doi.org/10.5555/existing},
  abstract = {This should update the old DOI row instead of inserting another row.}
}
""".strip(),
            encoding="utf-8",
        )
        imported = self.run_worker("zotero-import", {"path": str(bib)})
        self.assertEqual(imported["count"], 1)
        self.assertEqual(imported["papers"][0]["id"], "manual_existing")
        self.assertEqual(imported["papers"][0]["title"], "Updated Zotero title")


if __name__ == "__main__":
    unittest.main()
