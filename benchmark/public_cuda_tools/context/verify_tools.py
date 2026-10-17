"""CPU proof of the tiny public inspector overlay, not a baked optimized CLI or GPU claim."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/opt/benchmark-tools/cuobjdump')


def check_inspector(lock, *, binary=Path('/usr/local/bin/cuobjdump'), runner=subprocess.run):
    if hashlib.sha256(binary.read_bytes()).hexdigest() != lock['executable_sha256']:
        raise ValueError('inspector binary digest mismatch')
    version = runner([str(binary), '--version'], check=True, capture_output=True, text=True, timeout=20)
    if not re.search(r'\bV' + re.escape(lock['version']) + r'\b', version.stdout):
        raise ValueError('inspector version mismatch')
    deps = runner(['ldd', str(binary)], check=True, capture_output=True, text=True, timeout=20)
    if 'not found' in deps.stdout:
        raise ValueError('inspector runtime closure unresolved')
    fatbin = runner([str(binary), '--list-elf', '/usr/local/bin/babelstream'],
                    check=True, capture_output=True, text=True, timeout=30)
    arches = sorted(set(re.findall(r'\.sm_([0-9]+)\.cubin', fatbin.stdout)))
    if not {'86', '89'}.issubset(arches):
        raise ValueError('known public BabelStream fatbin inspection failed')
    return {'version': lock['version'], 'binary_sha256': lock['executable_sha256'],
            'known_public_fatbin': 'BabelStream', 'known_public_architectures': arches,
            'closure_unresolved': False, 'optimized_cli_baked_in_image': False,
            'optimized_cli_dual_arch_proof_required_at_artifact_and_launch': True}


def main():
    legacy = subprocess.run([sys.executable, '/opt/benchmark-transport/verify_image.py'],
                            check=True, capture_output=True, text=True, timeout=60)
    proof = json.loads(legacy.stdout)
    lock = json.loads((ROOT / 'cuobjdump-lock.json').read_text())
    proof['cuobjdump'] = check_inspector(lock)
    proof['tools_parent_image_ref'] = (ROOT / 'parent-image-ref').read_text().strip()
    print(json.dumps(proof, sort_keys=True))


if __name__ == '__main__':
    main()
