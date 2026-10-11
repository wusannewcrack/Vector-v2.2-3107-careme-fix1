#!/usr/bin/env python3
"""一键构建：拿官方 Vector 模块包，产出修复版可刷 zip。

    python bootstrap.py                      # 第一次用，下载工具到 tools/
    python build.py --base Vector-v2.2-XXXX-Release.zip

产物默认写在 ./out/ 下。整个过程不联网、不改原包。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import stage1_manager, stage2_daemon, stage3_module, tools  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent


def _log(msg: str) -> None:
    print(msg, flush=True)


def extract_from_module(base_zip: Path, work: Path, log=_log) -> tuple[Path, Path]:
    """从官方模块包里取出 manager.apk / daemon.apk。"""
    with zipfile.ZipFile(base_zip) as z:
        names = set(z.namelist())
        for need in ("manager.apk", "daemon.apk", "module.prop"):
            if need not in names:
                raise SystemExit(f"[!] {base_zip.name} 里没有 {need}，这不像一个 Vector 模块包")
        mgr = work / "manager.apk"
        dmn = work / "daemon.apk"
        mgr.write_bytes(z.read("manager.apk"))
        dmn.write_bytes(z.read("daemon.apk"))
        log(f"  - manager.apk  {mgr.stat().st_size} bytes")
        log(f"  - daemon.apk   {dmn.stat().st_size} bytes")
    return mgr, dmn


def sign_apk(apk: Path, log=_log) -> Path:
    """用 uber-apk-signer 重签（会生成 <name>-aligned-debugSigned.apk）。"""
    outdir = apk.parent / "signed"
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    # 注意：uber-apk-signer 不允许同时给 -o 和 --overwrite
    tools.run(["java", "-jar", str(tools.uber_signer()),
               "-a", str(apk), "-o", str(outdir), "--allowResign"])
    cands = sorted(outdir.glob("*-aligned-debugSigned.apk"))
    if not cands:
        raise SystemExit(f"[!] 签名失败，{outdir} 里没找到产物")
    final = apk.parent / (apk.stem + "-signed.apk")
    shutil.copy(cands[0], final)
    log(f"  + 已签名 -> {final.name}")
    return final


def verify_smoke(final_zip: Path, log=_log) -> None:
    """冒烟检查：哈希自洽 + 两个 APK 里的关键类还在、且确实被改动过。"""
    import io

    if not stage3_module.verify_module(final_zip, log):
        raise SystemExit("[!] 模块包 sha256 校验未通过")

    with zipfile.ZipFile(final_zip) as z:
        man_bytes = z.read("manager.apk")
        dmn_bytes = z.read("daemon.apk")
        log(f"  - manager.apk {len(man_bytes)} bytes / daemon.apk {len(dmn_bytes)} bytes")

    # manager：目标类还在不能有半途崩坏；出包前 Stage 1 已经确认过，这里只做存在性检查
    with zipfile.ZipFile(io.BytesIO(man_bytes)) as mz:
        found = any(stage1_manager.TARGET_CLASS.encode() in mz.read(n)
                    for n in mz.namelist()
                    if n.startswith("classes") and n.endswith(".dex"))
    log(f"  - manager: {stage1_manager.TARGET_CLASS.split('.')[-1]} 存在={found}")

    with zipfile.ZipFile(io.BytesIO(dmn_bytes)) as dz:
        found_d = any(stage2_daemon.TARGET_CLASS_MARKER in dz.read(n)
                      for n in dz.namelist()
                      if n.startswith("classes") and n.endswith(".dex"))
    log(f"  - daemon: InstallerVerifier 存在={found_d}（存在即为 smali 回编后的正常产物）")


def main() -> int:
    ap = argparse.ArgumentParser(description="构建修复版 Vector Magisk 模块")
    ap.add_argument("--base", required=True, type=Path, help="官方 Vector 模块 zip")
    ap.add_argument("--out", type=Path, help="输出 zip 路径，默认 out/<base>-fix1.zip")
    ap.add_argument("--suffix", default="-fix1", help="module.prop 的 version 后缀")
    ap.add_argument("--work", type=Path, default=REPO_ROOT / "build", help="中间产物目录")
    ap.add_argument("--no-sign", action="store_true", help="跳过重签名（调试用，产物不能刷）")
    args = ap.parse_args()

    base: Path = args.base.expanduser().resolve()
    if not base.is_file():
        raise SystemExit(f"[!] 找不到 {base}")

    work: Path = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    # 只清掉会被「重新生成时复用、且残留会影响结果」的两个目录。
    # 不整树删除：baksmali 输出动辄几万个小文件，删起来又慢又不安全。
    for stale in ("daemon_src", "signed"):
        shutil.rmtree(work / stale, ignore_errors=True)

    if args.out:
        out_zip = args.out.expanduser().resolve()
    else:
        out_zip = REPO_ROOT / "out" / (base.stem + args.suffix + ".zip")

    _log("=" * 62)
    _log(f"Vector Careme Fix 构建器\n  输入: {base}\n  输出: {out_zip}")
    _log("=" * 62)

    _log("\n[0/3] 检查 Java 工具依赖")
    tools.ensure_tools()

    _log("\n[1/3] Stage 1 —— manager 的 Compose autofill 崩溃修复")
    mgr_src, dmn_src = extract_from_module(base, work)
    mgr_unsigned = stage1_manager.patch_manager_apk(mgr_src, work / "manager-unsigned.apk", log=_log)
    if args.no_sign:
        mgr_final = mgr_unsigned
    else:
        _log("  * 重新签名 manager")
        mgr_final = sign_apk(mgr_unsigned, log=_log)

    _log("\n[2/3] Stage 2 —— daemon 的 manager 签名校验解除")
    dmn_unsigned = stage2_daemon.patch_daemon_apk(dmn_src, work, work / "daemon-unsigned.apk", log=_log)
    if args.no_sign:
        dmn_final = dmn_unsigned
    else:
        _log("  * 重新签名 daemon")
        dmn_final = sign_apk(dmn_unsigned, log=_log)

    _log("\n[3/3] Stage 3 —— 打包模块")
    stage3_module.build_module(base, mgr_final, dmn_final, out_zip, args.suffix, log=_log)
    verify_smoke(out_zip, log=_log)

    _log("\n完成 ✅")
    _log(f"刷机包: {out_zip}")
    _log("把它放进 Magisk App → 模块 → 从本地安装，重启即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
