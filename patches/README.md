# patches 目录说明

这里放的是「补丁内容本身」，而不是整份反编译结果（后者动辄几万行、且随上游版本变化）。

| 文件 | 用途 |
| --- | --- |
| `InstallerVerifier.verifyInstallerSignature.smali` | Stage 2 替换用的方法体。构建时 `src/stage2_daemon.py` 会用正则匹配 daemon 反编译结果里的同名方法并整体替换。 |

之所以只放方法片段而不是整个 `InstallerVerifier.smali`：Kotlin 类的 `@Metadata` 注解里
带版本专属的 `d1`/`d2` 字符串表，整文件覆盖会在跨版本时写错元数据。
方法级替换对上游版本变化更宽容，也更容易 review。

Stage 1（manager 的 autofill 修复）是纯字节级 dex 改动，没有 smali 产物，
逻辑直接写在 `src/stage1_manager.py` 里。
