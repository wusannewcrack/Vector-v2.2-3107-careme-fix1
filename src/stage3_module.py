"""Stage 3 —— 把补丁好的两个 APK 塞回官方模块包，输出可刷的 zip。

三个配套改动缺一不可：

1. service.sh 开头补一段 sepolicy 兜底
   部分 Magisk 分支（尤其手表/国产定制 ROM 上的移植版）不会自动执行模块的
   sepolicy.rule，导致 daemon 检查 dex2oat 域的 SELinux 权限时判定失败，
   manager 顶栏显示“异常 / Degraded”。开机时手动 apply 一次即可。

2. customize.sh 在刷入时就装修补版 manager
   补丁后的 APK 换了新的签名 key，必须 pm uninstall 旧的再 install，
   否则 pm 会以“签名不一致”直接拒绝覆盖安装。

3. module.prop 去掉 updateJson
   否则 Magisk 会把官方新版推给用户、覆盖掉这次修复。

以上三处都做成「找不到锚点就退化处理」，避免上游改一行就把构建炸掉。
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

MANAGER_PKG = "org.matrix.vector.manager"

SEPOLSICY_BLOCK = """
# --- vector-careme-fix: make sure the sepolicy rules are actually loaded ---
# Some Magisk builds on Wear / custom ROMs never run sepolicy.rule automatically,
# which leaves the daemon unable to verify permissions and the manager showing
# "Degraded". Applying it here is cheap and idempotent.
if [ -f "$MODDIR/sepolicy.rule" ] && command -v magiskpolicy >/dev/null 2>&1; then
    magiskpolicy --live --apply "$MODDIR/sepolicy.rule" >/dev/null 2>&1
