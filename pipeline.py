from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from lib.config import load_config
from lib.module import package_module, write_module_prop
from lib.util import PipelineError, ensure_dir, log
from steps.build import build
from steps.extract import extract_rom
from steps.preflight import preflight
from steps.verify import verify


def _inputs(config, value: str | None) -> Path:
    if value:
        return Path(value).resolve()
    return config.path("paths.inputs")


def _build_root(config) -> Path:
    return config.path("paths.build_root")


def _apply_version(config, version: str | None, version_code: int | None) -> None:
    if version:
        config.data["module"]["version"] = version
    if version_code is not None:
        config.data["module"]["version_code"] = version_code


def _package(config, module_dir: Path, output: Path | None = None) -> dict:
    target = output or (_build_root(config) / "MiCloudPort.zip")
    result = package_module(module_dir, target)
    releases = config.path("paths.releases")
    ensure_dir(releases)
    release_name = f"MiCloudPort-{config.get('module.version')}.zip"
    release = releases / release_name
    shutil.copy2(target, release)
    result["release"] = str(release)
    log(f"package: {target} ({result['size']} bytes)")
    log(f"release: {release}")
    log(f"sha256: {result['sha256']}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.py", description="Build and verify the Xiaomi Cloud Port module")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--inputs", default=None, help="extracted ROM input directory")
    parser.add_argument("--partitions", default=None, help="partition image directory")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preflight")
    p.add_argument("--no-gallery", action="store_true")

    p = sub.add_parser("extract")
    p.add_argument("--force", action="store_true")
    p.add_argument("--partitions-only", action="store_true")

    p = sub.add_parser("build")
    p.add_argument("--skip-gallery", action="store_true")
    p.add_argument("--version")
    p.add_argument("--version-code", type=int)
    p.add_argument("--no-package", action="store_true")

    p = sub.add_parser("package")
    p.add_argument("--module-dir", type=Path, default=None)
    p.add_argument("--output", type=Path, default=None)

    p = sub.add_parser("verify")
    p.add_argument("--zip", type=Path, default=None)
    p.add_argument("--install", action="store_true")
    p.add_argument("--no-start", action="store_true")

    p = sub.add_parser("all")
    p.add_argument("--skip-gallery", action="store_true")
    p.add_argument("--skip-emulator", action="store_true")
    p.add_argument("--install", action="store_true")

    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.partitions:
            config.data.setdefault("paths", {})["partitions"] = args.partitions
        inputs = _inputs(config, args.inputs)
        build_root = _build_root(config)
        _apply_version(config, getattr(args, "version", None), getattr(args, "version_code", None))

        if args.command == "preflight":
            preflight(config, inputs, require_gallery=not args.no_gallery)
            return 0

        if args.command == "extract":
            result = extract_rom(config, force=args.force, partitions_only=args.partitions_only, output=inputs)
            log(f"extracted inputs: {result}")
            return 0

        if args.command == "build":
            result = build(
                config,
                inputs,
                build_root,
                skip_gallery=args.skip_gallery,
                version=args.version,
                version_code=args.version_code,
            )
            if not args.no_package:
                _package(config, Path(result["module_dir"]))
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "package":
            module_dir = args.module_dir or (build_root / "module" / "MiCloudPort")
            _package(config, Path(module_dir), args.output)
            return 0

        if args.command == "verify":
            result = verify(config, args.zip, install=args.install, start=not args.no_start)
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "all":
            preflight(config, inputs, require_gallery=not args.skip_gallery)
            result = build(config, inputs, build_root, skip_gallery=args.skip_gallery)
            packaged = _package(config, Path(result["module_dir"]))
            if not args.skip_emulator:
                verify(config, Path(packaged["path"]), install=args.install, start=True)
            print(json.dumps(packaged, indent=2))
            return 0
        raise PipelineError(f"unknown command: {args.command}")
    except PipelineError as exc:
        log(f"ERROR: {exc}")
        return 2
    except KeyboardInterrupt:
        log("interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
