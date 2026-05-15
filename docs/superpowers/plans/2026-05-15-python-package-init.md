# cc-web MCP Python Package Init Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert cc-web MCP from root-level scripts into a standard Python package with a stable `cc-web-mcp` CLI and idempotent first-run initialization for Claude Code.

**Architecture:** Move runtime modules into `src/cc_web_mcp`, centralize config path resolution, expose one argparse-based CLI, and migrate install/doctor logic behind package entry points. Keep existing MCP tool behavior unchanged while updating tests and docs to the package import paths.

**Tech Stack:** Python 3.11, setuptools/pyproject, argparse, FastMCP, pytest, stdio Claude Code MCP integration.

---

## File Map

- Create `pyproject.toml`: package metadata, runtime dependencies, package data, console script.
- Create `src/cc_web_mcp/__init__.py`: package version.
- Create `src/cc_web_mcp/__main__.py`: `python -m cc_web_mcp` entry.
- Create `src/cc_web_mcp/cli.py`: argparse command routing.
- Create `src/cc_web_mcp/config.py`: default/user config path resolution and config file creation.
- Move `server.py` to `src/cc_web_mcp/server.py`: MCP tools and `run_stdio`.
- Move `web.py` to `src/cc_web_mcp/web.py`: web search/fetch implementation.
- Move `hooks/guard.py` to `src/cc_web_mcp/hooks/guard.py`: Claude hook guard.
- Create `src/cc_web_mcp/install.py`: MCP registration, CLAUDE.md block, settings hook merge, init orchestration.
- Move `scripts/doctor.py` to `src/cc_web_mcp/doctor.py`: package-aware diagnostics.
- Create `src/cc_web_mcp/data/default_config.json`: default config copied from root `config.json`.
- Modify tests under `tests/`: import package modules and cover CLI/init behavior.
- Modify docs and README: package install and init workflow.
- Delete old root-level runtime files after tests migrate: `server.py`, `web.py`, `config.json`, `hooks/`, `scripts/`.

## Task 1: Package Skeleton And Imports

**Files:**
- Create: `pyproject.toml`
- Create: `src/cc_web_mcp/__init__.py`
- Create: `src/cc_web_mcp/__main__.py`
- Create: `src/cc_web_mcp/cli.py`
- Create: `src/cc_web_mcp/hooks/__init__.py`
- Create: `src/cc_web_mcp/data/default_config.json`
- Move: `server.py` -> `src/cc_web_mcp/server.py`
- Move: `web.py` -> `src/cc_web_mcp/web.py`
- Move: `hooks/guard.py` -> `src/cc_web_mcp/hooks/guard.py`
- Modify: `tests/test_server_status.py`
- Modify: `tests/test_guard.py`
- Modify: `tests/test_web.py`

- [x] **Step 1: Write failing package import tests**

Add or update tests so imports use package paths:

```python
from cc_web_mcp import server
from cc_web_mcp import web
from cc_web_mcp.hooks import guard
```

Run:

```powershell
py -3.11 -m pytest .\tests\test_server_status.py .\tests\test_guard.py .\tests\test_web.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'cc_web_mcp'`.

- [x] **Step 2: Add package metadata and move runtime files**

Create `pyproject.toml` with:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "cc-web-mcp"
version = "0.1.1"
description = "Claude Code MCP web search and fetch tools for third-party models."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "mcp",
  "httpx",
  "beautifulsoup4",
  "markdownify",
]

[project.scripts]
cc-web-mcp = "cc_web_mcp.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
cc_web_mcp = ["data/*.json"]
```

Move runtime files into `src/cc_web_mcp`. Update `src/cc_web_mcp/server.py` import from:

```python
from web import check_health, fetch_page, research_brief as build_research_brief, search_web, to_json_text
```

to:

```python
from cc_web_mcp.web import check_health, fetch_page, research_brief as build_research_brief, search_web, to_json_text
```

Add `run_stdio()` in `server.py`:

```python
def run_stdio() -> None:
    mcp.run("stdio")
