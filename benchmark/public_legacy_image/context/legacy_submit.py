"""Stdlib-only, delivery-only raw legacy sender. Never executes native work.

Optional --spool freezes bundle.json before delivery. Reuse with identical inputs
only; changed inputs refuse rather than overwrite. No automatic delivery retries.
"""
import argparse
import base64
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import secrets

MAX = 8 * 1024 * 1024
FORMAT = 'legacy-vast-benchmark-files-v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def safe_read(path, maximum):
    # O_NONBLOCK prevents a malicious FIFO from hanging before fstat.
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('parent traversal refused')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ValueError('unsafe input file or size')
        chunks = []
        size = 0
        while True:
            chunk = os.read(fd, min(65536, maximum - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                raise ValueError('input byte limit')
            chunks.append(chunk)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('input changed while reading')
        return b''.join(chunks)
    finally:
        os.close(fd)


def object_report(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate report field')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('nonfinite report constant')
    if not isinstance(json.loads(data, object_pairs_hook=pairs, parse_constant=invalid), dict):
        raise ValueError('report must be a JSON object')


def build_payload(run_id, job_id, image_digest, native_exit_code, report_file=None, native_log=None):
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}', run_id) or not isinstance(job_id,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',job_id):
        raise ValueError('legacy scope')
    if not re.fullmatch('sha256:[a-f0-9]{64}', image_digest):
        raise ValueError('actual image digest required')
    if type(native_exit_code) is not int or not -2147483648 <= native_exit_code <= 2147483647:
        raise ValueError('native exit code')
    files = []
    decoded = 0
    for name, path, maximum in [('report.json', report_file, 2 * MAX), ('native.log', native_log, 16000000)]:
        if path is None:
            continue
        try:
            data = safe_read(path, maximum)
        except FileNotFoundError:
            # A failed native invocation may genuinely have produced no report.
            # A dangling symlink is not an absent native report.
            if name == 'report.json' and native_exit_code != 0 and not Path(path).is_symlink():
                continue
            raise
        decoded += len(data)
        if decoded > 2 * MAX:
            raise ValueError('decoded byte limit; explicitly omit optional log')
        if name == 'report.json':
            object_report(data)
        files.append(dict(name=name, encoding='gzip+base64', sha256=hashlib.sha256(data).hexdigest(),
                          data=base64.b64encode(gzip.compress(data, mtime=0)).decode('ascii')))
    if native_exit_code == 0 and not any(f['name'] == 'report.json' for f in files):
        raise ValueError('successful native report required')
    payload = canonical(dict(transport_version=2, result_format=FORMAT, run_id=run_id, job_id=job_id,
                             image_digest=image_digest, native_exit_code=native_exit_code, files=files))
    if len(payload) > MAX:
        raise ValueError('wire byte limit; explicitly omit optional log')
    key = hashlib.sha256(canonical([FORMAT, run_id, job_id])).hexdigest()
    return key, payload


def freeze(payload, spool):
    spool = Path(spool).absolute()
    if '..' in spool.parts:
        raise ValueError('parent traversal refused')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in spool.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        try:
            os.mkdir(spool.name, mode=0o700, dir_fd=directory)
        except FileExistsError:
            pass
        os.fsync(directory)
        child = os.open(spool.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        os.close(directory)
        directory = child
        st = os.fstat(directory)
        if st.st_uid != os.geteuid() or st.st_mode & 0o077:
            raise ValueError('private spool required')
        # A killed sender can leave only this bounded temporary file. No automatic
        # cleanup of pre-existing files; interrupted spools require local review.
        temporary = '.bundle-' + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(temporary, 'bundle.json', src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary, dir_fd=directory)
        fd = os.open('bundle.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX or f.read(MAX + 1) != payload:
                raise ValueError('frozen bundle conflicts with inputs')
        os.fsync(directory)
    finally:
        os.close(directory)


def submit(capability_file, key, payload, timeout):
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError('timeout must be in (0,30] seconds')
    node = shutil.which('node')
    if not node:
        raise ValueError('qualified Node runtime absent')
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'BENCH_HOLEPUNCH_DEPS', 'PHOTOGRAM_PROCESS_OWNER')}
    # Only a capability FILE path reaches argv. Python never reads the secret.
    result = subprocess.run([node, str(Path(__file__).with_name('submit.ts')), os.path.abspath(capability_file),
                             str(max(1, int(timeout * 1000))), key], input=payload, capture_output=True,
                            timeout=timeout, env=env)
    if result.returncode or len(result.stdout) > 4096:
        raise OSError('delivery failed; native outcome unchanged')
    ack = json.loads(result.stdout)
    if not isinstance(ack, dict) or ack.get('durable') is not True or ack.get('key') != key or ack.get('content_sha256') != hashlib.sha256(payload).hexdigest() or type(ack.get('duplicate')) is not bool:
        raise ValueError('invalid durable ACK binding')
    return ack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capability-file', required=True)
    parser.add_argument('--report-file')
    parser.add_argument('--native-log')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--image-digest', required=True)
    parser.add_argument('--native-exit-code', required=True, type=int)
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--spool')
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 30:
        raise ValueError('timeout must be in (0,30] seconds')
    key, payload = build_payload(args.run_id, args.job_id, args.image_digest, args.native_exit_code, args.report_file, args.native_log)
    if args.spool:
        freeze(payload, args.spool)
    ack = submit(args.capability_file, key, payload, args.timeout)
    # Delivery success never replaces the actual native exit code.
    print(json.dumps(dict(delivery='delivered', native_exit_code=args.native_exit_code, **ack)))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never echo paths, raw native data, capability material or child stderr.
        print('legacy delivery refused; native outcome unchanged', file=sys.stderr)
        sys.exit(20)
