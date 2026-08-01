from __future__ import annotations

import unittest

from atenex_nova.repo_context.application.repomap import (
    RepoMapBuilder,
    estimate_tokens,
)
from atenex_nova.repo_context.domain.models import (
    CodeEdge,
    CodeSymbol,
    FileRecord,
)
from atenex_nova.repo_context.infrastructure.parsers import (
    DefaultLanguageExtractor,
)


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


def _case_python_ast_extracts_symbols_imports_calls_and_inheritance() -> None:
    source = """\
from app.base import Base

class Checkout(Base):
    def execute(self, order_id: str) -> bool:
        return validate(order_id)

__all__ = ["Checkout"]
"""
    extractor = DefaultLanguageExtractor(max_chunk_lines=3, max_chunk_chars=256)

    first = extractor.extract(_file("src/checkout.py", "python", source))
    second = extractor.extract(_file("src/checkout.py", "python", source))

    assert first.parse_state == "parsed"
    assert [(item.kind, item.qualified_name) for item in first.symbols] == [
        ("class", "Checkout"),
        ("method", "Checkout.execute"),
    ]
    assert {(edge.relation, edge.target_name) for edge in first.edges} >= {
        ("imports", "app.base.Base"),
        ("extends", "Base"),
        ("calls", "validate"),
        ("exports", "Checkout"),
    }
    assert all(chunk.line_end - chunk.line_start + 1 <= 3 for chunk in first.chunks)
    assert [item.id for item in first.symbols] == [
        item.id for item in second.symbols
    ]
    assert len({item.id for item in first.symbols}) == len(first.symbols)
    assert len({item.id for item in first.edges}) == len(first.edges)


def _case_python_malformed_falls_back_with_diagnostic() -> None:
    result = DefaultLanguageExtractor().extract(
        _file("broken.py", "python", "def broken(:\n  pass\n")
    )

    assert result.parse_state == "lexical"
    assert result.chunks
    assert result.diagnostics[0].code == "python_parse_failed"


def _case_typescript_pattern_extractor_reports_explicit_evidence() -> None:
    source = """\
import { BaseService } from "./base";
export { helper } from "./helper";

export class OrderService extends BaseService implements Service {
  run(id: string) {
    return this.repository.load(id);
  }
}

export const STORE_ACTIVE_SQL = `sp.is_active = TRUE`;
export const createOrder = (id: string) => validate(id);
"""
    result = DefaultLanguageExtractor().extract(
        _file("src/order.ts", "typescript", source)
    )

    assert result.parse_state == "parsed"
    assert {(symbol.kind, symbol.name) for symbol in result.symbols} >= {
        ("class", "OrderService"),
        ("constant", "STORE_ACTIVE_SQL"),
        ("function", "createOrder"),
    }
    relations = {(edge.relation, edge.target_name) for edge in result.edges}
    assert ("imports", "./base") in relations
    assert ("exports", "./helper") in relations
    assert ("extends", "BaseService") in relations
    assert ("implements", "Service") in relations
    assert ("exports", "STORE_ACTIVE_SQL") in relations
    assert ("exports", "createOrder") in relations
    assert ("calls", "this.repository.load") in relations
    assert ("calls", "validate") in relations
    methods = {edge.method for edge in result.edges}
    assert methods in ({"js_pattern"}, {"tree_sitter"})
    assert all(edge.unresolved for edge in result.edges if edge.target_symbol_id is None)


def _case_sql_extracts_schema_symbols_and_table_access() -> None:
    source = """\
CREATE TABLE store_product_price (
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES product(id)
);
ALTER TABLE store_product_price ADD COLUMN currency TEXT;
INSERT INTO store_product_price(id) SELECT id FROM product;
UPDATE store_product_price SET currency = 'PEN';
"""
    result = DefaultLanguageExtractor(max_chunk_lines=20).extract(
        _file("db/migrations/001.sql", "sql", source)
    )

    assert ("table", "store_product_price") in {
        (symbol.kind, symbol.qualified_name) for symbol in result.symbols
    }
    relations = {(edge.relation, edge.target_name) for edge in result.edges}
    assert ("declares_table", "store_product_price") in relations
    assert ("alters_table", "store_product_price") in relations
    assert ("writes_table", "store_product_price") in relations
    assert ("reads_table", "product") in relations
    assert ("references", "product") in relations
    assert {chunk.kind for chunk in result.chunks} in (
        {"sql_statement"},
        {"tree_sitter_sql_statement"},
    )


