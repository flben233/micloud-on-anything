from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from lib import apk, module, rtmc
from lib.util import PipelineError, ensure_dir, log, require_dir, require_file, sha256_file


def _source(config, key: str, inputs: Path) -> Path:
    value = config.get(f"source.{key}")
    if not value:
        raise PipelineError(f"missing source.{key}")
    return (inputs / value).resolve()


def _paths(config, inputs: Path, build_root: Path) -> dict[str, Path]:
    return {
        "account": _source(config, "account", inputs),
        "rtmc": _source(config, "rtmc", inputs),
        "extres": _source(config, "extres", inputs),
        "miuisystem": _source(config, "miuisystem", inputs),
    }


def build(
    config,
    inputs: Path,
    build_root: Path,
    *,
    skip_gallery: bool = False,
    version: str | None = None,
    version_code: int | None = None,
) -> dict:
    require_dir(inputs, "extracted ROM input")
    source = _paths(config, inputs, build_root)
    for key, path in source.items():
        require_file(path, key)
    build_tools = config.path("tools.build_tools")
    android_jar = config.path("tools.android_jar")
    java_home = str(config.get("tools.java_home", "")) or None
    keystore = config.path("paths.keystore")
    require_file(keystore, "signing keystore")
    alias = str(config.get("signing.alias"))
    store_password = str(config.get("signing.store_password"))
    key_password = str(config.get("signing.key_password"))

    build_root = ensure_dir(build_root)
    artifacts_dir = ensure_dir(build_root / "artifacts")
    work_dir = ensure_dir(build_root / "work")

    account_json = artifacts_dir / "account_patch.json"
    account = apk.build_account_patch(
        config,
        source["account"],
        artifacts_dir / "patched_account.zip",
        account_json,
    )
    log(f"account patch: classes.dex={account['dex']['classes.dex']['sha1']} classes2.dex={account['dex']['classes2.dex']['sha1']}")

    rtmc_apk = rtmc.build_rtmc(
        rtmc_apk=source["rtmc"],
        extres_apk=source["extres"],
        miuisystem_apk=source["miuisystem"],
        output_apk=artifacts_dir / "RtMiCloudSDK.apk",
        work_dir=work_dir / "rtmc",
        build_tools=build_tools,
        android_jar=android_jar,
        java_home=java_home,
        keystore=keystore,
        alias=alias,
        store_password=store_password,
        key_password=key_password,
        get_sender_offset=int(config.get("rtmc.get_sender_offset")),
        get_sender_old_hex=str(config.get("rtmc.get_sender_old_hex")),
        get_sender_new_hex=str(config.get("rtmc.get_sender_new_hex")),
        metadata_path=artifacts_dir / "rtmc.json",
    )

    miuisystem_jar = apk.build_dex_jar(source["miuisystem"], artifacts_dir / "MiuiSystemCls.jar")
    androidx_stub = apk.build_java_dex_jar(
        source_dir=Path(__file__).resolve().parents[1] / "xposed" / "stub",
        output_jar=artifacts_dir / "androidx-core-stub.jar",
        work_dir=work_dir / "androidx-stub",
        build_tools=build_tools,
        android_jar=android_jar,
        java_home=java_home,
    )
    xposed_script = Path(__file__).resolve().parents[1] / "xposed" / "build.py"
    xposed_apk = build_root / "MiCloudXposed.apk"
    if not xposed_script.is_file():
        raise PipelineError(f"Xposed build script not found: {xposed_script}")
    log("building Xposed module APK")
    subprocess.run([sys.executable, str(xposed_script)], check=True)
    perms = apk.build_simple_apk(
        build_tools=build_tools,
        android_jar=android_jar,
        java_home=java_home,
        manifest=Path(__file__).resolve().parents[1] / "assets" / "perms-manifest.xml",
        source_dir=None,
        output_apk=artifacts_dir / "MiuiPortPerms.apk",
        work_dir=work_dir / "perms",
        keystore=keystore,
        alias=alias,
        store_password=store_password,
        key_password=key_password,
    )

    cloudid_src = work_dir / "cloudid" / "src" / "com" / "miui" / "port" / "cloudid"
    ensure_dir(cloudid_src)
    shutil.copy2(Path(__file__).resolve().parents[1] / "assets" / "CloudIdProvider.java", cloudid_src / "CloudIdProvider.java")
    cloudid = apk.build_simple_apk(
        build_tools=build_tools,
        android_jar=android_jar,
        java_home=java_home,
        manifest=Path(__file__).resolve().parents[1] / "assets" / "cloudid-manifest.xml",
        source_dir=cloudid_src,
        output_apk=artifacts_dir / "CloudIdProvider.apk",
        work_dir=work_dir / "cloudid",
        keystore=keystore,
        alias=alias,
        store_password=store_password,
        key_password=key_password,
    )

    assets = Path(__file__).resolve().parents[1] / "assets"
    libshell_x64 = assets / "libshell_jni_x86_64.so"
    libshell_arm64 = assets / "libshell_jni_arm64.so"
    zig = config.project_path("paths.zig", "tools/zig/zig.exe")
    if zig.is_file():
        libshell_dir = ensure_dir(work_dir / "libshell")
        for arch, target, out_name in (
            ("x86_64", "x86_64-linux-android", "libshell_jni_x86_64.so"),
            ("arm64", "aarch64-linux-android", "libshell_jni_arm64.so"),
        ):
            lib = libshell_dir / out_name
            from lib.util import run

            run(
                [
                    str(zig),
                    "cc",
                    "-target",
                    target,
                    "-shared",
                    "-nostdlib",
                    "-fno-stack-protector",
                    "-O2",
                    "-Wl,-soname,libshell_jni.so",
                    "-o",
                    str(lib),
                    str(assets / "stub.c"),
                ],
                label=f"zig libshell {arch}",
            )
        libshell_x64 = libshell_dir / "libshell_jni_x86_64.so"
        libshell_arm64 = libshell_dir / "libshell_jni_arm64.so"

    gallery = config.path("paths.gallery")
    if not skip_gallery:
        require_file(gallery, "gallery APK")
    else:
        if not gallery.is_file():
            raise PipelineError("gallery APK not found (use --skip-gallery only after placing a placeholder)")
    mediaeditor = config.path("paths.mediaeditor")
    require_file(mediaeditor, "mediaeditor APK")

    module_dir = ensure_dir(build_root / "module" / "MiCloudPort")
    module.assemble_module(
        config=config,
        inputs=inputs,
        build_dir=build_root,
        artifacts={
            "account_patch": artifacts_dir / "patched_account.zip",
            "account_json": account_json,
            "cloudid": cloudid,
            "gallery": gallery,
            "mediaeditor": mediaeditor,
            "libshell_x64": libshell_x64,
            "libshell_arm64": libshell_arm64,
            "rtmc": rtmc_apk,
            "miuisystem_jar": miuisystem_jar,
            "androidx_stub": androidx_stub,
            "xposed_apk": xposed_apk,
            "perms": perms,
        },
        output_dir=module_dir,
    )
    result = module.package_module(module_dir, build_root / "MiCloudPort.zip")
    result["module_dir"] = str(module_dir)
    result["artifacts"] = {
        "account": str(artifacts_dir / "patched_account.zip"),
        "rtmc": str(rtmc_apk),
        "perms": str(perms),
        "cloudid": str(cloudid),
        "mediaeditor": str(mediaeditor),
        "miuisystem_jar": str(miuisystem_jar),
        "androidx_stub": str(androidx_stub),
        "xposed_apk": str(xposed_apk),
        "account_json": str(account_json),
    }
    result["sha256"] = sha256_file(build_root / "MiCloudPort.zip")
    return result
