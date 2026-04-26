import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "Sources" / "LiteratureRadar" / "Resources" / "worker" / "litradar.py"


class WorkerTests(unittest.TestCase):
    def run_worker(self, db_path, command, payload):
        env = os.environ.copy()
        env.pop("DEEPSEEK_API_KEY", None)
        env.pop("DEEPSEEK_FLASH_API_KEY", None)
        proc = subprocess.run(
            ["python3", str(WORKER), command, "--db", str(db_path)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"invalid JSON stdout: {proc.stdout!r}, stderr={proc.stderr!r}, error={exc}")
        if proc.returncode != 0:
            self.fail(f"worker failed: {data}, stderr={proc.stderr}")
        return data

    def run_worker_failure(self, db_path, command, payload):
        env = os.environ.copy()
        env.pop("DEEPSEEK_API_KEY", None)
        env.pop("DEEPSEEK_FLASH_API_KEY", None)
        proc = subprocess.run(
            ["python3", str(WORKER), command, "--db", str(db_path)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"invalid JSON stdout: {proc.stdout!r}, stderr={proc.stderr!r}, error={exc}")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(data["ok"])
        return data

    def test_demo_ingest_rank_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "radar.sqlite3"
            init = self.run_worker(db, "init", {"seed_demo": True})
            self.assertTrue(init["ok"])

            papers = self.run_worker(db, "list-papers", {"limit": 10})
            self.assertGreaterEqual(len(papers["papers"]), 3)
            relevant = next(p for p in papers["papers"] if "single-cell" in p["title"])

            profiles = self.run_worker(db, "profile-list", {})
            profile_id = profiles["profiles"][0]["id"]

            before = self.run_worker(db, "list-papers", {"profile_id": profile_id, "limit": 10})["papers"]
            before_score = next(p for p in before if p["id"] == relevant["id"])["score"]["final_score"]

            self.run_worker(db, "feedback", {"paper_id": relevant["id"], "profile_id": profile_id, "action": "like"})
            self.run_worker(db, "rank", {"profile_ids": [profile_id]})
            after = self.run_worker(db, "list-papers", {"profile_id": profile_id, "limit": 10})["papers"]
            after_score = next(p for p in after if p["id"] == relevant["id"])["score"]["final_score"]
            self.assertGreater(after_score, before_score)

    def test_search_and_local_analysis_without_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "radar.sqlite3"
            self.run_worker(db, "init", {"seed_demo": True})
            profiles = self.run_worker(db, "profile-list", {})
            profile_id = profiles["profiles"][0]["id"]
            search = self.run_worker(
                db,
                "search",
                {"query": "single-cell regulatory", "profile_id": profile_id, "live": False, "limit": 5},
            )
            self.assertTrue(search["papers"])
            paper_id = search["papers"][0]["id"]
            analysis = self.run_worker(
                db,
                "analyze",
                {"paper_id": paper_id, "profile_id": profile_id, "model": "deepseek-v4-flash"},
            )
            self.assertEqual(analysis["status"], "local_triage")
            self.assertIn("one_sentence", analysis["analysis"])

    def test_usefulness_requires_api_key_before_memory_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "radar.sqlite3"
            self.run_worker(db, "init", {"seed_demo": True})
            profiles = self.run_worker(db, "profile-list", {})
            profile_id = profiles["profiles"][0]["id"]
            papers = self.run_worker(db, "list-papers", {"profile_id": profile_id, "limit": 10})["papers"]
            paper_id = papers[0]["id"]
            failure = self.run_worker_failure(
                db,
                "usefulness",
                {"paper_id": paper_id, "profile_id": profile_id, "obsidian_path": str(Path(tmp) / "vault")},
            )
            self.assertIn("DeepSeek reader API key is required", failure["error"])
            read = self.run_worker(db, "read-papers", {"profile_id": profile_id})
            self.assertFalse(any(p["id"] == paper_id for p in read["papers"]))
            memory = self.run_worker(db, "memory-list", {"profile_id": profile_id})
            self.assertFalse(any("Usefulness:" in note["title"] for note in memory["notes"]))

    def test_profile_delete_preserves_last_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "radar.sqlite3"
            self.run_worker(db, "init", {})
            created = self.run_worker(
                db,
                "profile-upsert",
                {"name": "Temporary Profile", "include_terms": ["single cell"]},
            )
            self.assertTrue(created["ok"])
            profiles = self.run_worker(db, "profile-list", {})["profiles"]
            temp_id = next(profile["id"] for profile in profiles if profile["name"] == "Temporary Profile")
            deleted = self.run_worker(db, "profile-delete", {"id": temp_id})
            self.assertTrue(deleted["ok"])
            remaining = self.run_worker(db, "profile-list", {})["profiles"]
            self.assertFalse(any(profile["id"] == temp_id for profile in remaining))

    def test_profile_from_description_requires_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "radar.sqlite3"
            self.run_worker(db, "init", {})
            failure = self.run_worker_failure(
                db,
                "profile-from-description",
                {
                    "description": "Track single cell and single-cell perturbation papers in gene regulation. Optional scholar: Aviv Regev.",
                    "model": "deepseek-v4-flash",
                },
            )
            self.assertIn("DeepSeek API key is required", failure["error"])

    def test_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db = tmp_path / "radar.sqlite3"
            self.run_worker(db, "init", {"seed_demo": True})
            profiles = self.run_worker(db, "profile-list", {})
            profile_id = profiles["profiles"][0]["id"]

            obsidian = self.run_worker(
                db,
                "export",
                {"format": "obsidian", "path": str(tmp_path / "vault"), "profile_id": profile_id},
            )
            self.assertTrue(obsidian["files"])
            self.assertTrue((tmp_path / "vault" / "Profiles").exists())

            zotero = self.run_worker(
                db,
                "export",
                {"format": "zotero", "path": str(tmp_path / "zotero"), "profile_id": profile_id},
            )
            self.assertEqual(len(zotero["files"]), 3)
            self.assertTrue((tmp_path / "zotero" / "literature-radar.ris").exists())

    def test_zotero_import_and_integrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db = tmp_path / "radar.sqlite3"
            ris = tmp_path / "zotero.ris"
            ris.write_text(
                "\n".join(
                    [
                        "TY  - JOUR",
                        "TI  - Imported Zotero paper about single-cell perturbations",
                        "AU  - Doe, Jane",
                        "PY  - 2025",
                        "DO  - 10.1234/zotero.test",
                        "AB  - This paper studies single-cell perturbation maps for regulatory memory.",
                        "UR  - https://example.org/zotero",
                        "ER  - ",
                    ]
                ),
                encoding="utf-8",
            )
            self.run_worker(db, "init", {})
            profiles = self.run_worker(db, "profile-list", {})
            profile_id = profiles["profiles"][0]["id"]
            imported = self.run_worker(db, "zotero-import", {"path": str(ris)})
            self.assertEqual(len(imported["papers"]), 1)
            paper_id = imported["papers"][0]["id"]
            failure = self.run_worker_failure(
                db,
                "integrate-papers",
                {"paper_ids": [paper_id], "profile_id": profile_id, "obsidian_path": str(tmp_path / "vault")},
            )
            self.assertIn("DeepSeek reader API key is required", failure["error"])
            papers = self.run_worker(db, "list-papers", {"profile_id": profile_id})
            imported_paper = next(p for p in papers["papers"] if p["id"] == paper_id)
            self.assertNotIn("save", imported_paper["actions"])
            self.assertNotIn("read", imported_paper["actions"])

    def test_zotero_bib_folder_resolves_local_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db = tmp_path / "radar.sqlite3"
            export_dir = tmp_path / "zotero-export"
            pdf_dir = export_dir / "files" / "399"
            pdf_dir.mkdir(parents=True)
            pdf_path = pdf_dir / "Bergen 2020 scVelo.pdf"
            pdf_path.write_text(
                "Generalizing RNA velocity to transient cell states through dynamical modeling. "
                "This readable test fixture stands in for PDF text extraction.",
                encoding="utf-8",
            )
            bib = export_dir / "library.bib"
            bib.write_text(
                """
@article{bergen_2_2020,
  title = {[2, {scVelo}] {Generalizing} {RNA} velocity to transient cell states through dynamical modeling},
  doi = {10.1038/s41587-020-0591-3},
  journal = {Nat Biotechnol},
  author = {Bergen, Volker and Lange, Marius and Theis, Fabian J.},
  year = {2020},
  file = {Bergen 等 - 2020 - Generalizing RNA velocity.pdf:files/399/Bergen 2020 scVelo.pdf:application/pdf},
}
""",
                encoding="utf-8",
            )
            self.run_worker(db, "init", {})
            profiles = self.run_worker(db, "profile-list", {})
            profile_id = profiles["profiles"][0]["id"]
            imported = self.run_worker(db, "zotero-import", {"path": str(export_dir)})
            self.assertEqual(len(imported["papers"]), 1)
            imported_pdf = imported["papers"][0]["pdf_url"]
            self.assertEqual(Path(imported_pdf).resolve(strict=False), pdf_path.resolve(strict=False))
            progress_path = tmp_path / "progress.json"
            failure = self.run_worker_failure(
                db,
                "integrate-papers",
                {
                    "paper_ids": [imported["papers"][0]["id"]],
                    "profile_id": profile_id,
                    "obsidian_path": str(tmp_path / "vault"),
                    "progress_path": str(progress_path),
                },
            )
            self.assertIn("DeepSeek reader API key is required", failure["error"])
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(progress["phase"], "failed")


if __name__ == "__main__":
    unittest.main()
