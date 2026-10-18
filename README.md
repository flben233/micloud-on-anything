# Xiaomi Cloud Port Pipeline

把小米 17（nezha，HyperOS 3 / Android 16）的小米云服务、小米相册、小米录音机移植到 AOSP Android 16 的 Magisk/KernelSU 模块构建流水线。

本仓库不存放 ROM、APK、模块 zip 或签名私钥；这些文件由配置指定并在本机生成。

## 当前状态

- 已在 x86_64 Android 16 模拟器（Magisk 30.7 + live_setup）完成全链路验证。
- 已验证：账号 dex 补丁、RtMiCloudSDK 资源合并、MiuiPortPerms、CloudIdProvider、云备份 device ID、相册安装、录音机部署。
- 当前模块：`1.0.8` / `versionCode=9`，已重新刷入并在模拟器激活。
- 当前确定性模块包：`194,823,112B`，SHA256 `74697C7DFEDC9FBC1B5F39051429C015FA7255CAF8F9FDB3889AD53254A72C35`。
- v1.0.6 已完成模拟器全链路验证；v1.0.7 的 `uninstall.sh` 已在模拟器实际执行并恢复；v1.0.8 修复账号 dex2oat 后 bind mount 未卸载的问题（改用 `umount -l`）。
- 尚未验证：arm64 真机、KernelSU、干净设备首次安装；12.7GB ROM tgz 的全量解包路径尚未实跑。
- 已知遗留：账号设置页可能因 `FindDeviceStatusManager` 绑定 `com.xiaomi.finddevice` 失败而崩溃，和 cloudbackup device ID 无关。

## 目录结构

```text
scripts/
├─ pipeline.py              # 唯一入口
├─ run.ps1                  # PowerShell 包装器
├─ config/
│  ├─ rom.toml              # ROM、模块、工具、补丁偏移配置
│  ├─ local.toml.example    # 本机签名配置示例
│  └─ local.toml            # 本地覆盖，git 忽略
├─ lib/
│  ├─ util.py               # 命令、哈希、路径、日志
│  ├─ config.py             # TOML 配置加载与合并
│  ├─ apk.py                # dex 补丁、AXML、简单 APK、签名
│  ├─ arsc.py               # RtMiCloudSDK 三包 arsc 合并
│  ├─ rtmc.py               # RtMiCloudSDK 完整构建
│  ├─ module.py             # 模块组装、脚本渲染、确定性 zip
│  ├─ erofs.py              # EROFS 读取/解压
│  ├─ lpunpack.py           # super.img 逻辑分区提取
│  └─ simg2img.py           # sparse image 转换
├─ steps/
│  ├─ preflight.py          # 输入、工具、SHA1、签名检查
│  ├─ extract.py            # ROM/分区 → 输入树
│  ├─ build.py              # 构建全部产物
│  └─ verify.py             # 模拟器验证
├─ templates/module/        # Magisk 模块脚本模板
├─ assets/                  # 权限 XML、provider 源码、libshell stub、类路径
├─ build/                   # 生成物，git 忽略
├─ releases/                # 发布 zip，git 忽略
├─ inputs/                  # ROM/提取物/密钥，git 忽略
└─ tools/                   # 本地工具，git 忽略
```

## 环境要求

- Windows PowerShell 5.1 或更新版本（当前开发环境）。
- Python 3.11+，当前使用 3.13.9。
- Python 包：`lz4`（读取 EROFS 压缩文件）。
- Android SDK：
  - build-tools 36.0.0：`aapt2`、`zipalign`、`apksigner`、`d8`
  - platform `android-37.0` 的 `android.jar`
- JDK：`javac`、`apksigner` 所需；当前使用 IntelliJ JBR。
- 可选：`zig`（重新编译 libshell stub；不提供时使用 `assets/` 中已编译的 x86_64/arm64 stub）。
- 验证需要已启动的模拟器、adb root、`/data/local/tmp/live_setup.sh` 和 Magisk live 环境。

路径都在 `config/rom.toml` 的 `[tools]` 中配置，不依赖当前工作目录。

## 首次配置

复制签名示例并填入自己的 keystore 密码：

```powershell
Copy-Item config\local.toml.example config\local.toml
```

```toml
[signing]
store_password = "your-store-password"
key_password = "your-key-password"
```

`config/local.toml` 已被 `.gitignore` 忽略，不要提交签名私钥或密码。

默认配置假定：

```text
inputs/own.jks                         # keystore
inputs/extracted/                      # 已提取的 ROM 输入
inputs/partitions/                     # product_a.img 等分区
inputs/nezha_images_....tgz            # 原始 ROM
E:/Xiaomi/work/tmp/gallery_43118_global.apk
```

按实际位置修改 `config/rom.toml` 的 `[paths]`。`source` 下的路径相对 `inputs` 根目录。

## 快速开始：已有解包输入

当前开发机上已有 `E:\Xiaomi\work\extract`，直接构建：

```powershell
python -X utf8 .\pipeline.py --inputs E:\Xiaomi\work\extract preflight
python -X utf8 .\pipeline.py --inputs E:\Xiaomi\work\extract build
```

产物：

