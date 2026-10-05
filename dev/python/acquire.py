"""Stage only the exact locked public bytes, preferring supplied verified caches."""

import argparse
import json
from pathlib import Path
import shutil
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from dev.python.locked_env import (
    load_lock,
    public_url,
    requirements_text,
    validate_archive,
    validate_wheel,
    verify_file,
)


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheelhouse-cache", type=Path)
    parser.add_argument("--interpreter-cache", type=Path)
    args = parser.parse_args()
    lock = load_lock(Path("dev/python/environment-lock.json"))
    args.output.mkdir(parents=True, exist_ok=True)
    if args.output.is_symlink():
        raise ValueError("staging directory is a symlink")
    opener = build_opener(PublicRedirects())
    licenses = []
    for row in lock["artifacts"] + lock["dependency_artifacts"]:
        name = urlsplit(row["uri"]).path.rsplit("/", 1)[-1]
        path = args.output / name
        cache = (
            args.wheelhouse_cache / name
            if args.wheelhouse_cache and name.endswith(".whl")
            else args.interpreter_cache
            if not name.endswith(".whl")
            else None
        )
        if path.exists() or path.is_symlink():
            verify_file(path, row)
        elif cache and cache.exists():
            verify_file(cache, row)
            shutil.copyfile(cache, path)
        else:
            temporary = path.with_suffix(path.suffix + ".partial")
            with (
                opener.open(public_url(row["uri"]), timeout=120) as source,
                temporary.open("xb") as target,
            ):
                remaining = row["size_bytes"] + 1
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    target.write(chunk)
                    remaining -= len(chunk)
            verify_file(temporary, row)
            temporary.rename(path)
        verify_file(path, row)
        if name.endswith(".whl"):
            licenses.append(validate_wheel(path, row))
        else:
            validate_archive(path)
        print("verified", name, row["sha256"])
    (args.output / "requirements.txt").write_text(requirements_text(lock))
    (args.output / "license-inventory.json").write_text(
        json.dumps(licenses, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