```

Update the `__main__` block to call `run_stdio()`.

- [x] **Step 3: Add minimal CLI serve route**

Create `src/cc_web_mcp/cli.py`:

```python
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cc-web-mcp")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start the cc-web MCP server over stdio.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "serve"
    if command == "serve":
        from cc_web_mcp.server import run_stdio

        run_stdio()
        return 0
    parser.error(f"unknown command: {command}")
    return 2
```

Create `src/cc_web_mcp/__main__.py`:

```python
from __future__ import annotations

from cc_web_mcp.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run package import tests**

Run:

```powershell
py -3.11 -m pytest .\tests\test_server_status.py .\tests\test_guard.py .\tests\test_web.py -q
```

Expected: PASS for these tests.

## Task 2: Central Config Module

**Files:**
- Create: `src/cc_web_mcp/config.py`
- Modify: `src/cc_web_mcp/web.py`
- Modify: `src/cc_web_mcp/hooks/guard.py`
- Create: `tests/test_config.py`

- [x] **Step 1: Write failing config tests**

Create tests for:

```python
from cc_web_mcp.config import default_user_config_path, ensure_user_config, resolve_config_path
```

Expected behavior:

- `resolve_config_path(explicit)` returns explicit path.
- `CC_WEB_MCP_CONFIG` overrides default.
- `ensure_user_config(path)` writes default JSON if missing.
- `ensure_user_config(path)` does not overwrite existing JSON.

Run:

```powershell
py -3.11 -m pytest .\tests\test_config.py -q
```

Expected: FAIL because `cc_web_mcp.config` does not exist.

- [x] **Step 2: Implement config module**

Implement:

```python
from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Any


ENV_CONFIG = "CC_WEB_MCP_CONFIG"


def default_user_config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "cc-web-mcp" / "config.json"


def default_config_text() -> str:
    return files("cc_web_mcp.data").joinpath("default_config.json").read_text(encoding="utf-8")


def default_config_dict() -> dict[str, Any]:
    data = json.loads(default_config_text())
    if not isinstance(data, dict):
        raise ValueError("default_config.json must contain a JSON object")
    return data


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env_value = os.environ.get(ENV_CONFIG)
    if env_value:
        return Path(env_value).expanduser()
    return default_user_config_path()


def ensure_user_config(path: str | Path | None = None) -> tuple[Path, bool]:
    config_path = resolve_config_path(path)
    if config_path.exists():
        return config_path, False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(default_config_text(), encoding="utf-8")
    return config_path, True
```

- [x] **Step 3: Wire web and guard defaults**

Update `web.py` default config path to use package config:

```python
from cc_web_mcp.config import resolve_config_path

DEFAULT_CONFIG_PATH = resolve_config_path()
```

Update `guard.py` default config path:

```python
from cc_web_mcp.config import resolve_config_path

DEFAULT_CONFIG = resolve_config_path()
```

- [x] **Step 4: Run config tests**

Run:

```powershell
py -3.11 -m pytest .\tests\test_config.py -q
```

Expected: PASS.

## Task 3: Install And Init Command

**Files:**
- Create: `src/cc_web_mcp/install.py`
- Modify: `src/cc_web_mcp/cli.py`
- Create: `tests/test_init.py`
- Replace: `tests/test_install_hook.py`
- Replace: `tests/test_install_instructions.py`

- [x] **Step 1: Write failing install/init tests**

Tests cover:

- `install_instructions(memory_path)` creates one marked block.
- Re-running `install_instructions` is idempotent.
- `install_hooks(settings_path, python_command, force=False)` creates SessionStart and PreToolUse entries.
- Re-running hook install is idempotent.
- Hook command contains `-m cc_web_mcp.hooks.guard`, not `hooks/guard.py`.
- `plan_init(..., dry_run=True)` reports actions without writing files.

Run:

```powershell
py -3.11 -m pytest .\tests\test_init.py -q
```

Expected: FAIL because `cc_web_mcp.install` does not exist.

- [x] **Step 2: Implement install module**

Move logic from old scripts into functions:

