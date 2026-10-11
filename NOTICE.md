# 说明 / NOTICE

## 上游归属

本仓库 `vector-careme-fix` 是 **[Vector](https://github.com/JingMatrix/Vector)** 的第三方补丁与构建工具集，
**不是官方项目**，与 JingMatrix 无关联。

- 上游仓库：https://github.com/JingMatrix/Vector
- 上游许可：GNU General Public License v3.0
- 上游作者：JingMatrix（及其全部贡献者）

Vector 自身源自 LSPosed 系 Project 谱系（LSPosed / LSPatch / EdXposed），
本仓库同时向其全部贡献者致谢。

## 本仓库的产物性质

本仓库**不包含、也不分发 Vector 的任何二进制 Artifact**。仓库里只有：

1. 补丁本身的描述（方法体片段）；
2. 生成补丁与打包模块的 Python 脚本。

构建时 `build.py` 需要用户**自己提供官方发布的模块 zip** 作为输入（本地文件，不上网）。
输出的修复版模块 zip 是用户在自己机器上生成的衍生产物。

## 修改范围

相对官方 Vector 模块包，本补丁集只改动以下内容：

| 文件 | 改动 |
| --- | --- |
| `manager.apk` | `androidx.compose.ui.autofill.PlatformAutofillManagerImpl` 的 7 个 void 方法置为 no-op |
| `daemon.apk` | `org.matrix.vector.daemon.utils.InstallerVerifier.verifyInstallerSignature` 方法体替换为 `return-void` |
| `service.sh` | 追加 sepolicy 兜底加载、manager 动态安装逻辑 |
| `customize.sh` | 追加修补版 manager 的安装逻辑 |
| `module.prop` | version 加后缀、description 标注补丁、移除 `updateJson` |
| 各 `.sha256` | 随对应文件同步重算 |

其余文件（zygisk 库、`framework/vector.dex`、`cli`、`dex2oat` wrapper、`prompt.apk` 等）
一律**原样保留**。

## 许可证

本项目按上游要求以 **GPL-3.0** 发布，完整条款见 [`LICENSE`](LICENSE)。
依据 GPLv3 第 5 条，本仓库对上游文件的修改已显著标记（见上表与 `patches/` 目录），
修改日期与自然演化记录保留在 Git 历史中。

第三方工具的许可保持各自原授权：
- smali / baksmali（JesusFreke）— BSD 3-Clause
- dexlib2 — BSD 3-Clause
- Guava — Apache-2.0
- jcommander, antlr-runtime — 各自的开源许可
- uber-apk-signer（patrickfav）— Apache-2.0
