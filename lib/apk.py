from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import zlib
import zipfile
from pathlib import Path

from .util import (
    PipelineError,
    copy_file,
    ensure_dir,
    log,
    require_file,
    run,
    sha1_file,
    zip_entry_crc,
)


def _zip_datetime() -> tuple[int, int, int, int, int, int]:
    return (2020, 1, 1, 0, 0, 0)


def extract_dex(apk: Path, output_dir: Path) -> list[Path]:
    ensure_dir(output_dir)
    result: list[Path] = []
    with zipfile.ZipFile(apk) as z:
        names = [n for n in z.namelist() if n.startswith("classes") and n.endswith(".dex")]
        if not names:
            raise PipelineError(f"no dex entries in {apk}")
        for name in names:
            out = output_dir / name
            out.write_bytes(z.read(name))
            result.append(out)
    return result


def fix_dex_header(data: bytearray) -> tuple[int, str]:
    data[0x0C:0x20] = hashlib.sha1(bytes(data[0x20:])).digest()
    checksum = zlib.adler32(bytes(data[0x0C:])) & 0xFFFFFFFF
    struct.pack_into("<I", data, 0x08, checksum)
    return checksum, data[0x0C:0x20].hex()


def patch_dex_bytes(data: bytes, offset: int, old_hex: str, new_hex: str) -> tuple[bytes, int, str]:
    buf = bytearray(data)
    old = bytes.fromhex(old_hex)
    new = bytes.fromhex(new_hex)
    if len(old) != len(new):
        raise PipelineError("dex patch old/new length mismatch")
    current = bytes(buf[offset:offset + len(old)])
    if current != old:
        raise PipelineError(f"dex patch mismatch at {offset:#x}: {current.hex()} != {old_hex}")
    buf[offset:offset + len(new)] = new
    checksum, sha1 = fix_dex_header(buf)
    return bytes(buf), checksum, sha1


def build_account_patch(config, account_apk: Path, output_zip: Path, output_json: Path) -> dict:
    require_file(account_apk, "account APK")
    expected_sha1 = str(config.get("account.apk_sha1", "")).lower()
    actual_sha1 = sha1_file(account_apk)
    if expected_sha1 and actual_sha1 != expected_sha1:
        raise PipelineError(f"account APK SHA1 mismatch: {actual_sha1} != {expected_sha1}")
    work = ensure_dir(output_zip.parent / "account")
    if work.exists():
        shutil.rmtree(work)
    ensure_dir(work)
    dex_files = extract_dex(account_apk, work)
    by_name = {p.name: p for p in dex_files}
    required = ["classes.dex", "classes2.dex"]
    for name in required:
        if name not in by_name:
            raise PipelineError(f"missing {name} in account APK")

    patched: dict[str, bytes] = {}
    metadata: dict[str, object] = {"stock_sha1": actual_sha1, "dex": {}}
    for name, offset, old_key, new_key in (
        ("classes.dex", int(config.get("account.classes1_patch_offset")), "account.classes1_old_hex", "account.classes1_new_hex"),
        ("classes2.dex", int(config.get("account.classes2_patch_offset")), "account.classes2_old_hex", "account.classes2_new_hex"),
    ):
        data, checksum, sha1 = patch_dex_bytes(by_name[name].read_bytes(), offset, str(config.get(old_key)), str(config.get(new_key)))
        patched[name] = data
        metadata["dex"][name] = {
            "adler32": f"{checksum:08x}",
            "sha1": sha1,
            "zip_crc": f"{zip_entry_crc(account_apk, name):08x}",
        }

    ensure_dir(output_zip.parent)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_STORED) as z:
        for name in required:
            info = zipfile.ZipInfo(name, date_time=_zip_datetime())
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, patched[name])
    metadata["output"] = str(output_zip)
    metadata["output_sha1"] = sha1_file(output_zip)
    output_json.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def build_dex_jar(source_apk: Path, output_jar: Path) -> Path:
    require_file(source_apk, "dex source APK")
    ensure_dir(output_jar.parent)
    with zipfile.ZipFile(source_apk) as zin, zipfile.ZipFile(output_jar, "w") as zout:
        dex_names = [n for n in zin.namelist() if n.startswith("classes") and n.endswith(".dex")]
        if not dex_names:
            raise PipelineError(f"no dex entries in {source_apk}")
        for name in dex_names:
            info = zipfile.ZipInfo(name, date_time=_zip_datetime())
            info.compress_type = zipfile.ZIP_STORED
            zout.writestr(info, zin.read(name))
    return output_jar


