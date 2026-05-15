from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cc_web_mcp.install import default_memory_path, install_instructions


def main() -> int:
    parser = argparse.ArgumentParser(description="Compatibility wrapper for cc-web instruction installation.")
    parser.add_argument("--memory", default=str(default_memory_path()))
    args = parser.parse_args()

    print("Deprecated: use `cc-web-mcp init` for first-time setup.")
    changed, backup_path = install_instructions(Path(os.path.expanduser(args.memory)))
    if changed:
        print(f"Updated: {args.memory}")
        if backup_path:
            print(f"Backup: {backup_path}")
    else:
        print(f"No change: {args.memory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
