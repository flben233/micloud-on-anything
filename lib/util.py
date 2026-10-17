from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PipelineError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_path(value: str | Path, base: Path = PROJECT_ROOT) -> Path:
    p = Path(value)
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def require_file(path: Path, label: str = "file") -> Path:
    if not path.is_file():
        raise PipelineError(f"missing {label}: {path}")
    return path


def require_dir(path: Path, label: str = "directory") -> Path:
    if not path.is_dir():
        raise PipelineError(f"missing {label}: {path}")
    return path


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture: bool = False,
    quiet: bool = False,
    label: str | None = None,
) -> subprocess.CompletedProcess:
    if label:
        log(f"[run] {label}")
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    log("  " + " ".join(str(x) for x in command))
    result = subprocess.run(
        [str(x) for x in command],
        cwd=str(cwd) if cwd else None,
        env=full_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )
    if capture and not quiet:
        if result.stdout:
            log(result.stdout.rstrip())
        if result.stderr:
            log(result.stderr.rstrip())
    if check and result.returncode != 0:
        raise PipelineError(f"command failed ({result.returncode}): {' '.join(str(x) for x in command)}")
    return result


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(block_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha1_file(path: Path, block_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(block_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def crc32_file(path: Path) -> int:
    import zlib

    value = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            value = zlib.crc32(chunk, value)
    return value & 0xFFFFFFFF


def zip_entry_crc(path: Path, entry: str) -> int:
    with zipfile.ZipFile(path) as z:
        info = z.getinfo(entry)
        return info.CRC & 0xFFFFFFFF


def copy_file(src: Path, dst: Path) -> Path:
    require_file(src)
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    return dst


def copy_tree(src: Path, dst: Path) -> None:
    require_dir(src)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def list_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def replace_text(path: Path, replacements: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8", newline="\n")


def read_prop(path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    if not path.is_file():
        return props
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


def prop_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def python_exe() -> str:
    return sys.executable


def command_path(value: str | Path) -> str:
    p = Path(value)
    if p.is_absolute():
        return str(p)
    return str(p)


def find_first(root: Path, patterns: list[str], label: str) -> Path:
    for pattern in patterns:
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0]
    raise PipelineError(f"cannot find {label} under {root}: {patterns}")


def is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def device_log_line(message: str) -> None:
    log(f"[device] {message}")


def parse_version_code(dumpsys_text: str) -> str:
    m = re.search(r"versionCode=(\d+)", dumpsys_text)
    return m.group(1) if m else ""