fi
"""

CUSTOMIZE_ANCHOR = 'if [ -f "$MODPATH/prompt.apk" ]; then'

CUSTOMIZE_MANAGER_BLOCK = f'''

# --- vector-careme-fix: install the patched manager APK ---
# It carries a different signing key than the stock manager, so the old install
# has to go away first or pm refuses to update it.
if [ -f "$MODPATH/manager.apk" ]; then
    pm uninstall "{MANAGER_PKG}" >/dev/null 2>&1
    if pm install -r -g "$MODPATH/manager.apk" >/dev/null 2>&1; then
        ui_print "- Installed patched manager (autofill crash fixed)"
    else
        ui_print "- Patched manager will be installed on next boot"
    fi
fi'''

SERVICE_MANAGER_BLOCK = f'''
# --- vector-careme-fix: install the patched manager APK ---
# Fallback for recovery flashes where customize.sh could not reach `pm`. Runs once
# per module build thanks to the stamp file, so it is not repeated every boot.
(
    MANAGER_PKG="{MANAGER_PKG}"
    MANAGER_APK="$MODDIR/manager.apk"
    STAMP="$MODDIR/.manager_stamp"
    [ -f "$MANAGER_APK" ] || exit 0
    i=0
    while [ "$(getprop sys.boot_completed)" != "1" ] && [ "$i" -lt 120 ]; do
        sleep 2
        i=$(( i + 1 ))
    done
    WANT=$(sha256sum "$MANAGER_APK" 2>/dev/null | cut -d' ' -f1)
    if [ -n "$WANT" ] && [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
        pm uninstall "$MANAGER_PKG" >/dev/null 2>&1
        if pm install -r -g "$MANAGER_APK" >/dev/null 2>&1; then
            echo "$WANT" >"$STAMP"
        fi
    fi
) &
'''


def _sha(data: bytes) -> bytes:
    return hashlib.sha256(data).hexdigest().encode()


def _edit_service(text: str, log=print) -> str:
    anchor = 'cd "$MODDIR" || exit 1'
    if SEPOLSICY_BLOCK.strip() in text:
        log("  = service.sh 已含 sepolicy 兜底，跳过")
    elif anchor in text:
        text = text.replace(anchor, anchor + "\n" + SEPOLSICY_BLOCK, 1)
        log("  + service.sh 插入 sepolicy 兜底")
    else:
        text = SEPOLSICY_BLOCK + "\n" + text
        log("  + service.sh 开头插入 sepolicy 兜底（未找到 cd 锚点）")

    if "vector-careme-fix: install the patched manager APK" in text:
        log("  = service.sh 已含 manager 安装块，跳过")
    else:
        text = text.rstrip() + "\n" + SERVICE_MANAGER_BLOCK
        log("  + service.sh 追加 manager 安装块")
    return text


def _edit_customize(text: str, log=print) -> str:
    if "vector-careme-fix: install the patched manager APK" in text:
        log("  = customize.sh 已含 manager 安装块，跳过")
        return text
    if CUSTOMIZE_ANCHOR in text:
        # 找到 prompt 安装块的结束位置（配对的 fi），在它后面追加
        idx = text.index(CUSTOMIZE_ANCHOR)
        end = text.find("\nfi", idx)
        if end == -1:
            text = text.rstrip() + "\n" + CUSTOMIZE_MANAGER_BLOCK
        else:
            end += len("\nfi")
            text = text[:end] + "\n" + CUSTOMIZE_MANAGER_BLOCK + text[end:]
        log("  + customize.sh 在 prompt 块之后插入 manager 安装块")
    else:
        text = text.rstrip() + "\n" + CUSTOMIZE_MANAGER_BLOCK
        log("  + customize.sh 末尾追加 manager 安装块（未找到锚点）")
    return text


def _edit_prop(text: str, suffix: str, log=print) -> str:
    lines = []
    for line in text.split("\n"):
        if line.startswith("version="):
            ver = line.split("=", 1)[1]
            if suffix not in ver:
                # v2.2-3107-careme (3107-8624af73) -> v2.2-3107-careme-fix1 (3107-8624af73)
                head, sp, tail = ver.partition(" ")
                line = f"version={head}{suffix}{sp}{tail}"
                log(f"  + module.prop version -> {head}{suffix}{sp}{tail}")
        elif line.startswith("description="):
            desc = line.split("=", 1)[1]
            if "vector-careme-fix" not in desc:
                line = ("description=" + desc +
                        " [vector-careme-fix: autofill crash fix for no-autofill ROMs, "
                        "daemon accepts re-signed manager, sepolicy boot fallback]")
                log("  + module.prop description 已更新")
        elif line.startswith("updateJson"):
            log("  - module.prop 移除 updateJson（防止被官方更新覆盖）")
            continue
        lines.append(line)
    return "\n".join(lines)


def build_module(base_zip: Path, manager_apk: Path, daemon_apk: Path,
                 out_zip: Path, suffix: str = "-fix1", log=print) -> Path:
    """基于官方模块包生成修复版。所有 .sha256 同步重算。"""
    replacements: dict[str, bytes] = {}

    man = manager_apk.read_bytes()
    dmn = daemon_apk.read_bytes()
    replacements["manager.apk"] = man
    replacements["manager.apk.sha256"] = _sha(man)
    replacements["daemon.apk"] = dmn
    replacements["daemon.apk.sha256"] = _sha(dmn)

    with zipfile.ZipFile(base_zip) as src:
        names = [i.filename for i in src.infolist()]
        for name, payload, label in (
            ("service.sh", None, "service.sh"),
            ("customize.sh", None, "customize.sh"),
            ("module.prop", None, "module.prop"),
        ):
            if name not in names:
                log(f"  ! {name} 不在原包里，跳过")
                continue
            raw = src.read(name).decode("utf-8")
            if label == "service.sh":
                raw = _edit_service(raw, log)
            elif label == "customize.sh":
                raw = _edit_customize(raw, log)
            else:
                raw = _edit_prop(raw, suffix, log)
            data = raw.encode()
            replacements[name] = data
            replacements[f"{name}.sha256"] = _sha(data)

        log("  * 重写模块包 …")
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as out:
            for info in src.infolist():
                name = info.filename
                payload = replacements.get(name, src.read(name))
                new_info = zipfile.ZipInfo(name, date_time=info.date_time)
                new_info.compress_type = info.compress_type
                new_info.external_attr = info.external_attr
                out.writestr(new_info, payload)
                if name in replacements and not name.endswith(".sha256"):
                    log(f"  -> 已替换 {name}")

    log(f"  -> {out_zip} ({out_zip.stat().st_size} bytes)")
    return out_zip


def verify_module(out_zip: Path, log=print) -> bool:
    """逐个校验模块包内的 sha256。"""
    ok = True
    with zipfile.ZipFile(out_zip) as z:
        names = set(z.namelist())
        for hname in [n for n in names if n.endswith(".sha256")]:
            target = hname[:-len(".sha256")]
            if target not in names:
                continue
            want = z.read(hname).decode().strip().split()[0]
            got = hashlib.sha256(z.read(target)).hexdigest()
            if want != got:
                ok = False
                log(f"  X {target}: 期望 {want[:12]}… 实际 {got[:12]}…")
    if ok:
        log("  OK 所有 sha256 校验通过")
    return ok