def build_java_dex_jar(
    *,
    source_dir: Path,
    output_jar: Path,
    work_dir: Path,
    build_tools: Path,
    android_jar: Path,
    java_home: str | None,
    classpath: Path | None = None,
    min_sdk: int = 29,
) -> Path:
    if not source_dir.is_dir():
        raise PipelineError(f"Java source directory not found: {source_dir}")
    java_files = sorted(source_dir.rglob("*.java"))
    if not java_files:
        raise PipelineError(f"no Java sources in {source_dir}")
    if not java_home:
        raise PipelineError("java_home is required to compile Java sources")
    javac = Path(java_home) / "bin" / "javac.exe"
    require_file(javac, "javac")

    if work_dir.exists():
        shutil.rmtree(work_dir)
    classes_dir = ensure_dir(work_dir / "classes")
    dex_dir = ensure_dir(work_dir / "dex")
    command = [
        str(javac),
        "-source",
        "8",
        "-target",
        "8",
        "-bootclasspath",
        str(android_jar),
    ]
    if classpath is not None:
        command.extend(["-classpath", str(classpath)])
    command.extend(["-d", str(classes_dir), *[str(path) for path in java_files]])
    _run_tool(command, java_home=java_home, label="javac")

    class_files = sorted(classes_dir.rglob("*.class"))
    if not class_files:
        raise PipelineError(f"javac produced no classes for {source_dir}")
    _run_tool(
        [
            str(build_tools / "d8.bat"),
            "--min-api",
            str(min_sdk),
            "--lib",
            str(android_jar),
            "--output",
            str(dex_dir),
            *[str(path) for path in class_files],
        ],
        java_home=java_home,
        label="d8",
    )
    classes_dex = dex_dir / "classes.dex"
    require_file(classes_dex, "generated classes.dex")
    ensure_dir(output_jar.parent)
    with zipfile.ZipFile(output_jar, "w") as zout:
        info = zipfile.ZipInfo("classes.dex", date_time=_zip_datetime())
        info.compress_type = zipfile.ZIP_STORED
        zout.writestr(info, classes_dex.read_bytes())
    return output_jar


def _parse_axml_strings(data: bytes) -> list[str]:
    _, _, _ = struct.unpack_from("<HHI", data, 8)
    count, _, flags, strings_start, _ = struct.unpack_from("<IIIII", data, 16)
    utf8 = bool(flags & 0x100)
    strings: list[str] = []
    offset = 8 + strings_start
    for _ in range(count):
        if not utf8:
            n = struct.unpack_from("<H", data, offset)[0]
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, offset + 2)[0]
                offset += 4
            else:
                offset += 2
            strings.append(data[offset:offset + n * 2].decode("utf-16-le", "replace"))
            offset += n * 2 + 2
        else:
            def read_len(pos: int) -> tuple[int, int]:
                a = data[pos]
                if a & 0x80:
                    return ((a & 0x7F) << 8) | data[pos + 1], pos + 2
                return a, pos + 1

            _, offset2 = read_len(offset)
            n, offset2 = read_len(offset2)
            strings.append(data[offset2:offset2 + n].decode("utf-8", "replace"))
            offset = offset2 + n + 1
    return strings


def strip_manifest_permissions(manifest: bytes, remove: set[str]) -> tuple[bytes, list[str]]:
    strings = _parse_axml_strings(manifest)
    string_index = {i: s for i, s in enumerate(strings)}
    name_permission = strings.index("permission")
    name_name = strings.index("name")
    offset = 8
    _, _, pool_size = struct.unpack_from("<HHI", manifest, offset)
    offset += pool_size
    chunk_type, _, chunk_size = struct.unpack_from("<HHI", manifest, offset)
    if chunk_type == 0x0180:
        offset += chunk_size
    chunks: list[tuple[int, int, int, int]] = []
    while offset < len(manifest):
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", manifest, offset)
        if chunk_size <= 0:
            raise PipelineError("invalid AXML chunk")
        chunks.append((offset, chunk_type, header_size, chunk_size))
        offset += chunk_size

    def start_info(element_offset: int, header_size: int):
        name, _ = struct.unpack_from("<II", manifest, element_offset + 20)
        fields = struct.unpack_from("<IIIIHHHHHH", manifest, element_offset + 8)
        attribute_start, attribute_size, attribute_count = fields[4:7]
        attrs = []
        base = element_offset + header_size + attribute_start
        for i in range(attribute_count):
            attr_offset = base + i * attribute_size
            _, attr_name, raw = struct.unpack_from("<III", manifest, attr_offset)
            _, _, value_type, value_data = struct.unpack_from("<HBBI", manifest, attr_offset + 12)
            attrs.append((attr_name, raw, value_type, value_data))
        return name, attrs

    deletions: list[tuple[int, int]] = []
    removed: list[str] = []
    for idx, (element_offset, chunk_type, header_size, chunk_size) in enumerate(chunks):
        if chunk_type != 0x0102:
            continue
        name, attrs = start_info(element_offset, header_size)
        if name != name_permission:
            continue
        permission_name = None
        for attr_name, raw, value_type, value_data in attrs:
            if attr_name == name_name and value_type == 0x03:
                permission_name = string_index.get(value_data) or string_index.get(raw)
        if permission_name not in remove:
            continue
        for end_offset, end_type, end_header, end_size in chunks[idx:]:
            if end_type == 0x0103:
                end_name = struct.unpack_from("<I", manifest, end_offset + 20)[0]
                if end_name == name_permission:
                    deletions.append((element_offset, chunk_size))
                    deletions.append((end_offset, end_size))
                    removed.append(permission_name)
                    break
    if set(removed) != remove:
        raise PipelineError(f"manifest permission removal mismatch: removed={removed}, wanted={sorted(remove)}")
    out = bytearray(manifest)
    for start, length in sorted(deletions, reverse=True):
        del out[start:start + length]
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out), removed


