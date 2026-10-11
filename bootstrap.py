#!/usr/bin/env python3
"""下载构建所需的 Java 工具到 ./tools/。

这些 jar 不进 git 仓库（每个几 MB ~ 20MB），用这份脚本按需拉取：

    python bootstrap.py

下载源全部是公开可校验的：
  - baksmali / smali / dexlib2 / util   https://repo1.maven.org/maven2/org/smali/
  - jcommander / guava / antlr-runtime  https://repo1.maven.org/maven2/
  - uber-apk-signer                     https://github.com/patrickfav/uber-apk-signer
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.tools import ensure_tools, TOOLS_DIR  # noqa: E402


def main() -> int:
    print(f"目标目录: {TOOLS_DIR}")
    ensure_tools()
    print("\n依赖就绪 ✅")
    for p in sorted(TOOLS_DIR.glob("*.jar")):
        print(f"  {p.name}  {p.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
