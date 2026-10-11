"""运行 Java 工具 / 下载 jar 依赖的辅助模块。"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"

MAVEN = "https://repo1.maven.org/maven2"
GITHUB_SMALI = "https://github.com/JesusFreke/smali/releases/download/v2.5.2"
GITHUB_UBER = "https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0"

# (文件名, URL) —— 全部是可校验的公开产物，不放二进制到 git 仓库里
DEPENDENCIES = [
    ("baksmali-2.5.2.jar", f"{MAVEN}/org/smali/baksmali/2.5.2/baksmali-2.5.2.jar"),
    ("smali-2.5.2.jar", f"{MAVEN}/org/smali/smali/2.5.2/smali-2.5.2.jar"),
    ("dexlib2-2.5.2.jar", f"{MAVEN}/org/smali/dexlib2/2.5.2/dexlib2-2.5.2.jar"),
    ("util-2.5.2.jar", f"{MAVEN}/org/smali/util/2.5.2/util-2.5.2.jar"),
    ("jcommander-1.82.jar", f"{MAVEN}/com/beust/jcommander/1.82/jcommander-1.82.jar"),
    ("guava-31.1-jre.jar", f"{MAVEN}/com/google/guava/guava/31.1-jre/guava-31.1-jre.jar"),
    ("antlr-runtime-3.5.3.jar", f"{MAVEN}/org/antlr/antlr-runtime/3.5.3/antlr-runtime-3.5.3.jar"),
    ("uber-apk-signer-1.3.0.jar", f"{GITHUB_UBER}/uber-apk-signer-1.3.0.jar"),
]

# 上面 GitHub 那份 uber-apk-signer 抓不到时的备用源
DEPENDENCIES.append(
    ("uber-apk-signer-1.3.0.jar", f"{MAVEN}/io/github/patrickfav/uber-apk-signer/1.3.0/uber-apk-signer-1.3.0.jar")
)

SMALI_CLASSPATH = [
    "baksmali-2.5.2.jar",
    "smali-2.5.2.jar",
    "dexlib2-2.5.2.jar",
    "util-2.5.2.jar",
    "jcommander-1.82.jar",
    "guava-31.1-jre.jar",
    "antlr-runtime-3.5.3.jar",
]


class ToolError(RuntimeError):
    pass


def _download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "vector-careme-fix"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if len(data) < 1024 or data[:2] != b"PK":
            return False
        dest.write_bytes(data)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {url} -> {exc}")
        return False


def ensure_tools() -> Path:
    """确保 tools/ 下的 jar 都在；缺哪个下哪个。"""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    missing = [pair for pair in DEPENDENCIES if not (TOOLS_DIR / pair[0]).is_file()]
    # uber-apk-signer 有两个候选 URL，只要有一个下载成功即可
    have_uber = any((TOOLS_DIR / n).is_file() for n, _ in DEPENDENCIES if n.startswith("uber"))
    for name, url in missing:
        if name.startswith("uber") and have_uber:
            continue
        print(f"[tools] downloading {name}")
        if _download(url, TOOLS_DIR / name):
            print(f"[tools] ok {name} ({(TOOLS_DIR / name).stat().st_size} bytes)")
            if name.startswith("uber"):
                have_uber = True
        else:
            print(f"[tools] FAILED {name}")
    absent = []
    for name in {n for n, _ in DEPENDENCIES}:
        if not (TOOLS_DIR / name).is_file():
            absent.append(name)
    if absent:
        raise ToolError(
            "缺少依赖: " + ", ".join(absent) + "\n请手动下载后放进 tools/，或检查网络代理。"
        )
    return TOOLS_DIR


def classpath() -> str:
    return os.pathsep.join(str(TOOLS_DIR / n) for n in SMALI_CLASSPATH)


def uber_signer() -> Path:
    for cand in ("uber-apk-signer-1.3.0.jar", "uber-apk-signer.jar"):
        p = TOOLS_DIR / cand
        if p.is_file():
            return p
    raise ToolError("uber-apk-signer 未找到")


def run(args: list[str], cwd: Path | None = None, check: bool = True):
    """跑一条命令并返回 CompletedProcess。"""
    print("  $ " + " ".join(str(a) for a in args))
    proc = subprocess.run([str(a) for a in args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.returncode != 0:
        sys.stderr.write((proc.stderr or "") + "\n")
        if check:
            raise ToolError(f"命令失败 (exit {proc.returncode}): {args[0]}")
    return proc


def java(main_class: str, args: list[str], cwd: Path | None = None):
    return run(["java", "-cp", classpath(), main_class, *args], cwd=cwd)
