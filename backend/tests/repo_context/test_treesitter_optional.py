from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from atenex_nova.repo_context.composition import build_runtime
from atenex_nova.repo_context.domain.models import FileRecord
from atenex_nova.repo_context.infrastructure.parsers import (
    DefaultLanguageExtractor,
    OptionalTreeSitterExtractor,
)


class OptionalTreeSitterTests(unittest.TestCase):
    def test_parser_version_changes_with_tree_sitter_capability(self) -> None:
        unavailable = {
            "adapter": "tree-sitter-language-pack",
            "package_version": "1.13.0",
            "grammars": {"typescript": False},
        }
        available = {
            "adapter": "tree-sitter-language-pack",
            "package_version": "1.13.0",
            "grammars": {"typescript": True},
        }
        target = (
            "atenex_nova.repo_context.infrastructure.parsers.registry."
            "OptionalTreeSitterExtractor.implementation_identity"
        )
        with patch(target, return_value=unavailable):
            fallback_version = DefaultLanguageExtractor().parser_version
            repeated_fallback_version = DefaultLanguageExtractor().parser_version
        with patch(target, return_value=available):
            ast_version = DefaultLanguageExtractor().parser_version

        self.assertNotEqual(fallback_version, ast_version)
        self.assertEqual(fallback_version, repeated_fallback_version)

    def test_composition_persists_extractor_parser_version(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "example.py").write_text("value = 1\n", encoding="utf-8")
            runtime = build_runtime(repo=root, data_dir=root / "derived")

            snapshot = runtime.scanner.scan().snapshot
            extractor = runtime.extractors[0]
            self.assertIsInstance(extractor, DefaultLanguageExtractor)
            assert isinstance(extractor, DefaultLanguageExtractor)
            self.assertEqual(
                snapshot.parser_version,
                extractor.parser_version,
            )

    def test_dependency_absence_uses_explicit_pattern_fallback(self) -> None:
        with patch(
            "atenex_nova.repo_context.infrastructure.parsers.treesitter."
            "importlib.import_module",
            side_effect=ModuleNotFoundError("tree_sitter_language_pack"),
        ):
            result = DefaultLanguageExtractor().extract(
                _file(
                    "src/service.ts",
                    "typescript",
                    'import { Base } from "./base";\n'
                    "export class Service extends Base {\n"
                    "  run() { return execute(); }\n"
                    "}\n",
                )
            )

        self.assertIn(
            "tree_sitter_unavailable",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        fallback = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "tree_sitter_unavailable"
        )
        self.assertEqual(fallback.details["fallback"], "js_pattern")
        self.assertEqual({edge.method for edge in result.edges}, {"js_pattern"})
        self.assertIn("Service", {symbol.name for symbol in result.symbols})

    def test_real_ast_fixtures_for_all_supported_languages(self) -> None:
        unavailable = _unavailable_languages()
        if unavailable:
            self.skipTest(
                "preloaded Tree-sitter grammars unavailable: "
                + ", ".join(f"{name} ({reason})" for name, reason in unavailable)
            )
        extractor = DefaultLanguageExtractor(max_chunk_lines=3, max_chunk_chars=256)
        fixtures = {
            "typescript": (
                "src/service.ts",
                'import { Base } from "./base";\n'
                "export class Service extends Base implements Runnable {\n"
                "  run(id: string) { return repository.load(id); }\n"
                "}\n"
                "export const create = (id: string) => validate(id);\n",
            ),
            "tsx": (
                "src/App.tsx",
                'import React from "react";\n'
                "export function App() {\n"
                "  return <Button onClick={() => save()} />;\n"
                "}\n",
            ),
            "javascript": (
                "src/service.js",
                'const dependency = require("./dependency");\n'
                "class Service extends Base {\n"
                "  run() { return dependency.execute(); }\n"
                "}\n",
            ),
            "java": (
                "src/OrderService.java",
                "package example.orders;\n"
                "import example.Base;\n"
                "class OrderService extends Base implements Runnable {\n"
                "  public void run() { repository.load(); }\n"
                "}\n",
            ),
            "sql": (
                "db/001.sql",
                "CREATE TABLE orders(id INT REFERENCES customer(id));\n"
                "SELECT * FROM orders JOIN customer ON true;\n",
            ),
        }

        results = {
            language: extractor.extract(_file(path, language, source))
            for language, (path, source) in fixtures.items()
        }

        for language, result in results.items():
            with self.subTest(language=language):
                self.assertEqual(result.parse_state, "parsed")
                self.assertFalse(result.diagnostics)
                self.assertTrue(result.symbols)
                self.assertTrue(result.chunks)
                self.assertTrue(
                    all(
                        chunk.line_end - chunk.line_start + 1 <= 3
                        for chunk in result.chunks
                    )
                )
                self.assertEqual(
                    {edge.method for edge in result.edges},
                    {"tree_sitter"},
                )

        ts_relations = {
            (edge.relation, edge.target_name)
            for edge in results["typescript"].edges
        }
        self.assertGreaterEqual(
            ts_relations,
            {
                ("imports", "./base"),
                ("extends", "Base"),
                ("implements", "Runnable"),
                ("calls", "repository.load"),
                ("calls", "validate"),
                ("exports", "Service"),
                ("exports", "create"),
            },
        )
        self.assertNotIn(("exports", "Service.run"), ts_relations)
        self.assertTrue(
            any(
                symbol.kind == "method"
                and symbol.qualified_name.startswith("Service.run")
                for symbol in results["typescript"].symbols
            )
        )
        self.assertIn(
            ("calls", "save"),
            {
                (edge.relation, edge.target_name)
                for edge in results["tsx"].edges
            },
        )
        self.assertIn(
            ("imports", "./dependency"),
            {
                (edge.relation, edge.target_name)
                for edge in results["javascript"].edges
            },
        )
        self.assertIn(
            ("calls", "repository.load"),
            {
                (edge.relation, edge.target_name)
                for edge in results["java"].edges
            },
        )
        self.assertIn(
            ("declares_table", "orders"),
            {
                (edge.relation, edge.target_name)
                for edge in results["sql"].edges
            },
        )

    def test_error_nodes_are_diagnosed_and_fall_back_safely(self) -> None:
        available, reason = _availability("typescript")
        if not available:
            self.skipTest(f"preloaded TypeScript grammar unavailable: {reason}")
        result = DefaultLanguageExtractor().extract(
            _file(
                "src/broken.ts",
                "typescript",
                "export class Broken {\n  run( {\n",
            )
        )

        self.assertIn(
            "tree_sitter_parse_error",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertTrue(result.chunks)
        self.assertNotIn("tree_sitter", {edge.method for edge in result.edges})

    def test_stable_ids_from_real_ast(self) -> None:
        available, reason = _availability("java")
        if not available:
            self.skipTest(f"preloaded Java grammar unavailable: {reason}")
        file = _file(
            "src/Service.java",
            "java",
            "class Service {\n  void run() { helper.execute(); }\n}\n",
        )
        extractor = DefaultLanguageExtractor()

        first = extractor.extract(file)
        second = extractor.extract(file)

        self.assertEqual(
            [symbol.id for symbol in first.symbols],
            [symbol.id for symbol in second.symbols],
        )
        self.assertEqual(
            [edge.id for edge in first.edges],
            [edge.id for edge in second.edges],
        )


def _availability(language: str) -> tuple[bool, str | None]:
    return OptionalTreeSitterExtractor(
        max_chunk_lines=80,
        max_chunk_chars=12_000,
    ).availability(language)


def _unavailable_languages() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    extractor = OptionalTreeSitterExtractor(
        max_chunk_lines=80,
        max_chunk_chars=12_000,
    )
    for language in ("typescript", "tsx", "javascript", "java", "sql"):
        available, reason = extractor.availability(language)
        if not available:
            result.append((language, reason or "unknown"))
    return result


def _file(path: str, language: str, text: str) -> FileRecord:
    return FileRecord(
        path=path,
        language=language,
        content_hash=f"hash:{path}",
        size=len(text.encode()),
        git_status="M",
        text=text,
        line_count=len(text.splitlines()),
    )
