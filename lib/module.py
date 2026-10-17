from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

from .util import (
    PipelineError,
    copy_file,
    copy_tree,
    ensure_dir,
    log,
    read_prop,
    require_dir,
    require_file,
    sha256_file,
)


def _escape_bytes(value: bytes) -> str:
    return "".join(f"\\{b:03o}" for b in value)


def _crc_bytes(value: str) -> bytes:
    return int(value, 16).to_bytes(4, "little")


def render_patch_account_script(script: Path, metadata: dict) -> None:
    text = script.read_text(encoding="utf-8")
    dex = metadata["dex"]
    vdex_bytes = _crc_bytes(dex["classes.dex"]["zip_crc"]) + _crc_bytes(dex["classes2.dex"]["zip_crc"])
    text = re.sub(
        r"printf '\\[0-9]{3}.*?' \| dd of=\"\$VDEX\"",
        lambda _m: f"printf '{_escape_bytes(vdex_bytes)}' | dd of=\"$VDEX\"",
        text,
        count=1,
    )
    case_block = (
        'case "$SHA" in\n'
        f"    {dex['classes.dex']['sha1']})\n"
        f"      printf '{_escape_bytes(_crc_bytes(dex['classes.dex']['zip_crc']))}' | dd of=\"$ODEX\" bs=1 seek=$((OFF + 8)) conv=notrunc 2>/dev/null\n"
        '      echo "patched odex classes.dex stub @ $OFF"\n'
        "      ;;\n"
        f"    {dex['classes2.dex']['sha1']})\n"
        f"      printf '{_escape_bytes(_crc_bytes(dex['classes2.dex']['zip_crc']))}' | dd of=\"$ODEX\" bs=1 seek=$((OFF + 8)) conv=notrunc 2>/dev/null\n"
        '      echo "patched odex classes2.dex stub @ $OFF"\n'
        "      ;;\n"
        "  esac"
    )
    text = re.sub(r'case "\$SHA" in.*?esac', lambda _m: case_block, text, count=1, flags=re.S)
    script.write_text(text, encoding="utf-8", newline="\n")


