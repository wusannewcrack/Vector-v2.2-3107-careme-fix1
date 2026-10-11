# 构建说明

## 前置条件

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.8+ | 脚本只用了标准库 |
| Java | JDK 8+ | 跑 baksmali / smali / uber-apk-signer |
| 官方 Vector 模块 zip | 任意版本 | **自己去官方 Releases 下载**，本仓库不含二进制 |

Windows / Linux / macOS 都能跑。Windows 上用 Python 或 python 均可。

## 三步走

```bash
# 1. 拉工具依赖到 tools/（只在第一次、或 tools/ 被清掉后需要）
python bootstrap.py

# 2. 构建
python build.py --base /path/to/Vector-v2.2-3107-xxx-Release.zip

# 3. 产物
ls out/
# → Vector-v2.2-3107-xxx-Release-fix1.zip
```

### `build.py` 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--base` | *必填* | 官方 Vector 模块 zip 路径 |
| `--out` | `out/<base名>-fix1.zip` | 输出路径 |
| `--suffix` | `-fix1` | 追加到 `module.prop` 的 `version` 后面 |
| `--work` | `./build` | 中间产物目录（每次构建会清空重来） |
| `--no-sign` | 关闭 | 跳过重签名，仅供调试。**加了这个参数产出的包不能刷** |

## `bootstrap.py` 会下载什么

全部落在 `tools/`，被 `.gitignore` 忽略：

```
baksmali-2.5.2.jar       (org.smali:       Maven Central)
smali-2.5.2.jar          (org.smali:       Maven Central)
dexlib2-2.5.2.jar        (org.smali:       Maven Central)
util-2.5.2.jar           (org.smali:       Maven Central)
jcommander-1.82.jar      (com.beust:       Maven Central)
guava-31.1-jre.jar       (com.google:      Maven Central)
antlr-runtime-3.5.3.jar  (org.antlr:       Maven Central)
uber-apk-signer-1.3.0.jar(github.com/patrickfav/uber-apk-signer)
```

网络不便时可以手动下载丢进去，文件名必须一致（`bootstrap.py` 靠文件名判断缺哪个）。

> uber-apk-signer 在 Maven Central 上也有 (`io/github/patrickfav/uber-apk-signer/1.3.0`)，
> `src/tools.py` 里把 GitHub 源放前面、Maven 源作为备选。

## 构建到底做了什么

```
┌─ Stage 1 ─ manager ─────────────────────────────────────────┐
│ 1. 从 base zip 取出 manager.apk                              │
│ 2. 扫 classes*.dex，找到含 PlatformAutofillManagerImpl 的那个 │
│ 3. 7 个目标方法原地改成 nop… + return-void                    │
│ 4. 重算 dex 头 signature(0x0c) → checksum(0x08)              │
│ 5. 写回 APK，丢掉 META-INF 签名条目                           │
│ 6. uber-apk-signer 重签                                      │
└────────────────────────────────────────────────────────────┘
┌─ Stage 2 ─ daemon ──────────────────────────────────────────┐
│ 1. 扫 dex 找到含 InstallerVerifier 的那个                     │
│ 2. baksmali 反编译 → 正则替换方法体 → smali 回编              │
│ 3. 替换原 dex，丢签名，重签                                   │
└────────────────────────────────────────────────────────────┘
┌─ Stage 3 ─ 打包 ────────────────────────────────────────────┐
│ 替换 manager.apk / daemon.apk / service.sh / customize.sh /  │
│ module.prop，其余文件原样搬运，同步重算所有 .sha256           │
└────────────────────────────────────────────────────────────┘
```

所有 zip 条目都**保持原始的 `compress_type`**。这不是洁癖：`lib/*.so` 是 `STORED`，
如果被改成 `DEFLATED`，Android 在提取 native lib 时会解不出来，模块直接废掉。

## 上游出新版本了怎么办

1. 下载新的官方模块 zip；
2. 直接 `python build.py --base 新版.zip --suffix -fix1`。

脚本对版本号、dex 编号（不一定还是 `classes17` / `classes23`）都做了扫描，
不写死。如果上游改了类名或方法签名，构建会**报错而不是静默跳过**：

```
ToolError: xxx.dex 里找不到 InstallerVerifier，可能这个版本的类名变了
ToolError: verifyInstallerSignature 方法体没匹配上，smali 结构可能变了
```

这时请对照新版本结构更新 `src/stage1_manager.py` 的 `TARGET_METHODS`
和 `src/stage2_daemon.py` 的 `TARGET_METHOD_RE`。

## CI 里用

仓库自带 `.github/workflows/build.yml`，手动触发（因为需要你提供 base 包 URL，
自动抓取第三方二进制不合适）。在 GitHub 上 Actions → Build → Run workflow，
填入：

- `base_url`：官方 Vector 模块 zip 的下载直链
- `suffix`：版本后缀，默认 `-fix1`

产物作为 Artifact 下载。

## 构建完怎么验证

`build.py` 自带三步冒烟检查：模块内所有 `.sha256` 自洽、manager 里目标类还在、
daemon 里目标类还在。想手动复查：

```bash
python -c "
import zipfile,hashlib
z=zipfile.ZipFile('out/xxx-fix1.zip')
bad=[n for n in z.namelist() if n.endswith('.sha256')
     and z.read(n).decode().split()[0]
     != hashlib.sha256(z.read(n[:-7])).hexdigest()]
print('mismatch:', bad or 'none ✅')
"
```

签名方案可以直接查出：

```bash
java -jar tools/uber-apk-signer-1.3.0.jar -a out/xxx-fix1.zip -y
```
（对外层 zip 不会成立，解开里面的 manager.apk / daemon.apk 再验。）
