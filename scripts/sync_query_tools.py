#!/usr/bin/env python3
"""Check or regenerate independent query tools from the maintenance Skill's source."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CONSUMERS = ('ai-engineering-collaboration', 'code-review', 'systematic-debugging', 'change-impact-analysis')
RESOURCES = ('scripts/query_aitasks.py', 'assets/search-aliases.json')


def query_tool_copies(root: Path) -> dict[Path, Path]:
    owner = root / 'skills/aitasks-maintenance'
    return {root / 'skills' / name / resource: owner / resource
            for name in CONSUMERS if (root / 'skills' / name).is_dir() for resource in RESOURCES}


def check_query_tools(root: Path) -> list[str]:
    # Standalone packages may omit the maintenance Skill; only the source
    # repository can compare generated resources to their authoritative owner.
    if not (root / 'skills/aitasks-maintenance').is_dir():
        return []
    errors = []
    for target, source in query_tool_copies(root).items():
        try:
            if source.is_symlink() or target.is_symlink() or not source.is_file() or not target.is_file():
                raise ValueError('expected regular source and generated files')
            if (target.read_bytes() != source.read_bytes()
                    or stat.S_IMODE(target.stat().st_mode) != stat.S_IMODE(source.stat().st_mode)):
                raise ValueError('generated content or permissions differ')
        except (OSError, ValueError) as error:
            errors.append(f'{target}: {error}; run scripts/sync_query_tools.py --write')
    return errors


def sync_query_tools(root: Path) -> None:
    copies = query_tool_copies(root)
    sources = {}
    for source in set(copies.values()):
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'Expected a regular query source: {source}')
        sources[source] = (source.read_bytes(), stat.S_IMODE(source.stat().st_mode))
    # Refuse redirected generated paths before writing any resource.
    for target in copies:
        current = target
        while current != root:
            if current.is_symlink():
                raise ValueError(f'Generated resource must not use symbolic links: {target}')
            current = current.parent
        if target.exists() and not target.is_file():
            raise ValueError(f'Expected a generated file: {target}')
    for target, source in copies.items():
        data, mode = sources[source]
        if target.is_file() and target.read_bytes() == data and stat.S_IMODE(target.stat().st_mode) == mode:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f'.{target.name}.', dir=target.parent)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                os.fchmod(handle.fileno(), mode)
                handle.write(data)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if not (root / 'skills/aitasks-maintenance/SKILL.md').is_file():
            raise ValueError('The source repository must contain aitasks-maintenance')
        if args.write:
            sync_query_tools(root)
        errors = check_query_tools(root)
        if errors:
            raise ValueError('\n'.join(errors))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print('Independent query tools match their authoritative source')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
