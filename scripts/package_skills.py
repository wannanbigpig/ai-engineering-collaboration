#!/usr/bin/env python3
"""Build deterministic, independently installable Skill ZIP files without publishing."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from bootstrap_project import BootstrapError, file_manifest, skill_directories
from validate_repository import check_packages


ROOT = Path(__file__).resolve().parents[1]
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def package_skills(root: Path, output: Path) -> dict:
    root = root.expanduser().resolve()
    output = output.expanduser().absolute()
    if output.is_symlink():
        raise ValueError("Output directory must not be a symbolic link")
    if output.resolve().is_relative_to(root / "skills"):
        raise ValueError("Output directory must be outside the source skills directory")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Output directory must be absent or empty: {output}")

    errors = check_packages(root)
    if errors:
        raise ValueError("Package validation failed:\n" + "\n".join(errors))
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    license_path = root / "LICENSE"
    if license_path.is_symlink() or not license_path.is_file():
        raise ValueError("The source repository must contain a regular LICENSE file")
    license_data = license_path.read_bytes()
    license_mode = stat.S_IMODE(license_path.stat().st_mode)

    # Read all distributable resources before creating output. The same manifest
    # rules govern bootstrap checks, copies, upgrades, and release packages.
    packages = []
    for skill in skill_directories(root):
        files = {}
        for name, identity in file_manifest(skill).items():
            mode, digest = identity.split(":", 1)
            data = (skill / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"Source changed while packaging: {skill / name}")
            files[name] = (data, int(mode, 8))
        license_name = "LICENSE.repository" if "LICENSE" in files else "LICENSE"
        if license_name in files and files[license_name][0] != license_data:
            raise ValueError(f"Cannot overwrite Skill resource with repository license: {skill / license_name}")
        if license_name not in files:
            files[license_name] = (license_data, license_mode)
        packages.append((skill.name, files))

    manifest = {"schema_version": 1, "version": version, "skills": []}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".skill-package-", dir=output.parent) as temporary:
        staging = Path(temporary)
        for name, files in packages:
            archive_name = f"{name}-{version}.zip"
            archive = staging / archive_name
            file_metadata = {}
            with ZipFile(archive, "w", compression=ZIP_STORED) as zipped:
                for relative in sorted(files):
                    data, mode = files[relative]
                    entry = ZipInfo(relative, date_time=ZIP_TIMESTAMP)
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFREG | mode) << 16
                    entry.compress_type = ZIP_STORED
                    zipped.writestr(entry, data)
                    file_metadata[relative] = {"sha256": hashlib.sha256(data).hexdigest(), "mode": f"{mode:04o}"}
            manifest["skills"].append({"name": name, "archive": archive_name,
                                       "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                       "files": file_metadata})
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        # rmdir refuses newly added contents, preserving another writer's files.
        if output.exists():
            output.rmdir()
        staging.rename(output)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Source repository containing VERSION, LICENSE, and skills/.")
    parser.add_argument("--output", type=Path, required=True, help="New or empty directory for Skill ZIP files and manifest.json.")
    args = parser.parse_args(argv)
    try:
        manifest = package_skills(args.root, args.output)
    except (BootstrapError, OSError, UnicodeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Packaged {len(manifest['skills'])} Skills at version {manifest['version']}: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
