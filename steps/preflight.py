from __future__ import annotations

import zipfile
from pathlib import Path

from lib import apk, rtmc
from lib.util import PipelineError, log, require_dir, require_file, sha1_file


def _source(config, key: str, inputs: Path) -> Path:
    value = config.get(f"source.{key}")
    if not value:
        raise PipelineError(f"missing source.{key}")
    return (inputs / value).resolve()


def preflight(config, inputs: Path, *, require_gallery: bool = True) -> dict:
    require_dir(inputs, "extracted ROM input")
    checks: dict[str, str] = {}
    for key in ("account", "cloudservice", "cloudsync", "simactivate", "xmscore", "xmsfkeeper", "findmy", "backup", "cloudbackup", "soundrecorder", "rtmc", "extres", "miuisystem", "rom_framework"):
        path = _source(config, key, inputs)
        require_file(path, key)
        checks[key] = str(path)
    for name, relative in config.section("source.jars").items():
        path = (inputs / relative).resolve()
        require_file(path, name)
        checks[name] = str(path)

    account = _source(config, "account", inputs)
    expected = str(config.get("account.apk_sha1", "")).lower()
    actual = sha1_file(account)
    if expected and actual != expected:
        raise PipelineError(f"account APK SHA1 mismatch: {actual} (expected {expected})")

    build_tools = config.path("tools.build_tools")
    for name in ("aapt2.exe", "zipalign.exe", "apksigner.bat", "d8.bat"):
        require_file(build_tools / name, name)
    android_jar = config.path("tools.android_jar")
    require_file(android_jar, "android.jar")
    java_home = Path(str(config.get("tools.java_home", "")))
    require_file(java_home / "bin" / "javac.exe", "javac")
    keystore = config.path("paths.keystore")
    require_file(keystore, "keystore")
    gallery = config.path("paths.gallery")
    if require_gallery:
        require_file(gallery, "gallery APK")
    adb = config.path("tools.adb")
    if adb and not adb.is_file():
        log(f"warning: adb not found at {adb}")

    with zipfile.ZipFile(_source(config, "rtmc", inputs)) as z:
        names = set(z.namelist())
        for needed in ("resources.arsc", "AndroidManifest.xml", "classes.dex"):
            if needed not in names:
                raise PipelineError(f"RtMiCloudSDK missing {needed}")
    with zipfile.ZipFile(_source(config, "miuisystem", inputs)) as z:
        if "classes.dex" not in z.namelist():
            raise PipelineError("miuisystem.apk missing classes.dex")

    log("preflight OK")
    log(f"  inputs: {inputs}")
    log(f"  account SHA1: {actual}")
    log(f"  build tools: {build_tools}")
    log(f"  module: {config.get('module.id')} {config.get('module.version')} ({config.get('module.version_code')})")
    return checks
