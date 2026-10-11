"""Stage 1 —— 修掉 manager 在「没有 Autofill 服务的 ROM」上的点击崩溃。

现象
----
Vector manager 用的是 Jetpack Compose。Compose 的 AndroidAutofill 委托给
androidx.compose.ui.autofill.PlatformAutofillManagerImpl，它每个方法都会先去拿
framework 的 AutofillManager：

    inline fun <reified T> getPlatformAndroidManager(): T =
        context.getSystemService(T::class.java)
            ?: error("Could not locate ${T::class.java.simpleName} from context")

偏偏一大批国产 ROM / Wear OS 手表 ROM（小米 Z10、CaremeOS、多数 Wear 4100/5100 平台
固件）在裁剪时把 autofill 系统服务连根拔了，`dumpsys autofill` 直接报
"Can't find service: autofill"。于是任何可输入组件拿到焦点、用户一点屏幕：

    java.lang.IllegalStateException: Could not locate AutofillManager from context

崩溃发生在 UI 线程且不走 Compose 的兜底，整个 manager 直接 ANR/闪退。

修法
----
把上面那些方法体原地抹成 no-op（return-void）。这些方法的返回值都是 void，
语义上只是「通知 autofill 一下」，跳过它对 none-autofill ROM 毫无损失——
本来就没有 autofill 可以通知。

注意不能「缩短」方法体：code_item 尾部要留出 padding 对齐，
指令数变少会让 dex2oat 报 "Non-zero padding before section"。
所以做法是保留原来的 insns_size，把前 n-1 条指令填 0x0000 (nop)，
最后一条写 0x000e (return-void)。
"""

from __future__ import annotations

import struct
from pathlib import Path

from .dexutil import Dex, DexError, fix_checksum

TARGET_CLASS = "Landroidx/compose/ui/autofill/PlatformAutofillManagerImpl;"

# 这几个是 Compose 里所有会触发 getPlatformAndroidManager() 的入口
TARGET_METHODS = [
    "cancel",
    "commit",
    "notifyValueChanged",
    "notifyViewEntered",
    "notifyViewExited",
    "notifyViewVisibilityChanged",
    "requestAutofill",
]

RETURN_VOID = 0x000E
NOP = 0x0000


def _patch_dex(data: bytes, cls: str, methods: list[str]) -> bytes:
    d = bytearray(data)
    dex = Dex(bytes(d))
    _ci, class_def_off = dex.find_class(cls)
    if class_def_off is None:
        raise DexError(f"DEX 里找不到 {cls}")

    rows = {name: (ret, code) for name, ret, _params, code, _acc in dex.signatures(class_def_off)}
    patched = 0
    for name in methods:
        if name not in rows:
            print(f"  - 跳过 {name}（该 dex 里没有这个方法，版本可能已变化）")
            continue
        ret, code_off = rows[name]
        if not code_off:
            continue
        if ret != "V":
            raise DexError(f"{name} 的返回值是 {ret}，不是 void，不能改成 return-void")

        _regs, _ins, _outs, _tries = struct.unpack_from("<HHHH", d, code_off)
        insns_size, = struct.unpack_from("<I", d, code_off + 12)
        ins_off = code_off + 16
        # 前 n-1 条填 nop，最后一条写 return-void，长度保持不变
        for i in range(insns_size - 1):
            struct.pack_into("<H", d, ins_off + i * 2, NOP)
        struct.pack_into("<H", d, ins_off + (insns_size - 1) * 2, RETURN_VOID)
        patched += 1
        print(f"  + {name}: {insns_size} 条指令已置空 @0x{code_off:x}")

    if patched == 0:
        raise DexError("一个方法都没打到，中止（可能是 dex 结构变了）")

    return bytes(fix_checksum(d))


def patch_manager_apk(src_apk: Path, dst_apk: Path, log=print) -> Path:
    """替换 manager.apk 里含 PlatformAutofillManagerImpl 的 dex，丢弃旧签名条目。"""
    import zipfile

    drop = {"MANIFEST.MF", "CERT.SF", "CERT.RSA", "ANDROID.SF", "ANDROID.RSA"}

    with zipfile.ZipFile(src_apk) as zin, zipfile.ZipFile(dst_apk, "w") as zout:
        hit = False
        for info in zin.infolist():
            name = info.filename
            # 丢掉原签名，后面由 uber-apk-signer 重新签
            if name.startswith("META-INF/") and name.rsplit("/", 1)[-1].upper() in drop:
                log(f"  - 移除签名条目 {name}")
                continue

            payload = zin.read(name)
            if name.startswith("classes") and name.endswith(".dex"):
                try:
                    dex = Dex(payload)
                    _ci, cdo = dex.find_class(TARGET_CLASS)
                except DexError:
                    cdo = None
                if cdo:
                    log(f"  * 命中 {name}，开始打补丁")
                    payload = _patch_dex(payload, TARGET_CLASS, TARGET_METHODS)
                    hit = True

            new_info = zipfile.ZipInfo(name, date_time=info.date_time)
            # 关键：保持原来的 compress_type。lib/*.so 是 STORED，
            # 改成 DEFLATED 会让 native lib 解不出来。
            new_info.compress_type = info.compress_type
            new_info.external_attr = info.external_attr
            zout.writestr(new_info, payload)

    if not hit:
        log("  ! 没有找到 PlatformAutofillManagerImpl：这个 manager 可能不需要本补丁")
    log(f"  -> {dst_apk}")
    return dst_apk
