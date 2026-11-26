#!/usr/bin/env python3
"""Build the market-release ZIP for sakuramedia_javranking.

Usage:
    python build.py [output.zip]

- Reads the version from manifest.json and defaults the output name to
  sakuramedia_javranking-<version>.zip next to this script's repo root.
- The ZIP root contains exactly: manifest.json, __init__.py, plugin.py, source.py.
- Prints the SHA-256 of the produced archive.
- Refuses to overwrite an existing archive (delete it yourself first).
"""
import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / 'sakuramedia_javranking'
MEMBERS = ('manifest.json', '__init__.py', 'plugin.py', 'source.py')


def main() -> int:
    import json

    manifest = json.loads((PACKAGE / 'manifest.json').read_text('utf-8'))
    version = manifest['version']
    default_out = REPO / 'dist' / f'sakuramedia_javranking-{version}.zip'
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_out
    if target.exists():
        print(f'refusing to overwrite existing archive: {target}', file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in MEMBERS:
            source = PACKAGE / name
            if not source.is_file():
                print(f'missing package member: {source}', file=sys.stderr)
                return 1
            archive.write(source, name)
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        if names != list(MEMBERS):
            print(f'unexpected archive layout: {names}', file=sys.stderr)
            return 1
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f'{digest}  {target.name}')
    print(f'wrote {target} ({target.stat().st_size} bytes)')
    (target.parent / f'{target.name}.sha256').write_text(f'{digest}  {target.name}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
