"""Offline tools-overlay source/doctor seams, not image or CUDA execution proof."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / 'benchmark/public_cuda_tools/context'
spec = importlib.util.spec_from_file_location('tools_doctor', CONTEXT / 'verify_tools.py')
doctor = importlib.util.module_from_spec(spec); spec.loader.exec_module(doctor)

class PublicCudaToolsTests(unittest.TestCase):
    def test_context_is_only_generic_inspector_not_sdk_private_cli_or_secrets(self):
        self.assertEqual({p.name for p in CONTEXT.iterdir() if p.is_file()},
                         {'Dockerfile','acquire.py','verify_tools.py','cuobjdump-lock.json','LICENSE'})
        text = (CONTEXT/'Dockerfile').read_text()
        self.assertIn('FROM ${BASE} AS payload-base', text)
        self.assertIn('COPY --from=tools-builder /staged/ /', text)
        for forbidden in ('apt-get', 'pip install', 'npm', 'ENTRYPOINT', 'capability.json', 'source.git'):
            self.assertNotIn(forbidden, text)

    def test_live_verified_frozen_sdk_inspector_bytes_and_parent_are_locked(self):
        lock = json.loads((CONTEXT/'cuobjdump-lock.json').read_text())
        self.assertEqual(lock['version'], '12.8.90')
        self.assertEqual(lock['archive_bytes'],207644)
        self.assertEqual(lock['archive_sha256'],'dbf41355a0f7a8aa491c1839a6c6ff8df02cdb6c6eefd66360543616c1b4980f')
        self.assertTrue(lock['parent_image_ref'].endswith('5b222ede5467c4c7706956ceff034aa6e3f224658f7e1c81fefd5e743e9b333b'))
        self.assertEqual(lock['executable_bytes'],568992)
        self.assertEqual(lock['license_bytes'],63021)

    def probe(self, version='V12.8.90', arches='colmap.1.sm_86.cubin\ncolmap.2.sm_89.cubin', deps='libc.so.6 => /lib/libc.so.6'):
        with tempfile.TemporaryDirectory() as temp:
            binary=Path(temp)/'fixture-only';binary.write_bytes(b'OFFLINE TEST ONLY')
            lock={'version':'12.8.90','executable_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
            def run(argv, **kwargs):
                text = version if '--version' in argv else deps if argv[0]=='ldd' else arches
                return SimpleNamespace(stdout=text)
            return doctor.check_inspector(lock,binary=binary,runner=run)

    def test_version_load_and_actual_known_public_fatbin_checks_are_distinct(self):
        result=self.probe()
        self.assertEqual(result['known_public_architectures'],['86','89'])
        self.assertFalse(result['optimized_cli_baked_in_image'])
        self.assertTrue(result['optimized_cli_dual_arch_proof_required_at_artifact_and_launch'])

    def test_wrong_version_refused(self):
        with self.assertRaisesRegex(ValueError,'version'):self.probe(version='V12.9.90')

    def test_missing_required_fatbin_architecture_refused(self):
        with self.assertRaisesRegex(ValueError,'fatbin'):self.probe(arches='colmap.1.sm_89.cubin')

    def test_unresolved_inspector_dependency_refused(self):
        with self.assertRaisesRegex(ValueError,'closure'):self.probe(deps='libm.so.6 => not found')

if __name__ == '__main__': unittest.main()
