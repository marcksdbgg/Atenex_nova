"""Python extraction using the standard library AST."""

from __future__ import annotations

import ast

from atenex_nova.repo_context.domain.models import (
    CodeEdge,
    CodeSymbol,
    Diagnostic,
    ExtractionResult,
    FileRecord,
)
from atenex_nova.repo_context.infrastructure.parsers.common import (
    bounded_chunks,
    deduplicate_edges,
    make_edge,
    make_symbol,
    qualified_call_name,
)


class PythonExtractor:
    """Extract deterministic Python definitions and conservative references."""

    def __init__(self, *, max_chunk_lines: int, max_chunk_chars: int) -> None:
        self._max_chunk_lines = max_chunk_lines
        self._max_chunk_chars = max_chunk_chars

    def extract(self, file: FileRecord) -> ExtractionResult:
        chunks = bounded_chunks(
            file,
            max_lines=self._max_chunk_lines,
            max_chars=self._max_chunk_chars,
            kind="code",
        )
        try:
            tree = ast.parse(file.text, filename=file.path, type_comments=True)
        except (SyntaxError, ValueError) as exc:
            line = getattr(exc, "lineno", None)
            return ExtractionResult(
                chunks=chunks,
                diagnostics=(
                    Diagnostic(
                        code="python_parse_failed",
                        message=str(exc),
                        severity="warning",
                        path=file.path,
                        details={"line": line} if line else {},
                    ),
                ),
                parse_state="lexical",
            )

        visitor = _PythonVisitor(file)
        visitor.visit(tree)
        return ExtractionResult(
            chunks=chunks,
            symbols=tuple(
                sorted(
                    visitor.symbols,
                    key=lambda symbol: (
                        symbol.line_start,
                        symbol.line_end,
                        symbol.qualified_name,
                    ),
                )
            ),
            edges=deduplicate_edges(visitor.edges),
            diagnostics=tuple(visitor.diagnostics),
            parse_state="parsed",
        )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, file: FileRecord) -> None:
        self.file = file
        self.symbols: list[CodeSymbol] = []
        self.edges: list[CodeEdge] = []
        self.diagnostics: list[Diagnostic] = []
        self._scope: list[CodeSymbol] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol = self._definition(node, "class", _class_signature(node))
        for index, base in enumerate(node.bases):
            target = qualified_call_name(base) or ast.unparse(base)
            self.edges.append(
                make_edge(
                    self.file,
                    relation="extends",
                    source_symbol_id=symbol.id,
                    target_name=target,
                    evidence_line=node.lineno,
                    confidence=0.85,
                    method="python_ast",
                    discriminator=index,
                )
            )
        self._scope.append(symbol)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, async_function=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, async_function=True)

    def visit_Import(self, node: ast.Import) -> None:
        source = self._current_symbol_id()
        for index, alias in enumerate(node.names):
            self.edges.append(
                make_edge(
                    self.file,
                    relation="imports",
                    source_symbol_id=source,
                    target_name=alias.name,
                    evidence_line=node.lineno,
                    confidence=1.0,
                    method="python_ast",
                    discriminator=index,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        source = self._current_symbol_id()
        for index, alias in enumerate(node.names):
            target = f"{module}.{alias.name}".strip(".")
            self.edges.append(
                make_edge(
                    self.file,
                    relation="imports",
                    source_symbol_id=source,
                    target_name=target or alias.name,
                    evidence_line=node.lineno,
                    confidence=1.0,
                    method="python_ast",
                    discriminator=index,
                )
            )

    def visit_Call(self, node: ast.Call) -> None:
        target = qualified_call_name(node.func)
        if target:
            self.edges.append(
                make_edge(
                    self.file,
                    relation="calls",
                    source_symbol_id=self._current_symbol_id(),
                    target_name=target,
                    evidence_line=node.lineno,
                    confidence=0.72 if "." in target else 0.62,
                    method="python_ast",
                    discriminator=node.col_offset,
                )
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # ``__all__`` is explicit public API evidence, not a guessed export.
        if any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            values = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else ()
            for index, value in enumerate(values):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    self.edges.append(
                        make_edge(
                            self.file,
                            relation="exports",
                            source_symbol_id=self._current_symbol_id(),
                            target_name=value.value,
                            evidence_line=node.lineno,
                            confidence=1.0,
                            method="python_ast",
                            discriminator=index,
                        )
                    )
        self.generic_visit(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        async_function: bool,
    ) -> None:
        kind = "method" if self._scope and self._scope[-1].kind == "class" else "function"
        signature = _function_signature(node, async_function=async_function)
        symbol = self._definition(node, kind, signature)
        self._scope.append(symbol)
        self.generic_visit(node)
        self._scope.pop()

    def _definition(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        kind: str,
        signature: str,
    ) -> CodeSymbol:
        qualified_name = ".".join([*(scope.name for scope in self._scope), node.name])
        if any(
            existing.qualified_name == qualified_name and existing.kind == kind
            for existing in self.symbols
        ):
            # Python permits deliberate rebinding. Preserve both definitions
            # without making ordinary ids line-dependent.
            qualified_name = f"{qualified_name}@L{node.lineno}"
        parent = self._scope[-1].id if self._scope else None
        symbol = make_symbol(
            self.file,
            name=node.name,
            qualified_name=qualified_name,
            kind=kind,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
            signature=signature,
            parent_id=parent,
            role="test" if _is_test_symbol(node.name, self.file.path) else None,
        )
        self.symbols.append(symbol)
        if parent:
            self.edges.append(
                make_edge(
                    self.file,
                    relation="contains",
                    source_symbol_id=parent,
                    target_symbol_id=symbol.id,
                    target_name=symbol.qualified_name,
                    evidence_line=node.lineno,
                    confidence=1.0,
                    method="python_ast",
                    unresolved=False,
                )
            )
        return symbol

    def _current_symbol_id(self) -> str | None:
        return self._scope[-1].id if self._scope else None


def _function_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    async_function: bool,
) -> str:
    arguments = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async def" if async_function else "def"
    return f"{prefix} {node.name}({arguments}){returns}"


def _class_signature(node: ast.ClassDef) -> str:
    bases = ", ".join(ast.unparse(base) for base in node.bases)
    return f"class {node.name}({bases})" if bases else f"class {node.name}"


def _is_test_symbol(name: str, path: str) -> bool:
    path_parts = path.lower().split("/")
    return name.startswith("test_") or any(
        part in {"test", "tests", "__tests__"} for part in path_parts
    )
