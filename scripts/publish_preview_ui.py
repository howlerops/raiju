#!/usr/bin/env python3
"""Publish built UI into a running localhost preview without deleting old chunks."""
import argparse
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def publish_ui(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not (source / 'index.html').is_file():
        raise ValueError('Source must contain a built index.html')
    destination.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in source.rglob('*') if p.is_file() and p.name != 'index.html')
    # Assets first, document last. Existing hashed assets belong to open tabs.
    for path in [*files, source / 'index.html']:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        if target.exists() and target.name != 'index.html':
            if target.read_bytes() != data:
                raise ValueError(f'Immutable asset collision: {target.name}')
            continue
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as pending:
            temporary = Path(pending.name)
            try:
                pending.write(data)
                pending.flush()
                os.fsync(pending.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.chmod(0o644)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'web/dist')
    args = parser.parse_args()
    access = json.loads((ROOT / 'build/console-preview-access.json').read_text())
    target = Path(access.get('uiDir', '')).resolve()
    build = (ROOT / 'build').resolve()
    if target.parent.parent != build or not target.parent.name.startswith('console-preview-') or target.name != 'ui':
        parser.error('The running preview does not own a disposable UI snapshot')
    count = publish_ui(args.source, target)
    print(f'Published {count} assets; previous chunks retained for open tabs.')


if __name__ == '__main__':
    main()