def _case_java_extracts_types_overloaded_methods_and_calls() -> None:
    source = """\
package example.orders;
import example.Base;

public class OrderService extends Base implements Runnable {
    public void run() {
        repository.load();
    }

    public String find(String id) {
        return repository.find(id);
    }

    public String find(long id) {
        return repository.find(id);
    }
}
"""
    result = DefaultLanguageExtractor().extract(
        _file("src/OrderService.java", "java", source)
    )

    assert ("class", "example.orders.OrderService") in {
        (symbol.kind, symbol.qualified_name) for symbol in result.symbols
    }
    methods = [symbol for symbol in result.symbols if symbol.kind == "method"]
    assert {symbol.name for symbol in methods} == {"run", "find"}
    assert len(methods) == 3
    assert len({symbol.id for symbol in methods}) == 3
    relations = {(edge.relation, edge.target_name) for edge in result.edges}
    assert ("imports", "example.Base") in relations
    assert ("extends", "Base") in relations
    assert ("implements", "Runnable") in relations
    assert ("calls", "repository.load") in relations
    assert ("calls", "repository.find") in relations


def _case_markdown_config_shell_and_unsupported_text_are_bounded() -> None:
    extractor = DefaultLanguageExtractor(max_chunk_lines=2, max_chunk_chars=128)
    markdown = extractor.extract(
        _file(
            "README.md",
            "markdown",
            "# Setup\nSee [architecture](docs/architecture.md).\n"
            "# Setup\nSecond heading.\n",
        )
    )
    config = extractor.extract(
        _file("config.json", "json", '{"scripts": {"test": "pytest"}}')
    )
    shell = extractor.extract(
        _file("scripts/run.sh", "shell", "source ./env.sh\nrun() {\n echo ok\n}\n")
    )
    unknown = extractor.extract(_file("notes.xyz", "unknown", "one\ntwo\nthree\n"))

    assert len(markdown.symbols) == 2
    assert len({symbol.id for symbol in markdown.symbols}) == 2
    assert ("references", "docs/architecture.md") in {
        (edge.relation, edge.target_name) for edge in markdown.edges
    }
    assert {symbol.qualified_name for symbol in config.symbols} >= {
        "scripts",
        "scripts.test",
    }
    assert shell.symbols[0].name == "run"
    assert ("imports", "./env.sh") in {
        (edge.relation, edge.target_name) for edge in shell.edges
    }
    assert unknown.parse_state == "lexical"
    assert unknown.diagnostics[0].code == "unsupported_language"
    assert all(
        chunk.line_end - chunk.line_start + 1 <= 2 for chunk in unknown.chunks
    )


def _case_jsonc_comments_urls_and_trailing_commas_are_structural() -> None:
    result = DefaultLanguageExtractor().extract(
        _file(
            "tsconfig.json",
            "json",
            '{\n'
            '  // compiler configuration\n'
            '  "endpoint": "https://localhost/api",\n'
            '  "compilerOptions": {"strict": true,},\n'
            "}\n",
        )
    )

    assert result.parse_state == "parsed"
    assert not result.diagnostics
    assert {symbol.qualified_name for symbol in result.symbols} >= {
        "endpoint",
        "compilerOptions",
        "compilerOptions.strict",
    }


def _case_unbalanced_pattern_language_is_diagnosed_not_raised() -> None:
    result = DefaultLanguageExtractor().extract(
        _file("src/broken.ts", "typescript", "export function broken() {\n")
    )

    assert result.parse_state == "lexical"
    assert result.chunks
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        "unbalanced_braces"
    }


def _case_repomap_is_deterministic_focused_diverse_and_token_bounded() -> None:
    symbols = (
        _symbol("s-api", "src/api.py", "Api", "class", 1),
        _symbol("s-checkout", "src/checkout.py", "CheckoutService", "class", 2),
        _symbol("s-pay", "packages/payments.py", "PaymentGateway", "class", 3),
        _symbol("s-test", "tests/test_checkout.py", "test_checkout", "function", 4),
        _symbol("s-readme", "README.md", "Overview", "heading", 1),
    )
    edges = (
        _edge("e1", "src/api.py", "s-checkout", "CheckoutService"),
        _edge("e2", "src/checkout.py", "s-pay", "PaymentGateway"),
        _edge("e3", "tests/test_checkout.py", "s-checkout", "CheckoutService"),
    )
    files = (
        _file("src/api.py", "python", ""),
        _file("src/checkout.py", "python", ""),
        _file("packages/payments.py", "python", ""),
        _file("tests/test_checkout.py", "python", ""),
        _file("README.md", "markdown", ""),
    )
    builder = RepoMapBuilder()

    first = builder.build(
        symbols,
        edges,
        files=files,
        focus="checkout payment",
        max_tokens=48,
    )
    second = builder.build(
        symbols,
        edges,
        files=files,
        focus="checkout payment",
        max_tokens=48,
    )

    assert first == second
    assert first.estimated_tokens <= first.max_tokens
    assert estimate_tokens(first.rendered) == first.estimated_tokens
    assert first.entries
    assert first.entries[0].path in {
        "src/checkout.py",
        "packages/payments.py",
    }
    assert first.truncated
    assert len({entry.path.split("/", 1)[0] for entry in first.entries}) >= 2