```text
build/artifacts/                       # account patch、RTMC、perms、cloudid 等
build/module/MiCloudPort/              # 可直接检查的模块目录
build/MiCloudPort.zip                  # 模块包
releases/MiCloudPort-1.0.8.zip         # 发布副本
```

用 PowerShell 包装器：

```powershell
.\run.ps1 --inputs E:\Xiaomi\work\extract build
```

模块 zip 使用固定时间戳和 Python `zipfile` 生成；相同输入重复构建会得到相同 SHA256。不要用 7-Zip 重新打包，7z 产物在 Android/Magisk 上可能被识别为 Invalid，并解出 0 字节文件。

## 从分区提取

如果已有 `super.img` 分区文件：

```powershell
python -X utf8 .\pipeline.py `
  --partitions E:\Xiaomi\work\partitions `
  --inputs .\build\extracted `
  extract --partitions-only
```

会从 EROFS 分区提取：

```text
product/app、product/priv-app、product/data-app、product/etc
system_ext/priv-app/RtMiCloudSDK、system_ext/app/miuisystem
system_ext/framework、system_ext/etc
system/framework.jar、system/etc/classpaths、system/etc/permissions
mi_ext/etc
```

然后用提取目录构建：

```powershell
python -X utf8 .\pipeline.py --inputs .\build\extracted build
```

## 从 ROM tgz 全量提取

```powershell
python -X utf8 .\pipeline.py extract
```

流程：

1. 从 `paths.rom_tgz` 读取 `*.img`。
2. sparse image 自动转换。
3. 从 `super.img` 提取 `product_a`、`system_ext_a`、`system_a`、`mi_ext_a`。
4. 从 EROFS 提取流水线需要的目录到 `paths.inputs`。

注意：当前代码路径已实现，但尚未用实际 12.7GB tgz 完整跑过；建议先用 `--partitions-only` 验证。

## 卸载

Magisk/KernelSU 卸载模块时会执行 `uninstall.sh`，自动清理：

- 账号 odex/vdex、`/data/adb/micloudport_*` marker 和版本缓存
- `/data/local/tmp/micloudport*` 日志与临时文件
- `com.miui.port.cloudid` data-app 及其数据目录
- 模块安装的 4.3.1.18 相册（仅当其仍为 data-app 版本 `4030118`）
- `READ_DEVICE_IDENTIFIERS`、相册存储 appop、调试属性和模拟器 captive portal 设置
- 录音机 CTA 预置文件

不会自动删除：账号登录态、小米云/同步/备份的应用数据、用户手动保留的相册/录音数据。需要彻底清理时，先卸载模块，再按需清理对应应用数据和 `accounts.db`。

已在模拟器实测 v1.0.7 和 v1.0.8：CloudIdProvider/Gallery 被卸载、账号 odex/vdex 和 marker 被删除、appops 恢复 default、`hidden_api_policy`/captive portal 设置被删除；随后重新刷入模块并重启，service 自动恢复 provider、gallery 和账号 odex。测试中发现账号 dex2oat 的 bind mount 可能因 busy 未卸载，v1.0.8 已把 `umount` 改为 `umount -l` 并在卸载脚本中主动清理解除。

如果直接删除 `/data/adb/modules/micloudport` 而不通过 Magisk/KernelSU 卸载，`uninstall.sh` 不会执行，仍需手动清理上述残留。卸载完成后建议重启，让 systemless overlay/属性完全移除。

## 命令说明

### `preflight`

检查输入 APK、account APK SHA1、build-tools、android.jar、JDK、keystore、RtMiCloudSDK/miuisystem 结构。任何关键缺口直接失败。

```powershell
python -X utf8 .\pipeline.py --inputs E:\Xiaomi\work\extract preflight
```

### `extract`

```powershell
python -X utf8 .\pipeline.py [--partitions DIR] [--inputs DIR] extract [--force] [--partitions-only]
```

### `build`

```powershell
python -X utf8 .\pipeline.py --inputs DIR build [--version VERSION] [--version-code N] [--no-package]
```

执行内容：

- 从 stock `MIUIXiaomiAccount.apk` 提取 `classes.dex` / `classes2.dex`，按配置偏移修补 `Intent.getMiuiFlags` 与 `ContentResolver.getContentResolverForUser`，修正 dex SHA1/adler32，生成 STORED zip。
- 合并 `RtMiCloudSDK.apk` + `framework-ext-res.apk` + `miuisystem.apk` 的 arsc 全局字符串池，重映射 0x11/0x12 包，剥离 `CLOUD_MANAGER`/`FIND_DEVICE` 权限声明，替换 patched `classes.dex` 并追加 miuisystem 的 `classes2.dex`。
- 构建 `MiuiPortPerms.apk`（无代码，声明 normal 级 MIUI 权限）。
- 构建独立 `CloudIdProvider.apk`（`com.miui.port.cloudid`，authority `com.xiaomi.cloud.cloudidprovider`）。
- 从 miuisystem.apk 提取 dex 生成 `MiuiSystemCls.jar`。
- 复制小米云、账号、备份、FindMy、录音机 APK，复制 cloudbackup arm64 库。
- 生成 `system.prop` 与 `post-fs-data.sh` 属性块。
- 渲染 `patch_account_dex.sh` 的 stock ZIP CRC 与 patched SHA1。
- 组装 `build/module/MiCloudPort` 和确定性 zip。

### `package`

只重新打包已有模块目录：

```powershell
python -X utf8 .\pipeline.py package `
  --module-dir .\build\module\MiCloudPort `
  --output .\build\MiCloudPort.zip
