# 更新日志

本文件的日期遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/) 精神，
版本号跟随「补丁集」而非上游 Vector。

---

## [1.0.0] - 2026-10-12

初始版本。针对 **Vector v2.2 (3107)** 在缺 `autofill` 服务的 ROM 上的三连问题。

### 新增

- **Stage 1** `src/stage1_manager.py`
  把 Compose 的 `androidx.compose.ui.autofill.PlatformAutofillManagerImpl`
  中 7 个 void 方法（`cancel` / `commit` / `notifyValueChanged` /
  `notifyViewEntered` / `notifyViewExited` / `notifyViewVisibilityChanged` /
  `requestAutofill`）置为 no-op，解决「碰一下屏幕就崩溃」。
  采用定长补丁（nop… + return-void）而非删指令，避免 dex2oat 的
  `Non-zero padding before section`。

- **Stage 2** `src/stage2_daemon.py`
  `InstallerVerifier.verifyInstallerSignature` 方法体替换为 `return-void`，
  让重签名过的 manager 能被 daemon 注入，解决「未激活」。
  走 baksmali/smali 完整重编而非字节 patch。

- **Stage 3** `src/stage3_module.py`
  - `service.sh` 追加开机幂等的 `magiskpolicy --live --apply sepolicy.rule`
  - `service.sh` / `customize.sh` 追加「先 uninstall 再 install」修补版 manager
  - `module.prop` 移除 `updateJson`，防止 Magisk 把官方新版推下来覆盖修复
  - 所有改动过的文件同步重算 `.sha256`

- `bootstrap.py`：按需拉取 baksmali / smali / uber-apk-signer 等到 `tools/`
- `build.py`：三 stage 的一键构建与冒烟校验
- 文档：`README.md`、`NOTICE.md`、`docs/ANALYSIS.md`、`docs/BUILD.md`、`docs/TROUBLESHOOTING.md`

### 已验证

在 **小米 Z10 手表（Wear 4100 平台 + CaremeOS5）** + Magisk 27.2 上：
刷入后 daemon 正常拉起，`cli status` 显示全部 hook 已安装，
manager 界面显示 **Vector 已激活**，多次重启不回退。

### 已知限制

- 补丁擦掉了 daemon 对 manager 的签名校验。manager 仍受 Android 自身的
  安装校验保护，但请不要在不可信的设备上依赖这道防线。
- 若上游改动 `PlatformAutofillManagerImpl` 的方法集或 `InstallerVerifier`
  的签名，构建会**报错中止**而非静默产出错误结果 —— 这是故意的。
