"""Bounded exact search over the authoritative worktree."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from atenex_nova.repo_context.domain.policies import safe_relative_path


@dataclass(frozen=True, slots=True)
class ExactMatch:
    path: str
    line: int
    text: str


class ExactSearcher:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        path_prefix: str | None = None,
    ) -> list[ExactMatch]:
        if not query or limit < 1:
            return []
        if shutil.which("rg") is None:
            return []
        command = [
            "rg",
            "--json",
            "--fixed-strings",
            "--line-number",
            "--color",
            "never",
            "--max-count",
            str(limit),
            "--",
            query,
        ]
        if path_prefix:
            command.append(safe_relative_path(path_prefix))
        else:
            command.append(".")
        process = subprocess.run(
            command,
            cwd=self._root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if process.returncode not in (0, 1):
            return []
        matches: list[ExactMatch] = []
        for raw_line in process.stdout.splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event.get("data") or {}
            path_data = data.get("path") or {}
            lines_data = data.get("lines") or {}
            path_value = path_data.get("text")
            line_number = data.get("line_number")
            text_value = lines_data.get("text")
            if not isinstance(path_value, str) or not isinstance(line_number, int):
                continue
            try:
                relative = safe_relative_path(path_value.removeprefix("./"))
            except ValueError:
                continue
            matches.append(
                ExactMatch(
                    path=relative,
                    line=line_number,
                    text=str(text_value or "").rstrip("\r\n"),
                )
            )
            if len(matches) >= limit:
                break
        return matches
