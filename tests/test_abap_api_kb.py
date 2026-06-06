"""ABAP API KB — bootstrap, codegen accumulate, RAG lookup."""

from __future__ import annotations

import unittest

from app import models
from app.abap_api_kb import (
    ENTRY_APPROVED,
    SOURCE_CODEGEN,
    accumulate_from_lint_issues,
    bootstrap_lint_kb_entries,
    dedupe_key_for_lint,
    lookup_rag_block_for_sources,
    lookup_rag_entries,
)
from app.database import Base, SessionLocal, engine
from app.delivered_abap_quality import lint_se38_semantic_patterns


class AbapApiKbTests(unittest.TestCase):
    def setUp(self):
        from app.main import _run_migrations

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        _run_migrations()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_bootstrap_creates_approved_lint_patterns(self):
        n = bootstrap_lint_kb_entries(self.db)
        self.assertGreater(n, 0)
        row = (
            self.db.query(models.AbapApiKbEntry)
            .filter(models.AbapApiKbEntry.dedupe_key == dedupe_key_for_lint("param_type_string"))
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.entry_status, ENTRY_APPROVED)

    def test_lint_accumulate_upserts_from_codegen(self):
        issues = lint_se38_semantic_patterns("PARAMETERS p_x TYPE string.", filename="t.abap")
        accumulate_from_lint_issues(issues)
        row = (
            self.db.query(models.AbapApiKbEntry)
            .filter(models.AbapApiKbEntry.error_code == "param_type_string")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.entry_status, ENTRY_APPROVED)
        self.assertEqual(row.source_kind, SOURCE_CODEGEN)
        self.assertGreaterEqual(int(row.occurrence_count or 0), 1)

    def test_lookup_rag_block_for_sources_non_empty_on_lint_match(self):
        bootstrap_lint_kb_entries(self.db)
        block = lookup_rag_block_for_sources(source="PARAMETERS p_path TYPE string.")
        self.assertIn("TYPE string", block)
        self.assertIn("Dev code API/syntax KB", block)

    def test_rag_lookup_uses_approved_bootstrap(self):
        bootstrap_lint_kb_entries(self.db)
        rows = lookup_rag_entries(self.db, source="PARAMETERS p_path TYPE string.")
        self.assertTrue(any(r.error_code == "param_type_string" for r in rows))