```python
START_MARKER = "<!-- cc-web-mcp:start -->"
END_MARKER = "<!-- cc-web-mcp:end -->"
DEFAULT_MATCHER = r"^(mcp__cc[-_]web__.*|WebFetch)$"

def default_memory_path() -> Path: ...
def default_settings_path() -> Path: ...
def install_instructions(memory_path: Path, force: bool = False) -> tuple[bool, Path | None]: ...
def install_hooks(settings_path: Path, python_command: str, force: bool = False) -> tuple[bool, Path | None]: ...
def build_guard_command(python_command: str) -> str:
    return f"{format_python_command(python_command)} -m cc_web_mcp.hooks.guard"
def run_init(args) -> int: ...
```

Keep existing backup behavior before writes. Preserve unrelated settings and hooks.

- [x] **Step 3: Add CLI subcommands**

Extend `cli.py` with:

- `init`
- `doctor`
- `config path`
- `config show`
- `config init`
- `hook-guard`

`hook-guard` calls `cc_web_mcp.hooks.guard.main`.

- [x] **Step 4: Run init tests**

Run:

```powershell
py -3.11 -m pytest .\tests\test_init.py -q
```

Expected: PASS.

## Task 4: Doctor Migration

**Files:**
- Create/Modify: `src/cc_web_mcp/doctor.py`
- Modify: `src/cc_web_mcp/cli.py`
- Modify: `tests/test_doctor.py`

- [x] **Step 1: Write failing doctor tests**

Update tests to import `cc_web_mcp.doctor` and call:

```powershell
py -3.11 -m cc_web_mcp doctor --json --skip-network --config <path> --claude-memory <path> --settings <path>
```

Assertions:

- missing setup recommends `cc-web-mcp init`.
- no recommendation mentions `scripts/install_hook.py`.
- configured local files pass.

Expected: FAIL until doctor is migrated.

- [x] **Step 2: Move doctor implementation**

Move `scripts/doctor.py` into package. Update imports:

```python
from cc_web_mcp.config import resolve_config_path
from cc_web_mcp.web import check_health
```

Default config path uses `resolve_config_path()`. Recommendations use `cc-web-mcp init`.

- [x] **Step 3: Wire CLI doctor**

`cc-web-mcp doctor` passes parsed args into `cc_web_mcp.doctor.main`.

- [x] **Step 4: Run doctor tests**

Run:

```powershell
py -3.11 -m pytest .\tests\test_doctor.py -q
```

Expected: PASS.

## Task 5: Remove Old Script Entrypoints And Update Docs

**Files:**
- Delete: `server.py`
- Delete: `web.py`
- Delete: `config.json`
- Delete: `hooks/guard.py`
- Delete: `scripts/install_hook.py`
- Delete: `scripts/install_instructions.py`
- Delete: `scripts/doctor.py`
- Modify: `README.md`
- Modify: `docs/installation.md`
- Modify: `docs/configuration.md`
- Modify: `docs/routing-and-permissions.md`

- [x] **Step 1: Update docs to new commands**

Replace quick start with:

```powershell
pipx install cc-web-mcp
cc-web-mcp init
cc-web-mcp doctor
```

Replace development workflow with:

```powershell
py -3.11 -m pip install -e .
cc-web-mcp init --dry-run
py -3.11 -m pytest .\tests -q
```

- [x] **Step 2: Delete old runtime files**

Remove the old root-level runtime/script files after tests import from package paths.

- [x] **Step 3: Run full tests**

Run:

```powershell
py -3.11 -m pytest .\tests -q
```

Expected: PASS.

## Task 6: Build Verification

**Files:**
- Modify as needed from prior tasks.

- [x] **Step 1: Install package editable**

Run:

```powershell
py -3.11 -m pip install -e .
```

Expected: exit 0.

- [x] **Step 2: Verify CLI help and dry-run**

Run:

```powershell
py -3.11 -m cc_web_mcp --help
py -3.11 -m cc_web_mcp init --dry-run --claude-memory .\tmp\CLAUDE.md --settings .\tmp\settings.json --config .\tmp\config.json
```

Expected: exit 0 and no real user Claude files modified.

- [x] **Step 3: Build wheel/sdist if build is installed**

Run:

```powershell
py -3.11 -m build
```

If `build` is missing, run:

```powershell
py -3.11 -m pip install build
py -3.11 -m build
```

Expected: exit 0 with artifacts in `dist/`.

- [x] **Step 4: Final git review**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only intended package/docs/test changes.