def write_module_prop(path: Path, config) -> None:
    data = config.section("module")
    text = (
        f"id={data['id']}\n"
        f"name={data['name']}\n"
        f"version={data['version']}\n"
        f"versionCode={data['version_code']}\n"
        f"author={data['author']}\n"
        f"description={data['description']}\n"
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def write_system_prop(path: Path, config) -> None:
    props = config.section("rom.props")
    path.write_text("\n".join(f"{k}={v}" for k, v in props.items()) + "\n", encoding="utf-8", newline="\n")


def render_post_fs_data(script: Path, config) -> None:
    props = config.section("rom.props")
    block = "\n".join(f"set_prop {key} {value}" for key, value in props.items())
    text = script.read_text(encoding="utf-8")
    text = re.sub(
        r"(?ms)^set_prop ro\.miui\.ui\.version\.code .*?^(?=MODVER=)",
        block + "\n\n",
        text,
        count=1,
    )
    script.write_text(text, encoding="utf-8", newline="\n")


def _source(config, key: str, inputs: Path) -> Path:
    value = config.get(f"source.{key}")
    if not value:
        raise PipelineError(f"missing source.{key}")
    return (inputs / value).resolve()


def copy_component(src: Path, dst_dir: Path, name: str | None = None) -> Path:
    require_file(src, src.name)
    target = dst_dir / (name or src.name)
    ensure_dir(target.parent)
    shutil.copy2(src, target)
    return target


def assemble_module(
    *,
    config,
    inputs: Path,
    build_dir: Path,
    artifacts: dict[str, Path],
    output_dir: Path,
) -> Path:
    require_dir(inputs, "extracted ROM input")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    template_dir = Path(__file__).resolve().parents[1] / "templates" / "module"
    copy_tree(template_dir, output_dir)

    write_module_prop(output_dir / "module.prop", config)
    write_system_prop(output_dir / "system.prop", config)
    render_post_fs_data(output_dir / "post-fs-data.sh", config)
    render_patch_account_script(output_dir / "patch_account_dex.sh", json.loads(artifacts["account_json"].read_text(encoding="utf-8")))

    files = ensure_dir(output_dir / "files")
    copy_file(artifacts["account_patch"], files / "patched_account.zip")
    copy_file(artifacts["cloudid"], files / "CloudIdProvider.apk")
    copy_file(artifacts["gallery"], files / "gallery_43118.apk")
    copy_file(artifacts["libshell_x64"], files / "libshell_jni_x86_64.so")
    copy_file(artifacts["libshell_arm64"], files / "libshell_jni_arm64.so")

    product_app = ensure_dir(output_dir / "system" / "product" / "app")
    for key, dest in (
        ("account", "MIUIXiaomiAccount"),
        ("cloudservice", "MIUICloudService"),
        ("cloudsync", "MIUIMiCloudSync"),
        ("simactivate", "XiaomiSimActivateServiceCn"),
        ("xmscore", "XmsCore"),
        ("xmsfkeeper", "XMSFKeeperAll"),
    ):
        copy_component(_source(config, key, inputs), product_app / dest, dest + ".apk")
    copy_component(_source(config, "findmy", inputs), product_app / "MIUIFindMy", "MIUIFindMy.apk")

    product_priv = ensure_dir(output_dir / "system" / "product" / "priv-app")
    copy_component(_source(config, "backup", inputs), product_priv / "Backup", "Backup.apk")
    copy_component(_source(config, "cloudbackup", inputs), product_priv / "MIUICloudBackup", "MIUICloudBackup.apk")
    copy_component(_source(config, "soundrecorder", inputs), product_priv / "MIUISoundRecorder", "MIUISoundRecorder.apk")
    libs = _source(config, "cloudbackup_libs", inputs) if config.get("source.cloudbackup_libs") else (Path(__file__).resolve().parents[1] / "assets" / "cloudbackup-libs")
    if not libs.is_dir():
        libs = Path(__file__).resolve().parents[1] / "assets" / "cloudbackup-libs"
    if libs.is_dir():
        copy_tree(libs, product_priv / "MIUICloudBackup" / "lib" / "arm64")

    product_permissions = ensure_dir(output_dir / "system" / "product" / "etc" / "permissions")
    for name in ("privapp-miui-gallery.xml", "privapp-miui-recorder.xml", "privapp-permissions-miui-cloud.xml"):
        copy_file(Path(__file__).resolve().parents[1] / "assets" / name, product_permissions / name)

    system_ext = ensure_dir(output_dir / "system" / "system_ext")
    copy_component(artifacts["rtmc"], system_ext / "priv-app" / "RtMiCloudSDK", "RtMiCloudSDK.apk")
    framework = ensure_dir(system_ext / "framework")
    copy_file(artifacts["miuisystem_jar"], framework / "MiuiSystemCls.jar")
    copy_file(_source(config, "rom_framework", inputs), framework / "rom-framework.jar")
    for name, relative in config.section("source.jars").items():
        copy_file(inputs / relative, framework / name)
    system_ext_permissions = ensure_dir(system_ext / "etc" / "permissions")
    for name in ("miui-system-lib.xml", "miui-gson.xml"):
        copy_file(Path(__file__).resolve().parents[1] / "assets" / name, system_ext_permissions / name)

    classpath = ensure_dir(output_dir / "system" / "etc" / "classpaths")
    copy_file(Path(__file__).resolve().parents[1] / "assets" / "bootclasspath.pb", classpath / "bootclasspath.pb")
    perms = ensure_dir(output_dir / "system" / "framework" / "MiuiPortPerms")
    copy_file(artifacts["perms"], perms / "MiuiPortPerms.apk")
    return output_dir


def package_module(output_dir: Path, output_zip: Path) -> dict:
    require_dir(output_dir, "module directory")
    ensure_dir(output_zip.parent)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(output_dir.rglob("*")):
            if not path.is_file():
                continue
            arcname = path.relative_to(output_dir).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, path.read_bytes())
    return {"path": str(output_zip), "size": output_zip.stat().st_size, "sha256": sha256_file(output_zip)}