def _tool_env(java_home: str | None) -> dict[str, str] | None:
    if not java_home:
        return None
    env = {"JAVA_HOME": java_home}
    env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + os.environ.get("PATH", "")
    return env


def _run_tool(command: list[str], *, cwd: Path | None = None, java_home: str | None = None, label: str | None = None):
    return run(command, cwd=cwd, env=_tool_env(java_home), check=True, capture=True, label=label)


def zipalign(zipalign_exe: Path, input_apk: Path, output_apk: Path) -> None:
    _run_tool([str(zipalign_exe), "-f", "-p", "4", str(input_apk), str(output_apk)], label="zipalign")


def sign_apk(
    apksigner: Path,
    input_apk: Path,
    output_apk: Path,
    keystore: Path,
    alias: str,
    store_password: str,
    key_password: str,
    java_home: str | None = None,
) -> None:
    require_file(keystore, "keystore")
    _run_tool(
        [
            str(apksigner),
            "sign",
            "--ks",
            str(keystore),
            "--ks-key-alias",
            alias,
            "--ks-pass",
            f"pass:{store_password}",
            "--key-pass",
            f"pass:{key_password}",
            "--v1-signing-enabled",
            "true",
            "--v2-signing-enabled",
            "true",
            "--out",
            str(output_apk),
            str(input_apk),
        ],
        java_home=java_home,
        label="sign APK",
    )


def verify_apk(apksigner: Path, apk: Path, java_home: str | None = None) -> None:
    _run_tool([str(apksigner), "verify", str(apk)], java_home=java_home, label="verify APK")


def build_simple_apk(
    *,
    build_tools: Path,
    android_jar: Path,
    java_home: str | None,
    manifest: Path,
    source_dir: Path | None,
    output_apk: Path,
    work_dir: Path,
    keystore: Path,
    alias: str,
    store_password: str,
    key_password: str,
    min_sdk: int = 29,
    target_sdk: int = 35,
) -> Path:
    ensure_dir(work_dir)
    unsigned = work_dir / "unsigned.apk"
    linked = work_dir / "linked.apk"
    _run_tool(
        [
            str(build_tools / "aapt2.exe"),
            "link",
            "-o",
            str(linked),
            "--manifest",
            str(manifest),
            "-I",
            str(android_jar),
            "--min-sdk-version",
            str(min_sdk),
            "--target-sdk-version",
            str(target_sdk),
        ],
        java_home=java_home,
        label="aapt2 link",
    )
    classes: list[Path] = []
    if source_dir is not None:
        source_dir = require_file(source_dir, "Java source").parent if source_dir.is_file() else source_dir
        java_files = sorted(source_dir.rglob("*.java"))
        if java_files:
            if not java_home:
                raise PipelineError("java_home is required to compile Java sources")
            classes_dir = ensure_dir(work_dir / "classes")
            _run_tool(
                [
                    str(Path(java_home or os.environ.get("JAVA_HOME", "")) / "bin" / "javac.exe"),
                    "-source",
                    "8",
                    "-target",
                    "8",
                    "-bootclasspath",
                    str(android_jar),
                    "-d",
                    str(classes_dir),
                    *[str(p) for p in java_files],
                ],
                java_home=java_home,
                label="javac",
            )
            class_files = sorted(classes_dir.rglob("*.class"))
            dex_dir = ensure_dir(work_dir / "dex")
            _run_tool(
                [
                    str(build_tools / "d8.bat"),
                    "--min-api",
                    str(min_sdk),
                    "--lib",
                    str(android_jar),
                    "--output",
                    str(dex_dir),
                    *[str(p) for p in class_files],
                ],
                java_home=java_home,
                label="d8",
            )
            classes = [dex_dir / "classes.dex"]
            for p in classes:
                require_file(p, "generated classes.dex")
    with zipfile.ZipFile(linked) as zin, zipfile.ZipFile(unsigned, "w") as zout:
        for item in zin.infolist():
            info = zipfile.ZipInfo(item.filename, date_time=_zip_datetime())
            info.compress_type = item.compress_type
            zout.writestr(info, zin.read(item.filename))
        for p in classes:
            info = zipfile.ZipInfo("classes.dex", date_time=_zip_datetime())
            info.compress_type = zipfile.ZIP_STORED
            zout.writestr(info, p.read_bytes())
    aligned = work_dir / "aligned.apk"
    zipalign(build_tools / "zipalign.exe", unsigned, aligned)
    ensure_dir(output_apk.parent)
    sign_apk(
        build_tools / "apksigner.bat",
        aligned,
        output_apk,
        keystore,
        alias,
        store_password,
        key_password,
        java_home,
    )
    verify_apk(build_tools / "apksigner.bat", output_apk, java_home)
    return output_apk


def copy_rename(src: Path, dst: Path) -> Path:
    require_file(src)
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    return dst
