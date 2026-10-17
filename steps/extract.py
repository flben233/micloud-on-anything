from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path

from lib import lpunpack, simg2img
from lib.erofs import Erofs
from lib.util import PipelineError, ensure_dir, log, require_file, run


PARTITIONS = {
    "product_a": [
        ("/app", "product/app"),
        ("/priv-app", "product/priv-app"),
        ("/data-app", "product/data-app"),
        ("/etc/permissions", "product/etc/permissions"),
        ("/etc/build.prop", "product/etc/build.prop"),
    ],
    "system_ext_a": [
        ("/priv-app/RtMiCloudSDK", "system_ext/priv-app/RtMiCloudSDK"),
        ("/app/miuisystem", "system_ext/app/miuisystem"),
        ("/framework", "system_ext/framework"),
        ("/etc/permissions", "system_ext/etc/permissions"),
        ("/etc/build.prop", "system_ext/etc/build.prop"),
    ],
    "system_a": [
        ("/system/framework/framework.jar", "system/framework.jar"),
        ("/system/etc/classpaths", "system/etc/classpaths"),
        ("/system/etc/permissions", "system/etc/permissions"),
        ("/system/build.prop", "system/system/build.prop"),
    ],
    "mi_ext_a": [
        ("/etc/build.prop", "mi_ext/etc/build.prop"),
        ("/product/etc/permissions", "mi_ext/product/etc/permissions"),
    ],
}


def extract_tgz(rom_tgz: Path, raw_dir: Path) -> dict[str, Path]:
    require_file(rom_tgz, "ROM tgz")
    ensure_dir(raw_dir)
    images: dict[str, Path] = {}
    log(f"reading {rom_tgz}")
    with tarfile.open(rom_tgz, "r:gz") as tf:
        for member in tf:
            if not member.isfile() or not member.name.lower().endswith(".img"):
                continue
            name = Path(member.name).name
            out = raw_dir / name
            if out.exists():
                log(f"  keep existing {name}")
                images[name] = out
                continue
            log(f"  extract {member.name} ({member.size} bytes)")
            src = tf.extractfile(member)
            if src is None:
                raise PipelineError(f"cannot read tar member {member.name}")
            with src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
            images[name] = out
    return images


def _maybe_unsparse(image: Path, out: Path) -> Path:
    with image.open("rb") as f:
        magic = f.read(4)
    if magic == b"\x3a\xff\x26\xed":
        log(f"unsparse {image.name}")
        simg2img.main(str(image), str(out))
        return out
    return image


def _write_inode(ero: Erofs, nid: int, out: Path) -> None:
    ino = ero.read_inode(nid)
    mode = ino["mode"]
    kind = mode & 0xF000
    if kind == 0x4000:
        ensure_dir(out)
        for name, child, _ in ero.listdir(nid):
            if name in (".", ".."):
                continue
            _write_inode(ero, child, out / name)
        try:
            os.chmod(out, mode & 0o777)
        except OSError:
            pass
        return
    data = ero.read_file_data(ino)
    ensure_dir(out.parent)
    if kind == 0xA000:
        try:
            os.symlink(data.decode("utf-8", "replace"), out)
            return
        except OSError:
            pass
    out.write_bytes(data)
    try:
        os.chmod(out, mode & 0o777)
    except OSError:
        pass


def extract_partition(image: Path, image_root: Path, output_root: Path, mappings: list[tuple[str, str]]) -> None:
    ero = Erofs(str(image))
    for source_path, target_path in mappings:
        try:
            nid = ero.walk(source_path)
        except FileNotFoundError:
            log(f"  skip missing {source_path} in {image.name}")
            continue
        destination = output_root / target_path
        log(f"  {source_path} -> {target_path}")
        _write_inode(ero, nid, destination)


def extract_rom(config, *, force: bool = False, partitions_only: bool = False, output: Path | None = None) -> Path:
    inputs = output or config.path("paths.inputs")
    if inputs.is_dir() and not force:
        required = inputs / "product" / "app" / "MIUIXiaomiAccount" / "MIUIXiaomiAccount.apk"
        if required.is_file():
            log(f"using existing extracted inputs: {inputs}")
            return inputs
    partitions_dir = ensure_dir(config.path("paths.partitions"))
    if not partitions_only:
        raw_dir = ensure_dir(config.path("paths.build_root") / "rom" / "raw")
        images = extract_tgz(config.path("paths.rom_tgz"), raw_dir)
        super_image = images.get("super.img")
        if super_image is None:
            raise PipelineError("super.img not found in ROM tgz")
        raw_super = raw_dir / "super.raw.img"
        super_image = _maybe_unsparse(super_image, raw_super)
        if not (partitions_dir / "product_a.img").is_file():
            log("unpacking super.img")
            lpunpack.main(str(super_image), str(partitions_dir))
    output_root = ensure_dir(inputs)
    for partition, mappings in PARTITIONS.items():
        image = partitions_dir / f"{partition}.img"
        if not image.is_file():
            log(f"missing partition {image.name}, skipping")
            continue
        log(f"extracting {partition}")
        extract_partition(image, output_root, output_root, mappings)
    return output_root