```

### `verify`

对已启动的模拟器执行：

1. `adb root` / `adb remount`
2. 运行 `/data/local/tmp/live_setup.sh`
3. 等待 boot 与 `sys.user.0.ce_available=true`
4. 启动 `CloudBackupDetailActivity`
5. `content call` 查询 CloudIdProvider
6. 检查相册 versionCode
7. 检查 `micloudport.log` 中的 `Unknown authority` / `IllegalDeviceException`
8. 检查 crash buffer 中的 cloudbackup

```powershell
python -X utf8 .\pipeline.py verify --zip .\build\MiCloudPort.zip
```

`--install` 会 push 并执行 `magisk --install-module`；模块真正生效仍需要重启或 live_setup。`--no-start` 可跳过启动 cloudbackup。

### `all`

```powershell
python -X utf8 .\pipeline.py --inputs E:\Xiaomi\work\extract all
```

依次执行 preflight、build、package、verify。`--skip-emulator` 只构建不验证。

## 关键设计

### 账号 dex 补丁

真实框架缺口只有两个：

- `Intent.getMiuiFlags()I`：改为 `const/4 v0, 0; return v0`
- `Context.getContentResolverForUser(UserHandle)`：改为调用 `getContentResolver()`

补丁后必须重算 dex 的 SHA1 和 adler32，并保持 zip 条目 STORED。模块运行时由 `patch_account_dex.sh` 通过 bind mount 让 dex2oat 读取 patched zip，再把 odex/vdex 部署到 dalvik-cache；vdex 和 odex stub 的校验和必须是 **stock APK 的 ZIP CRC**，不是 dex adler32。

### RtMiCloudSDK 资源合并

三个 APK 的 arsc 包 ID：

- `0x60`：`com.xiaomi.micloud.sdk`
- `0x11`：`android.miui`
- `0x12`：`miui.system`

流水线重建全局字符串池、重映射 0x11/0x12 的字符串索引、保留 extres 的 style span 区，并用 `aapt2 dump resources` 做最终合法性校验。

### CloudIdProvider

cloudbackup 在 `ro.miui.restrict_imei=1` 且 SDK>=31 时访问：

```text
content://com.xiaomi.cloud.cloudidprovider
```

AOSP 没有这个 provider。模块使用独立 data-app `com.miui.port.cloudid` 提供 `getCloudId`，返回 `Settings.Secure.ANDROID_ID`。不要放回 `/system/framework/MiuiPortPerms`：PMS 能注册 authority，但 AMS 的 provider map 不会注册 `/system/framework` 包，`content call` 仍会失败。

### 模块脚本

- `post-fs-data.sh`：`resetprop` 设置 15 个 MIUI 属性；模块 versionCode 变化时清 `package_cache`。
- `service.sh`：等待 CE 解锁，设置 appops/权限，预置录音机 CTA，安装 CloudIdProvider 和相册，最后触发账号 odex 补丁。
- `customize.sh`：按 `$ARCH`（arm64/x64）选择 libshell stub，并创建 `system/lib64`。
- `uninstall.sh`：通过 Magisk/KernelSU 卸载模块时清理 odex/vdex、data-app、appops、临时文件和 CTA 预置；不删除账号/云服务用户数据。

## 常见问题

- **7-Zip 打包后设备报 Invalid**：改用本流水线的 Python `zipfile`；不要用 `7z a` 重新打包模块。
- **Magisk 安装后关键 jar 为 0 字节**：通常仍是 7z 打包问题；用设备 `unzip -l` 检查。
- **service 写 appops/pm 报 `Failed transaction`**：还没到 CE 解锁；等待 `sys.user.0.ce_available=true`。
- **相册打开停在 Permissions required**：除 runtime 权限外还需要 `MANAGE_EXTERNAL_STORAGE` appop；首次启动还需手动接受相册自己的 Terms/通知 CTA。
- **模拟器默认 GPU 循环重启**：使用 `-gpu host -no-boot-anim`；`swiftshader_indirect` 太卡。
- **账号设置页 FindDevice 崩溃**：当前遗留问题，不影响 cloudbackup device ID 验证；需要补 `com.xiaomi.finddevice` service 或禁用状态检查。
- **相册 5.x 不能用**：5.x 是 HyperOS Rust 应用，依赖 `hyos_spawner` 和 HyperOS system_server，纯 AOSP 不可模块化；本流水线固定使用 4.3.1.18-global。

## 未提交文件

以下内容不会进入 git：

```text
build/
releases/
inputs/
tools/
config/local.toml
*.apk *.jar *.zip *.img *.tgz *.jks *.log
```

`assets/` 下的权限 XML、provider 源码、stub、cloudbackup arm64 小库会提交。
