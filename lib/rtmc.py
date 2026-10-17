from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from . import apk, arsc
from .util import PipelineError, ensure_dir, log, require_file, run, sha256_file


def build_rtmc(
    *,
    rtmc_apk: Path,
    extres_apk: Path,
    miuisystem_apk: Path,
    output_apk: Path,
    work_dir: Path,
    build_tools: Path,
    android_jar: Path,
    java_home: str | None,
    keystore: Path,
    alias: str,
    store_password: str,
    key_password: str,
    get_sender_offset: int,
    get_sender_old_hex: str,
    get_sender_new_hex: str,
    metadata_path: Path,
) -> Path:
    require_file(rtmc_apk, "RtMiCloudSDK.apk")
    require_file(extres_apk, "framework-ext-res.apk")
    require_file(miuisystem_apk, "miuisystem.apk")
    ensure_dir(work_dir)
    with zipfile.ZipFile(rtmc_apk) as z:
        rtmc_arsc = z.read("resources.arsc")
        classes = z.read("classes.dex")
        stock_manifest = z.read("AndroidManifest.xml")
    with zipfile.ZipFile(extres_apk) as z:
        extres_arsc = z.read("resources.arsc")
    with zipfile.ZipFile(miuisystem_apk) as z:
        miuisys_arsc = z.read("resources.arsc")
        miuisys_classes = z.read("classes.dex")

    merged_arsc, stats = arsc.merge_apks(rtmc_arsc, extres_arsc, miuisys_arsc)
    manifest, removed = apk.strip_manifest_permissions(
        stock_manifest,
        {"com.xiaomi.permission.CLOUD_MANAGER", "com.miui.cloudservice.permission.FIND_DEVICE"},
    )
    patched_classes, checksum, sha1 = apk.patch_dex_bytes(
        classes,
        get_sender_offset,
        get_sender_old_hex,
        get_sender_new_hex,
    )

    unsigned = work_dir / "rtmc-unsigned.apk"
    with zipfile.ZipFile(rtmc_apk) as zin, zipfile.ZipFile(unsigned, "w") as zout:
        for item in zin.infolist():
            name = item.filename
            if name in {"resources.arsc", "AndroidManifest.xml", "classes.dex"}:
                continue
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = item.compress_type
            zout.writestr(info, zin.read(name))
        info = zipfile.ZipInfo("AndroidManifest.xml", date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        zout.writestr(info, manifest)
        info = zipfile.ZipInfo("resources.arsc", date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        zout.writestr(info, merged_arsc)
        info = zipfile.ZipInfo("classes.dex", date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        zout.writestr(info, patched_classes)
        info = zipfile.ZipInfo("classes2.dex", date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        zout.writestr(info, miuisys_classes)
        seen = set(zin.namelist())
        seen.update({"AndroidManifest.xml", "resources.arsc", "classes.dex", "classes2.dex"})
        for source in (extres_apk, miuisystem_apk):
            with zipfile.ZipFile(source) as src:
                for item in src.infolist():
                    name = item.filename
                    if not (name.startswith("res/") or name.startswith("assets/")) or name in seen:
                        continue
                    seen.add(name)
                    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = item.compress_type
                    zout.writestr(info, src.read(name))

    aligned = work_dir / "rtmc-aligned.apk"
    apk.zipalign(build_tools / "zipalign.exe", unsigned, aligned)
    ensure_dir(output_apk.parent)
    apk.sign_apk(
        build_tools / "apksigner.bat",
        aligned,
        output_apk,
        keystore,
        alias,
        store_password,
        key_password,
        java_home,
    )
    apk.verify_apk(build_tools / "apksigner.bat", output_apk, java_home)
    result = run(
        [str(build_tools / "aapt2.exe"), "dump", "resources", str(output_apk)],
        capture=True,
        quiet=True,
        check=False,
        label="aapt2 validate RtMiCloudSDK",
    )
    if result.returncode != 0:
        raise PipelineError("aapt2 could not parse merged RtMiCloudSDK resources")
    metadata = {
        "input_sha256": sha256_file(rtmc_apk),
        "stats": stats,
        "removed_permissions": removed,
        "classes_dex": {"adler32": f"{checksum:08x}", "sha1": sha1},
        "output": str(output_apk),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return output_apk
