from __future__ import annotations

import re
import time
from pathlib import Path

from lib.util import PipelineError, log, require_file, run


def adb(config, *args: str, check: bool = True) -> str:
    executable = config.path("tools.adb")
    result = run([str(executable), *args], capture=True, check=check, quiet=True)
    return (result.stdout or "") + (result.stderr or "")


def wait_boot(config, timeout: int = 240) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = adb(config, "shell", "getprop", "sys.boot_completed", check=False).strip()
        if value == "1":
            return
        time.sleep(3)
    raise PipelineError("emulator did not boot")


def wait_ce(config, timeout: int = 240) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = adb(config, "shell", "getprop", "sys.user.0.ce_available", check=False).strip()
        if value == "true":
            return
        time.sleep(3)
    raise PipelineError("user 0 CE storage did not unlock")


def require_package(config, package: str) -> bool:
    result = adb(config, "shell", "pm", "path", package, check=False)
    return "package:" in result


def verify(config, zip_path: Path | None = None, install: bool = False, start: bool = True) -> dict:
    if zip_path is not None:
        require_file(zip_path, "module zip")
    adb(config, "root", check=False)
    adb(config, "remount", check=False)
    wait_boot(config)
    adb(config, "shell", "sh", str(config.get("tools.live_setup")), check=False)
    wait_boot(config)
    wait_ce(config)
    time.sleep(10)

    if zip_path is not None and install:
        adb(config, "push", str(zip_path), "/data/local/tmp/MiCloudPort.zip")
        adb(config, "shell", "magisk", "--install-module", "/data/local/tmp/MiCloudPort.zip", check=False)
        log("module installed; reboot is required before app verification")

    if start:
        adb(config, "shell", "am", "start", "-W", "-n", str(config.get("verify.cloudbackup_activity")), check=False)
        time.sleep(8)

    cloudid = adb(
        config,
        "shell",
        "content",
        "call",
        "--uri",
        str(config.get("verify.cloudid_authority")),
        "--method",
        "getCloudId",
        check=False,
    )
    if "result_id" not in cloudid:
        raise PipelineError(f"CloudIdProvider call failed: {cloudid.strip()}")

    package = str(config.get("gallery.package"))
    gallery = adb(config, "shell", "dumpsys", "package", package, check=False)
    version = re.search(r"versionCode=(\d+)", gallery)
    gallery_code = version.group(1) if version else ""

    log_path = str(config.get("verify.log_path"))
    service_log = adb(config, "shell", "tail", "-n", "120", log_path, check=False)
    forbidden = [line for line in service_log.splitlines() if "Unknown authority" in line or "IllegalDeviceException" in line]
    if forbidden:
        raise PipelineError("cloudbackup device-id error still present in log:\n" + "\n".join(forbidden[-5:]))

    crash = adb(config, "shell", "logcat", "-b", "crash", "-d", check=False)
    cloudbackup_crash = [line for line in crash.splitlines() if "com.miui.cloudbackup" in line]
    if cloudbackup_crash:
        raise PipelineError("cloudbackup crashed:\n" + "\n".join(cloudbackup_crash[-10:]))

    result = {
        "cloudid": cloudid.strip(),
        "gallery_version": gallery_code,
        "cloudbackup_running": "com.miui.cloudbackup" in adb(config, "shell", "pidof", "com.miui.cloudbackup", check=False),
        "service_log_tail": service_log.strip().splitlines()[-5:] if service_log.strip() else [],
        "crash_cloudbackup": bool(cloudbackup_crash),
    }
    log("verify OK")
    log(f"  cloudid: {result['cloudid']}")
    log(f"  gallery versionCode: {gallery_code}")
    return result
