"""Export only image identity fields, never raw container-host metadata."""

import json
import sys


def public_metadata(images):
    if not isinstance(images, list) or len(images) != 1:
        raise ValueError("Exactly one image required")
    return {
        key: images[0][key]
        for key in ("Id", "Architecture", "Os", "Size", "RepoDigests")
    }


if __name__ == "__main__":
    print(json.dumps(public_metadata(json.load(sys.stdin)), indent=2))
