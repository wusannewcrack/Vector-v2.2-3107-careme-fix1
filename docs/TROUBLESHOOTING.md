# 排障：刷完之后还是不正常

按下面顺序查，每条都能单独验证，别跳步。

---

## 0. 先确认你刷对了包

```console
$ adb shell cat /data/adb/modules/zygisk_vector/module.prop
# version 行末尾应该有 -fix1，description 里应该有 "vector-careme-fix"
```

如果 `version` 没有 `-fix1`，说明刷的是官方包，或者 Magisk 把它覆盖回去了。

---

## 1. daemon 到底起没起来

```console
$ adb shell ps -A | grep vectord
# 有输出 = 起来了；没有 = 下面 2 的问题
```

daemon **必须**由 Magisk 在开机阶段拉起（`service.sh` 里的
`unshare --propagation slave -m ./daemon`）。自己 `nohup ./daemon &`
是注入不了 `system_server` 的 —— 缺正确的 SELinux 域和挂载命名空间。

---

## 2. manager 是不是修补版

```console
$ adb shell pm path org.matrix.vector.manager
$ adb shell ls -l /data/adb/modules/zygisk_vector/.manager_stamp 2>/dev/null
$ adb shell sha256sum /data/adb/modules/zygisk_vector/manager.apk
$ adb shell sha256sum <上面 pm path 给出的路径>
```

两个 sha256 **必须一致**。不一致说明设备上装的还是旧 manager：

```console
$ adb shell pm uninstall org.matrix.vector.manager
$ adb reboot
```

重启后 `service.sh` 会按 stamp 重新装一次。

---

## 3. 换过 daemon.apk 没清 oat → 补丁等于没打

这是最容易踩的一条。ART 会把旧的 oat 缓存住，
**你换了 APK 但 ART 还在跑老代码**，现象是「什么都改了但行为一点没变」。

```console
$ adb shell rm -rf /data/adb/modules/zygisk_vector/oat
$ adb reboot
```

> 如果模块目录只读先 remount：
> `adb shell su -c "mount -o rw,remount /debug_ramdisk/.magisk/modules"`
> 还不行就临时 `adb shell su -c setenforce 0` 再操作。

---

## 4. manager 看日志：有没有「注入成功」

```console
$ adb logcat | grep -iE "Vector manager injected|vectord"
```

看到 `Vector manager injected successfully` 就说明 Stage 2 生效了。
如果看到 `Skipped ... no binder`，回去看第 3 条。

---

## 5. 显示「异常 / Degraded」但功能正常

大概率是 `HealthIssue.SepolicyNotLoaded`。临时验证：

```console
$ adb shell su -c "magiskpolicy --live --apply /data/adb/modules/zygisk_vector/sepolicy.rule"
```

界面立刻变「已激活」的话，就确定是它。本补丁的 `service.sh` 已经在开机时
自动 apply 了；如果仍然复发，说明你的 Magisk 分支的 `magiskpolicy` 有问题，
检查一下：

```console
$ adb shell which magiskpolicy
$ adb shell magiskpolicy --live --apply /data/adb/modules/zygisk_vector/sepolicy.rule
```

另外两项 HealthIssue 的含义：

| HealthIssue | 含义 | 常见原因 |
| --- | --- | --- |
| `SystemServerNotInjected` | system_server 没被注入 | daemon 不是 Magisk 拉起的（见第 1 条） |
| `Dex2oatWrapperBroken` | dex2oat 包装不可用 | 模块 bin/ 权限不对，或 ROM 的 dex2oat 路径非标准 |

---

## 6. 还是崩溃

如果现在的崩溃**不是**下面这条：

```
java.lang.IllegalStateException: Could not locate AutofillManager from context
```

那大概率是新问题，请把 logcat 完整抓下来。可以用 rmurf方式确认 autofill 补丁本身有没有打进去：

```console
$ adb shell dumpsys autofill     # 应该仍然报 Can't find service，这是 ROM 的锅
```

然后确认你装的 manager.apk 的 sha256 跟构建产物一致（见第 2 条）。

---

## 7. 卡在数据线 / adb 掉线

手表类设备的 USB 很爱掉。命令带重试：

```bash
for i in 1 2 3 4 5; do adb devices | grep -q device$ && break; sleep 2; done
adb wait-for-device shell 'while [ "$(getprop sys.boot_completed)" != 1 ]; do sleep 1; done'
```

`su -c "复杂命令"` 的引号在各种 shell 里会被吃掉。稳妥做法是
把命令写成一个 `.sh` push 到 `/data/local/tmp/` 再执行。

---

## 全都试过了

开 issue，请附上：

```console
$ adb shell getprop ro.build.description
$ adb shell getprop ro.product.cpu.abi
$ adb shell su -c magisk -v
$ adb shell cat /data/adb/modules/zygisk_vector/module.prop
$ adb logcat -d | grep -iE "vector|zygisk"
$ adb shell /data/adb/modules/zygisk_vector/cli status 2>&1 | head -40
```
