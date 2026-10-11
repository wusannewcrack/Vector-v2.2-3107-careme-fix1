"""Stage 2 —— 让 daemon 接受「重签名过的 manager」。

现象
----
修完 Stage 1 之后 manager 不崩了，但界面停在「未激活」。logcat 里是：

    Skipped ... no binder

根因：daemon 在注入 manager 进程之前，会先验证**已安装 manager APK** 的签名，
比对的是编译时硬编码进 SignInfo.CERTIFICATE 的官方证书：

    ConfigCache.updateManager(...)
      └─ ManagerService
           └─ InstallerVerifier.verifyInstallerSignature(sourceDir)
                   ← 比对 SignInfo.CERTIFICATE，不一致就抛异常

Stage 1 的补丁改了 manager 的 dex，APK 必须由我们重新签名（原签名对应不上 content），
签名自然就不等于官方证书了。于是 daemon 跳过注入，manager 永远拿不到 binder。

修法
----
把 verifyInstallerSignature 的方法体换成 `return-void`，即无条件放行。
它只有这两处调用方，都是「注入前自检」，放行后 daemon 会照常把 framework.dex
注入 manager；而且 manager 是本机 pm 装的普通应用，已经过了 Android 自己的
安装校验（降级防线本来也不该由 daemon 承担）。

为什么要用 smali 工具链 instead of 字节 patch
--------------------------------------------
试过直接改 dex 字节：方法体变短会让 code_item / debug_info 段错位，
dex2oat 报 `Non-zero padding before section`，ART 直接拒载。
用 baksmali 反编译 → 改 smali → smali 回编，dex 布局是重新排布的、干净的。
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .tools import ToolError, java

TARGET_CLASS_MARKER = b"Lorg/matrix/vector/daemon/utils/InstallerVerifier;"
TARGET_SMALI_REL = "org/matrix/vector/daemon/utils/InstallerVerifier.smali"
TARGET_METHOD_RE = re.compile(
    r"\.method public final verifyInstallerSignature\(Ljava/lang/String;\)V"
    r".*?\.end method",
    re.DOTALL,
)

PATCH_FILE = Path(__file__).resolve().parent.parent / "patches" / "InstallerVerifier.verifyInstallerSignature.smali"


def _patched_method() -> str:
    return PATCH_FILE.read_text(encoding="utf-8").strip()


def find_dex_with_marker(apk: Path, marker: bytes) -> str | None:
    """找出 apk 里哪一个 classes*.dex 含目标类。"""
    with zipfile.ZipFile(apk) as z:
        names = [i.filename for i in z.infolist()
                 if i.filename.startswith("classes") and i.filename.endswith(".dex")]
        for name in sorted(names, key=_dex_sort_key):
            if marker in z.read(name):
                return name
    return None


def _dex_sort_key(n: str):
    # classes.dex < classes2.dex < classes12.dex ...
    m = re.match(r"classes(\d*)\.dex", n)
    return int(m.group(1)) if m and m.group(1) else 0


def _replace_method(smali_file: Path) -> bool:
    text = smali_file.read_text(encoding="utf-8")
    new, n = TARGET_METHOD_RE.subn(_patched_method(), text)
    if n == 0:
        return False
    smali_file.write_text(new, encoding="utf-8")
    return True


def patch_daemon_apk(src_apk: Path, workdir: Path, out_apk: Path, log=print) -> Path:
    """返回重编后、还没签名的 daemon.apk。"""
    dex_name = find_dex_with_marker(src_apk, TARGET_CLASS_MARKER)
    if not dex_name:
        raise ToolError(
            f"{src_apk.name} 里找不到 InstallerVerifier，"
            "可能这个版本的类名变了，检查后再构建。"
        )
    log(f"  * 目标 dex: {dex_name}")

    dex_path = workdir / dex_name
    src_dir = workdir / "daemon_src"
    out_dex = workdir / dex_name.replace(".dex", ".fixed.dex")

    with zipfile.ZipFile(src_apk) as z:
        dex_path.write_bytes(z.read(dex_name))

    log("  * baksmali 反编译 …（可能要几十秒）")
    java("org.jf.baksmali.Main", ["d", str(dex_path), "-o", str(src_dir), "--api", "30"])

    target = src_dir / TARGET_SMALI_REL
    if not target.is_file():
        raise ToolError(f"反编译结果里没有 {TARGET_SMALI_REL}（类名是否变了？）")
    if not _replace_method(target):
        raise ToolError("verifyInstallerSignature 方法体没匹配上，smali 结构可能变了")
    log("  + verifyInstallerSignature 已改为 return-void")

    log("  * smali 回编 …")
    java("org.jf.smali.Main", ["a", str(src_dir), "-o", str(out_dex), "--api", "30"])

    log("  * 重建 daemon.apk")
    drop = {"MANIFEST.MF", "CERT.SF", "CERT.RSA", "ANDROID.SF", "ANDROID.RSA"}
    with zipfile.ZipFile(src_apk) as zin, zipfile.ZipFile(out_apk, "w") as zout:
        for info in zin.infolist():
            name = info.filename
            if name.startswith("META-INF/") and name.rsplit("/", 1)[-1].upper() in drop:
                continue
            payload = out_dex.read_bytes() if name == dex_name else zin.read(name)
            new_info = zipfile.ZipInfo(name, date_time=info.date_time)
            new_info.compress_type = info.compress_type
            new_info.external_attr = info.external_attr
            zout.writestr(new_info, payload)

    log(f"  -> {out_apk}")
    return out_apk
