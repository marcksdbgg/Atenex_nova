#!/usr/bin/env bash
set -euo pipefail

# Stable local launcher for GUI clients, whose PATH and working directory may
# differ from an interactive shell. A relative first argument follows a client
# worktree, while the second argument pins the Git repository identity expected
# by the project configuration. This prevents a user-scoped "." registration
# from silently serving whichever repository happens to be the GUI process cwd.
repo_argument="${1:-}"
expected_repository_argument="${2:-}"

if [[ -z "$repo_argument" ]]; then
  printf 'Atenex Repo Context requires an explicit repository argument.\n' >&2
  exit 2
fi
if [[ "$repo_argument" != /* && -z "$expected_repository_argument" ]]; then
  printf '%s\n' \
    'Atenex Repo Context relative repository arguments require an expected checkout root.' \
    'Do not register the launcher globally with "."; use the repository .mcp.json.' >&2
  exit 2
fi

repo_root="$(realpath --canonicalize-existing "$repo_argument")"

git_common_dir() {
  local root="$1"
  local common_dir
  common_dir="$(git -C "$root" rev-parse --git-common-dir 2>/dev/null)" || return 1
  if [[ "$common_dir" == /* ]]; then
    realpath --canonicalize-existing "$common_dir"
  else
    realpath --canonicalize-existing "$root/$common_dir"
  fi
}

if [[ -n "$expected_repository_argument" ]]; then
  expected_repository_root="$(realpath --canonicalize-existing "$expected_repository_argument")"
  repo_common_dir="$(git_common_dir "$repo_root")" || {
    printf 'Atenex Repo Context repository is not a Git checkout: %s\n' "$repo_root" >&2
    exit 2
  }
  expected_common_dir="$(git_common_dir "$expected_repository_root")" || {
    printf 'Atenex Repo Context expected root is not a Git checkout: %s\n' \
      "$expected_repository_root" >&2
    exit 2
  }
  if [[ "$repo_common_dir" != "$expected_common_dir" ]]; then
    printf '%s\n' \
      'Atenex Repo Context refused a repository binding mismatch.' \
      "Resolved repository: $repo_root" \
      "Expected checkout: $expected_repository_root" >&2
    exit 2
  fi
fi

install_root="$(realpath --canonicalize-existing "${ATENEX_CONTEXT_INSTALL_ROOT:-/mnt/ssd/Atenex/Atenex_nova}")"
runtime_root="${ATENEX_CONTEXT_RUNTIME_ROOT:-$install_root/backend/.venv-context-runtime}"
python_executable="${ATENEX_CONTEXT_PYTHON:-$install_root/backend/.venv-context/bin/python}"
grammar_cache="${ATENEX_CONTEXT_TREE_SITTER_CACHE:-$install_root/.atenex/context/tree-sitter}"

if [[ -n "${ATENEX_CONTEXT_DATA_DIR:-}" ]]; then
  data_dir="$ATENEX_CONTEXT_DATA_DIR"
elif [[ "$repo_root" == "$install_root" ]]; then
  data_dir="$install_root/.atenex/context"
else
  repo_key="$(printf '%s' "$repo_root" | sha256sum)"
  repo_key="${repo_key%% *}"
  data_dir="$install_root/.atenex/context/repositories/$repo_key"
fi

source_root="${ATENEX_CONTEXT_SOURCE_ROOT:-$repo_root}"
if [[ ! -d "$source_root/backend/atenex_nova/repo_context" ]]; then
  source_root="$install_root"
fi

if [[ ! -x "$python_executable" ]]; then
  printf 'Atenex Repo Context runtime not found: %s\n' "$python_executable" >&2
  exit 127
fi
if [[ ! -d "$repo_root" ]]; then
  printf 'Atenex Repo Context repository not found: %s\n' "$repo_root" >&2
  exit 2
fi

export LD_LIBRARY_PATH="$runtime_root/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$source_root/backend${PYTHONPATH:+:$PYTHONPATH}"
export ATENEX_TREE_SITTER_CACHE_DIR="$grammar_cache"

# Refresh the deterministic sidecar before exposing tools. CLI output is
# suppressed because stdout belongs exclusively to MCP after exec.
"$python_executable" -m atenex_nova.repo_context.presentation.cli \
  index \
  --repo "$repo_root" \
  --data-dir "$data_dir" \
  --json >/dev/null

exec "$python_executable" -m atenex_nova.repo_context.presentation.cli \
  serve \
  --repo "$repo_root" \
  --data-dir "$data_dir" \
  --transport stdio
