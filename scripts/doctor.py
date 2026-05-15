from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cc_web_mcp.doctor import main


if __name__ == "__main__":
    print("Deprecated: use `cc-web-mcp doctor`.")
    raise SystemExit(main())
