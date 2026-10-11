# vector-careme-fix

> 让 **Vector**（JingMatrix 的 Zygisk/Xposed 兼容框架）在没有 Autofill 服务的 ROM 上正常激活、正常运行 kit 的一套补丁构建器。

![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Android%208.1%20~%2017-orange.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![Java](https://img.shields.io/badge/java-8+-red.svg)

---

## 这个项目解决什么

在**小米 Z10 手表 / CaremeOS / 各类 Wear 4100·5100 平台固件**这类被深度裁剪的 ROM 上装官方 Vector，会遇到三连击：

| # | 现象 | 真实原因 |
| --- | --- | --- |
| 1 | 打开 Vector manager，手指一碰屏幕就卡死 → ANR → 崩溃 | ROM 没有 `autofill` 系统服务，Compose 的 `PlatformAutofillManagerImpl` 取不到 `AutofillManager` 直接抛 `IllegalStateException` |
| 2 | 崩溃修好后界面卡在「未激活」 | daemon 校验**已安装 manager APK** 的签名，比对的是编译时硬编码的官方证书；补丁后的 APK 必须重签，于是被判定为不可信，跳过注入 |
| 3 | 有时顶栏挂个大红警告「异常 / Degraded」 | 部分 Magisk 移植版不会自动加载模块的 `sepolicy.rule`，daemon 检查 dex2oat 域权限失败 |

三者叠加的结果就是「能用但不好使，或者干脆不能用」。本仓库把这三处一次性修好，产出一个**直接可刷的 Magisk 模块 zip**。

技术细节见 [`docs/ANALYSIS.md`](docs/ANALYSIS.md)。

---

## 两种用法

### A. 只想刷进去用（不需要构建）

去 Releases 页面下载对应上游版本的 `Vector-v2.2-XXXX-…-fix1.zip`，然后：

1. 如果已经装了 Vector 模块，先在 Magisk 里**卸载并重启一次**；
2. Magisk App → **模块** → **从本地安装** → 选这个 zip；
3. 安装日志里出现 `Installed patched manager (autofill crash fixed)` 即为成功；
4. 重启。开机后 Vector manager 应显示 **已激活**。

> 头几秒如果还显示 Degraded 属正常：service.sh 会在开机阶段补一次 `magiskpolicy`，稍等界面自动刷新。

如果是 **recovery 里刷**（此时 `pm` 不可用），<｜hy_place▁holder▁no▁813｜>不用担心 —— `service.sh` 会在下次开机、`boot_completed` 之后自动补装修补版 manager 和 prompt app，效果一样。

### B. 想自己构建 / 适配别的上游版本

```bash
git clone https://github.com/<你的账号>/vector-careme-fix.git
cd vector-careme-fix

python bootstrap.py     # 下载 baksmali / smali / uber-apk-signer 等工具到 tools/
python build.py --base /path/to/Vector-v2.2-XXXX-Release.zip
```

产物在 `out/` 下。更详细的构建说明、CI 用法、常见问题见 [`docs/BUILD.md`](docs/BUILD.md)。

**依赖：** Python 3.8+ 和任意 JDK 8+，其余全部由 `bootstrap.py` 自动拉取。

---

## 仓库结构

```
vector-careme-fix/
├── build.py                    # 一键构建入口（编排下面三个 stage）
├── bootstrap.py                # 下载 Java 工具依赖
├── src/
│   ├── dexutil.py              # 轻量 dex 解析 + dex 头校验修复
│   ├── stage1_manager.py       # 修 Compose autofill 崩溃（字节级 dex 补丁）
│   ├── stage2_daemon.py        # 解除 daemon 对 manager 的签名校验（smali 重编）
│   ├── stage3_module.py        # 打包模块：补 sepolicy 兜底 / 装修补版 manager / 重算 sha256
│   └── tools.py                # jar 依赖管理 + 进程封装
├── patches/
│   └── InstallerVerifier.verifyInstallerSignature.smali   # Stage 2 的替换方法体
├── docs/
│   ├── ANALYSIS.md             # 三个问题的完整技术分析
│   ├── BUILD.md                # 构建与排错
│   └── TROUBLESHOOTING.md      # 刷完之后还是不正常怎么办
├── LICENSE                     # GPL-3.0（沿用上游）
└── NOTICE.md
```

---

## 补丁都改了什么

### Stage 1 · manager：Compose autofill 崩溃

把 `androidx.compose.ui.autofill.PlatformAutofillManagerImpl` 的 7 个方法
（`cancel` / `commit` / `notifyValueChanged` / `notifyViewEntered` / `notifyViewExited` /
`notifyViewVisibilityChanged` / `requestAutofill`）**原地置为 no-op**。

这些方法返回值都是 `void`，语义上只是「通知一下 autofill」，在没有 autofill 的 ROM 上跳过毫无损失。
做法是 **保留原来的 `insns_size`**，把前 n-1 条指令填 `nop`、最后一条写成 `return-void` ——
不这么做的话 `code_item` 长度变了，`dex2oat` 会报 `Non-zero padding before section` 直接拒载。

### Stage 2 · daemon：接受重签名的 manager

`InstallerVerifier.verifyInstallerSignature(String)` 的方法体替换为 `return-void`。
它是 daemon 注入 manager 之前的唯一一道签名检查，放行后注入流程照常走。

这里是 **baksmali 反编译 → 改 smali → smali 回编**，而不是字节 patch：
直接改字节会让方法体变短、dex 分段错位，同样会被 ART 拒。

### Stage 3 · 模块外壳

* `service.sh` 开头插入幂等的 `magiskpolicy --live --apply sepolicy.rule`；
* `service.sh` / `customize.sh` 加入「先 `pm uninstall` 再 `pm install` 修补版 manager」的逻辑，前者用 stamp 文件保证每次模块构建只跑一次；
* `module.prop` 的 `version` 加 `-fix1` 后缀、`description` 标注补丁内容，并**移除 `updateJson`** —— 否则 Magisk 会把官方新版推给你、覆盖掉修复。

---

## 适用范围与已知限制

✅ **适用**
* 系统缺 `autofill` 服务的 ROM：`adb shell dumpsys autofill` 返回 `Can't find service: autofill`
* 已 root + Magisk（或 Kitsune Mask / Magisk Delta）并能刷模块
* Android 8.1 ~ 17（与上游 Vector 一致）

⚠️ **注意**
* 每台设备、每个上游版本的字节布局都不一样，**不要跨版本混用**别人构建好的 zip —— 请对着你的 base 包重新 `build.py` 一次。
* 本补丁让 daemon 不再校验 manager 签名。manager 本身仍是本机 `pm` 安装的普通应用，Android 自己的安装校验照常生效。
* 如果上游后来换了类名或方法签名，构建脚本会报错而不是静默出错 —— 这是**故意的**，请对照报错检查新版本结构。

---

## 常见问题

**Q：会和官方 Vector 冲突吗？**
A：不会冲突，但会**被覆盖**。`module.prop` 里去掉了 `updateJson`，Magisk 不会自动 upgrade；手动升级官方版才会失效，届时用新版 base 包重新构建一次即可。

**Q：刷完之后还是「未激活」怎么办？**
A：按顺序看 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)。九成情况是旧 manager 的 oat 缓存或 daemon 没被 Magisk 拉起来。

**Q：能不能只应用其中某一个补丁？**
A：可以，三个 stage 互相独立，`build.py` 之外你也可以直接 import 对应的模块单独调用。

**Q：为什么用 Python 而不是 apktool？**
A：apktool 会重排资源、重算 `resources.arsc`，容易和原始包产生不必要的 diff。这里只动 dex 字节和 zip 条目，其余原样保留，`compress_type` 都保持不变（尤其 `lib/*.so` 是 `STORED`，改成 `DEFLATED` 会导致 native lib 解不出来）。

---

## 许可与致谢

本项目是 [JingMatrix/Vector](https://github.com/JingMatrix/Vector) 的**第三方补丁集**，
按上游要求以 **GNU General Public License v3.0** 发布（全文见 [`LICENSE`](LICENSE)）。
所有对 Vector 的修改均在此协议下开放，详见 [`NOTICE.md`](NOTICE.md)。

上游 Vector 本身源自 LSPosed 系 Project，一并致谢其全部贡献者。
工具链致谢：
* [JesusFreke/smali](https://github.com/JesusFreke/smali) —— baksmali / smali
* [patrickfav/uber-apk-signer](https://github.com/patrickfav/uber-apk-signer) —— APK 签名

**免责声明**：本项目按「原样」提供，不含任何担保。刷入第三方模块有变砖风险，请自行备份 boot / data，作者不对任何设备损坏或数据丢失负责。

---

<sub>English summary: this repo patches Vector so it activates and runs correctly on ROMs that ship without the Android Autofill system service (typical for Chinese Wear 4100/5100 smartwatch firmwares such as CaremeOS on the Xiaomi Z10). It fixes three stacked failures — a Compose `PlatformAutofillManagerImpl` crash, the daemon's hardcoded manager-signature check, and missing sepolicy rules — and ships a ready-to-flash Magisk module. See <code>docs/ANALYSIS.md</code> for the technical breakdown.</sub>
