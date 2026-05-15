from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _dispatch_init(argv: list[str]) -> int:
    from cc_web_mcp import install

    return install.main(argv)


def _dispatch_doctor(argv: list[str]) -> int:
    from cc_web_mcp import doctor

    return doctor.main(argv)


def _dispatch_serve(argv: list[str]) -> int:
    from cc_web_mcp import server

    if argv:
        raise SystemExit("serve does not accept subcommand arguments")
    server.run_stdio()
    return 0


def _dispatch_hook_guard(argv: list[str]) -> int:
    if argv:
        raise SystemExit("hook-guard does not accept subcommand arguments")
    from cc_web_mcp.hooks import guard

    return guard.main()


def _dispatch_config(argv: list[str]) -> int:
    from cc_web_mcp.config import default_config_dict, ensure_user_config, resolve_config_path

    parser = argparse.ArgumentParser(prog="cc-web-mcp config")
    subparsers = parser.add_subparsers(dest="config_command")

    path_parser = subparsers.add_parser("path", help="Print the active cc-web config path.")
    path_parser.add_argument("--config", default=None)

    show_parser = subparsers.add_parser("show", help="Print the active cc-web config JSON.")
    show_parser.add_argument("--config", default=None)

    init_parser = subparsers.add_parser("init", help="Create the user config if it is missing.")
    init_parser.add_argument("--config", default=None)

    args = parser.parse_args(argv)
    command = args.config_command or "path"
    explicit = Path(os.path.expanduser(args.config)) if getattr(args, "config", None) else None
    config_path = resolve_config_path(explicit)

    if command == "path":
        print(config_path)
        return 0
    if command == "init":
        path, created = ensure_user_config(config_path)
        print(f"{'Created' if created else 'Exists'}: {path}")
        return 0
    if command == "show":
        if config_path.exists():
            print(config_path.read_text(encoding="utf-8-sig").rstrip())
        else:
            print(json.dumps(default_config_dict(), ensure_ascii=False, indent=2))
        return 0
    parser.error(f"unknown config command: {command}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cc-web-mcp")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start the cc-web MCP server over stdio.")
    subparsers.add_parser("init", help="Initialize Claude Code integration.")
    subparsers.add_parser("doctor", help="Check local cc-web setup.")
    subparsers.add_parser("config", help="Show or initialize cc-web configuration.")
    subparsers.add_parser("hook-guard", help="Run the Claude Code hook guard.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not args:
        return _dispatch_serve([])

    command = args[0]
    rest = args[1:]
    if command in {"-h", "--help"}:
        parser.print_help()
        return 0
    if command == "serve":
        return _dispatch_serve(rest)
    if command == "init":
        return _dispatch_init(rest)
    if command == "doctor":
        return _dispatch_doctor(rest)
    if command == "config":
        return _dispatch_config(rest)
    if command == "hook-guard":
        return _dispatch_hook_guard(rest)
    parser.error(f"unknown command: {command}")
    return 2
