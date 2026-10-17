"""Fetch one official frozen CUDA inspector; extract selected bytes, never install SDK packages."""
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import urllib.request


def stage(inputs, output, base):
    inputs, output = Path(inputs), Path(output)
    lock = json.loads((inputs / 'cuobjdump-lock.json').read_text())
    if base != lock['parent_image_ref'] or not re.fullmatch(r'ghcr\.io/uncloud-tech/[a-z0-9-]+@sha256:[0-9a-f]{64}', base):
        raise ValueError('immutable approved public parent required')
    with urllib.request.urlopen(lock['archive_url'], timeout=30) as response:
        raw = response.read(lock['archive_bytes'] + 1)
    if len(raw) != lock['archive_bytes'] or hashlib.sha256(raw).hexdigest() != lock['archive_sha256']:
        raise ValueError('official inspector archive identity mismatch')
    notice = output / 'opt/benchmark-tools/cuobjdump'
    notice.mkdir(parents=True)
    executable = output / 'usr/local/bin/cuobjdump'
    executable.parent.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as archive:
        for suffix, target, size, expected, mode in (
            ('/bin/cuobjdump', executable, lock['executable_bytes'], lock['executable_sha256'], 0o755),
            ('/LICENSE', notice / 'NVIDIA-LICENSE', lock['license_bytes'], lock['license_sha256'], 0o644),
        ):
            entries = [member for member in archive if member.name.endswith(suffix)]
            if len(entries) != 1 or not entries[0].isfile() or entries[0].size != size:
                raise ValueError('selected inspector/notice archive member mismatch')
            data = archive.extractfile(entries[0]).read(size + 1)
            if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('selected inspector/notice byte identity mismatch')
            target.write_bytes(data); target.chmod(mode)
    shutil.copyfile(inputs / 'verify_tools.py', notice / 'verify_tools.py')
    shutil.copyfile(inputs / 'LICENSE', notice / 'PROJECT-LICENSE')
    shutil.copyfile(inputs / 'cuobjdump-lock.json', notice / 'cuobjdump-lock.json')
    (notice / 'parent-image-ref').write_text(base + '\n')


if __name__ == '__main__':
    stage(*sys.argv[1:])