def _case_repomap_zero_budget_is_empty() -> None:
    result = RepoMapBuilder().build(
        (_symbol("s", "src/app.py", "App", "class", 1),),
        (),
        max_tokens=0,
    )

    assert result.rendered == ""
    assert result.entries == ()
    assert result.estimated_tokens == 0
    assert result.truncated


def _case_repomap_retrieval_focus_overrides_unrelated_global_centrality() -> None:
    symbols = (
        _symbol("s-camera", "packages/scanner/src/camera.ts", "Camera", "class", 1),
        _symbol("s-sync", "apps/api/src/routes/sync.ts", "syncRoute", "function", 1),
    )
    files = (
        _file("packages/scanner/src/camera.ts", "typescript", ""),
        _file("apps/api/src/routes/sync.ts", "typescript", ""),
    )

    result = RepoMapBuilder().build(
        symbols,
        (),
        files=files,
        focus="flujo de venta offline y persistencia",
        focus_paths={"apps/api/src/routes/sync.ts": 1.0},
        max_tokens=100,
    )

    assert result.entries[0].path == "apps/api/src/routes/sync.ts"
    assert result.entries[0].focus_score == 1.0


class RepoParserMapTests(unittest.TestCase):
    def test_python_ast_extracts_symbols_imports_calls_and_inheritance(self) -> None:
        _case_python_ast_extracts_symbols_imports_calls_and_inheritance()

    def test_python_malformed_falls_back_with_diagnostic(self) -> None:
        _case_python_malformed_falls_back_with_diagnostic()

    def test_typescript_pattern_extractor_reports_explicit_evidence(self) -> None:
        _case_typescript_pattern_extractor_reports_explicit_evidence()

    def test_sql_extracts_schema_symbols_and_table_access(self) -> None:
        _case_sql_extracts_schema_symbols_and_table_access()

    def test_java_extracts_types_overloaded_methods_and_calls(self) -> None:
        _case_java_extracts_types_overloaded_methods_and_calls()

    def test_markdown_config_shell_and_unsupported_text_are_bounded(self) -> None:
        _case_markdown_config_shell_and_unsupported_text_are_bounded()

    def test_jsonc_comments_urls_and_trailing_commas_are_structural(self) -> None:
        _case_jsonc_comments_urls_and_trailing_commas_are_structural()

    def test_unbalanced_pattern_language_is_diagnosed_not_raised(self) -> None:
        _case_unbalanced_pattern_language_is_diagnosed_not_raised()

    def test_repomap_is_deterministic_focused_diverse_and_token_bounded(self) -> None:
        _case_repomap_is_deterministic_focused_diverse_and_token_bounded()

    def test_repomap_zero_budget_is_empty(self) -> None:
        _case_repomap_zero_budget_is_empty()

    def test_repomap_retrieval_focus_overrides_unrelated_global_centrality(self) -> None:
        _case_repomap_retrieval_focus_overrides_unrelated_global_centrality()


def _symbol(
    symbol_id: str,
    path: str,
    name: str,
    kind: str,
    line: int,
) -> CodeSymbol:
    return CodeSymbol(
        id=symbol_id,
        file_path=path,
        language="python",
        name=name,
        qualified_name=name,
        kind=kind,
        line_start=line,
        line_end=line + 3,
        signature=f"{kind} {name}",
    )


def _edge(
    edge_id: str,
    source_path: str,
    target_symbol_id: str,
    target_name: str,
) -> CodeEdge:
    return CodeEdge(
        id=edge_id,
        relation="calls",
        source_symbol_id=None,
        source_path=source_path,
        target_symbol_id=target_symbol_id,
        target_name=target_name,
        evidence_line=1,
        confidence=0.9,
        method="test",
        unresolved=False,
    )
