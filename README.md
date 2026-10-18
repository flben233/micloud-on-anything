# Xiaomi Cloud Port Pipeline

把小米 17（nezha，HyperOS 3 / Android 16）的小米云服务、小米相册、小米录音机移植到 AOSP Android 16 的 Magisk/KernelSU 模块构建流水线。

本仓库不存放 ROM、APK、模块 zip 或签名私钥；这些文件由配置指定并在本机生成。

## 当前状态

- 已在 x86_64 Android 16 模拟器（Magisk 30.7 + Vector + live_setup）完成全链路验证。
- 已验证：账号 dex 补丁、RtMiCloudSDK 资源合并、MiuiPortPerms、CloudIdProvider、云备份 device ID、国内版相册替换、MediaEditor 安装与编辑保存、录音机部署；相册云同步已验证到元数据/列表下载（`cloud` 表 730→1537，128 photos+1 video），文件上传尚未验证。
- **2026-10-18 Xposed 注入验证**：Vector 加载 `MiCloudXposed` 后，`ApplicationLoaders.getSharedLibraryClassLoaderWithSharedLibraries` 钩子把 12 个 MIUI jar 注入 `RtMiCloudSDK.apk` 的 classloader，包级 `onPackageLoaded` 再注入各应用；cloudservice/account/simactivate/soundrecorder/gallery 均出现 `SubscriptionManager resolved`，`get deviceId failed`/`IllegalDeviceException` 不再出现，无 FATAL。
- 当前模块：`1.2` / `versionCode=18`，作者 `ShirakawaTyu`。已移除 `post-mount.sh`/`initrc`/`load_exports` 的 bootclasspath 方案，改用 Vector + libxposed；模块内含 `system/system_ext/framework/androidx-core-stub.jar`（780B），以及 `system/product/app/` 下的 `CloudIdProvider`、`MiCloudGallery`、`MiMediaEditor`、`MiCloudXposed`（`versionCode=2`）。正常 Magisk/KernelSU 开机由 PMS 直接扫描 system 应用；`service.sh` 只在 `pm path` 缺失时用模块内 APK 兜底安装，并设置 Vector scope。入口 APK `MiCloudLauncher` `1.5` / `versionCode=6` 已安装。
- 当前确定性模块包：`412,297,510B`，SHA256 `8deb7967deff8b0e3ef1830aefaf76173ac49b4f14964e8281d216df8d31b1a8`；`releases/MiCloudPort-1.2.zip` 为发布副本。
- **2026-10-18 v1.2**：Android 16 的 `USE_ICC_AUTH_WITH_DEVICE_IDENTIFIER` 是 runtime permission app-op，`cmd appops set` 无法强制 allow（新 `AccessCheckingService`/`AppOpService` 直接拒绝 UID mode），因此改为在 `com.xiaomi.simactivate.service` 内 hook `j1.r.l/i/c`：捕获 `getSubscriberId` 等 telephony 调用的 `SecurityException` 并返回 null，使激活信息走“SIM 未插入”分支；真机有权限时仍返回原值。`service.sh` 已移除无效的 `allow_icc_auth_appop`。Xposed APK 21,094B，SHA256 `a76863ff5c80e2e6a8645f890f166e0c8cdaf546b0efe0b26902aea67016d4c2`。
- v1.0.6 已完成模拟器全链路验证；v1.0.7/v1.0.8 的 `uninstall.sh` 已实际执行并恢复，且 v1.0.8 修复账号 dex2oat 后 bind mount 未卸载的问题（改用 `umount -l`）；v1.0.9 已完成升级安装、global→国内版相册替换和 MediaEditor 编辑/保存实测（该版本卸载脚本尚未重新执行）。
- 尚未验证：arm64 真机、干净设备首次安装；12.7GB ROM tgz 的全量解包路径尚未实跑。模拟器上 cloudbackup 仍因 `libutils.so` 仅 arm64 崩溃（转译环境限制）。
- 已知遗留：账号设置页可能因 `FindDeviceStatusManager` 绑定 `com.xiaomi.finddevice` 失败而崩溃；与已修复的 cloudbackup device ID 无关。

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
├─ xposed/                  # MiCloudXposed 源码、stub、scope 与构建脚本
├─ launcher/                # 小米云入口 APK 源码（Manifest + Java）
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
- Xposed 构建需要 `inputs/libxposed-api-102.0.0.jar`；运行需要 Vector（`/data/adb/modules/zygisk_vector/cli`）。
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
E:/Xiaomi/work/tmp/gallery_43118_cn.apk
E:/Xiaomi/work/tmp/MiMediaEditor.apk
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
build/MiCloudXposed.apk                # Xposed 模块（打进模块 system/product/app/）
releases/MiCloudPort-1.1.0.zip         # 发布副本
```

用 PowerShell 包装器：

```powershell
.\run.ps1 --inputs E:\Xiaomi\work\extract build
```

模块 zip 使用固定时间戳和 Python `zipfile` 生成；`MiCloudXposed.apk` 也会在签名前归一化 ZIP 时间戳；相同输入重复构建会得到相同 SHA256。不要用 7-Zip 重新打包，7z 产物在 Android/Magisk 上可能被识别为 Invalid，并解出 0 字节文件。

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
- 旧版 data-app 形式的 `com.miui.port.cloudid` 及其数据目录（v1.1.0 起为 system app，随模块移除）
- 旧版 data-app 形式的 `com.miui.port.xposed`
- 旧版 data-app 形式的 4.3.1.18 相册（仅当版本 `4030118`）
- 旧版 data-app 形式的 MediaEditor `com.miui.mediaeditor`（仅当版本 `203990083`）
- `READ_DEVICE_IDENTIFIERS`、相册/编辑器存储 appop、调试属性和模拟器 captive portal 设置
- 录音机 CTA 预置文件

不会自动删除：账号登录态、小米云/同步/备份的应用数据、用户手动保留的相册/录音数据。需要彻底清理时，先卸载模块，再按需清理对应应用数据和 `accounts.db`。

已在模拟器实测 v1.0.7 和 v1.0.8：CloudIdProvider/Gallery 被卸载、账号 odex/vdex 和 marker 被删除、appops 恢复 default、`hidden_api_policy`/captive portal 设置被删除；随后重新刷入模块并重启，service 自动恢复 provider、gallery 和账号 odex。测试中发现账号 dex2oat 的 bind mount 可能因 busy 未卸载，v1.0.8 已把 `umount` 改为 `umount -l` 并在卸载脚本中主动清理解除。v1.1.0 的 Xposed 卸载路径尚未重新实测。

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
6. 检查相册 versionCode/versionName（必须不是 `-global`）与 MediaEditor 是否安装
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

AOSP 没有这个 provider。模块在 `system/product/app/CloudIdProvider/` 预置 `com.miui.port.cloudid` 提供 `getCloudId`，返回 `Settings.Secure.ANDROID_ID`；PMS 扫描后 AMS 会注册该 provider。不要放回 `/system/framework/MiuiPortPerms`：PMS 能注册 authority，但 AMS 的 provider map 不会注册 `/system/framework` 包，`content call` 仍会失败。

### 相册与编辑器

- 采用 **国内版 Gallery 4.3.1.18**（`versionCode=4030118`，来自 memeosupdates 的 China 构建）。它与 `4.3.1.18-global` 的 versionCode 相同，`service.sh` 通过 `versionName` 是否以 `-global` 结尾来判断并替换。
- 编辑按钮依赖 **MediaEditor** `com.miui.mediaeditor` `2.3.0.8.3`（`203990083`）。它与相册一样预置在 `system/product/app/MiMediaEditor/`，正常开机由 PMS 扫描；service 只在缺失时兜底安装。
- MediaEditor 安装时要求 shared library `security-device-credential-sdk.jar`；模块把 ROM 的 `system_ext/framework/security-device-credential-sdk.jar` 和对应的 `system_ext/etc/permissions/security-device-credential-sdk.xml` 一起挂载，否则会报 `INSTALL_FAILED_MISSING_SHARED_LIBRARY`。
- 模拟器已实测：Edit → 接受条款 → 跳过编辑器更新 → Crop/Rotate → Save → 返回相册；输出为新文件（源文件所在相册，例如 `/storage/emulated/0/DCIM/Creative/IMG_*.png` 或存储根目录），相册自动扫描并显示。模拟器上 Filter 缩略图渲染异常（arm64 转译），基础编辑与保存可用。

### APK 预置策略

- `CloudIdProvider`、国内版 Gallery、MediaEditor、`MiCloudXposed` 直接放在模块的 `system/product/app/`，Magisk/KernelSU 正常开机在 PMS 扫描前挂载，因此会作为 system app 注册，不依赖 `service.sh` 的 `pm install`。
- 模拟器 `live_setup` 在开机后才挂载模块，PMS 可能没有扫描到；`service.sh` 用 `pm path`/版本检查做兜底，必要时从 `$MODDIR/system/product/app/...` 复制到 `/data/local/tmp` 再安装。
- 不要把 `CloudIdProvider` 放到 `/system/framework`：PMS 能看到 authority，但 AMS 的 provider map 不会注册该路径的 provider；`system/product/app` 可以正常工作。
- Gallery/MediaEditor 用非 priv-app 的 `system/product/app`，避免 privapp allowlist；存储 appop 仍由 service 设置。

### 模块脚本

- `post-fs-data.sh`：`resetprop` 设置 15 个 MIUI 属性；模块 versionCode 变化时清 `package_cache`。
- `service.sh`：等待 CE 解锁，设置 appops/权限，预置录音机 CTA；CloudIdProvider/Gallery/MediaEditor/Xposed 正常情况下已由 system 扫描，service 只在 `pm path` 为空或版本过旧时从 `system/product/app` 兜底安装，并设置 Vector scope；最后触发账号 odex 补丁。
- `patch_account_dex.sh`：bind mount 补丁 zip 后 `dex2oat64` speed 编译，修改 odex/vdex 的 ZIP CRC，部署到 `/data/dalvik-cache`；脚本用 `trap` 在退出时 `umount -l` 并重新 bind mount 模块内原始 APK（否则会把 Magisk 挂载一起卸载，APK 变成 0 字节）。
- `customize.sh`：按 `$ARCH`（arm64/x64）选择 libshell stub，创建 `system/lib64`。
- `uninstall.sh`：通过 Magisk/KernelSU 卸载模块时清理 odex/vdex、旧版 data-app 残留、appops、临时文件、CTA 预置；不删除账号/云服务用户数据。
- `system/system_ext/framework/androidx-core-stub.jar`：由 `steps/build.py` 从 `xposed/stub` 自动编译；`MiCloudXposed.apk` 由 `xposed/build.py` 构建后放到 `system/product/app/MiCloudXposed/`，由 PMS 扫描，service 仅负责更新/兜底和 Vector scope。

## 常见问题

- **7-Zip 打包后设备报 Invalid**：改用本流水线的 Python `zipfile`；不要用 `7z a` 重新打包模块。
- **Magisk 安装后关键 jar 为 0 字节**：通常仍是 7z 打包问题；用设备 `unzip -l` 检查。
- **service 写 appops/pm 报 `Failed transaction`**：还没到 CE 解锁；等待 `sys.user.0.ce_available=true`。
- **相册打开停在 Permissions required**：除 runtime 权限外还需要 `MANAGE_EXTERNAL_STORAGE` appop；首次启动还需手动接受相册自己的 Terms/通知 CTA。
- **模拟器默认 GPU 循环重启**：使用 `-gpu host -no-boot-anim`；`swiftshader_indirect` 太卡。
- **同一次开机第二次 live_setup 后相册/编辑器崩溃 `EM_AARCH64`**：live_setup 会启用 Zygisk native bridge wrapper，arm64-only 库无法加载；每次 boot 只跑一次，重测前 `adb reboot`。`pipeline verify` 会重跑 live_setup，注意测试顺序。
- **MIUI 应用 `ClassNotFoundException: miui.os.Build`**：1.1.0 不再修改 `BOOTCLASSPATH`，改用 Vector + `MiCloudXposed`。检查 `pm path com.miui.port.xposed`、`/data/adb/modules/zygisk_vector/cli modules ls`、`/data/adb/modules/zygisk_vector/cli scope ls com.miui.port.xposed`；service 日志应有 `installing MiCloudXposed` 和 `vector scope rc=0`。如果 scope 没有目标包，重新执行 `scope set` 或重启后再启动应用。
- **Xposed 没有注入**：确认 Vector 已启用 `com.miui.port.xposed`，并看 logcat 是否有 `MiCloudXposed: loaded in <pkg>`、`ApplicationLoaders hooks installed`、`RtMiCloudSDK.apk: SubscriptionManager resolved`。共享库钩子必须在 `clns-9` 创建前安装；hidden API 豁免日志应出现在同一进程早期。
- **重启后网络一直不 VALIDATED**：模拟器探针可能超时；临时 `settings put global captive_portal_mode 0`，再 WiFi 关闭/开启 + 重设 IPv6 disable。仅模拟器测试用。
- **账号设置页 FindDevice 崩溃**：当前遗留问题，不影响 cloudbackup device ID 验证；需要补 `com.xiaomi.finddevice` service 或禁用状态检查。
- **相册 5.x 不能用**：5.x 是 HyperOS Rust 应用，依赖 `hyos_spawner` 和 HyperOS system_server，纯 AOSP 不可模块化；本流水线固定使用国内版 4.3.1.18 + MediaEditor。

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
