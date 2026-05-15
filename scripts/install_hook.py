from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cc_web_mcp.install import install_hooks


def main() -> int:
    parser = argparse.ArgumentParser(description="Compatibility wrapper for cc-web hook installation.")
    parser.add_argument("--settings", default=str(Path.home() / ".claude" / "settings.json"))
    parser.add_argument("--python-command", default=None)
    parser.add_argument("--guard", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    print("Deprecated: use `cc-web-mcp init` for first-time setup.")
    changed, backup_path = install_hooks(
        Path(os.path.expanduser(args.settings)),
        args.python_command,
        force=args.force,
    )
    if changed:
        print(f"Updated: {args.settings}")
        if backup_path:
            print(f"Backup: {backup_path}")
    else:
        print(f"No change: {args.settings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
