"""Synthetic allowlist checks only; no image/build/qualification is simulated."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from scripts.private_build_input import safe_proof
ROOT=Path(__file__).resolve().parents[1]
class SafeProofTests(unittest.TestCase):
 def inputs(self,root):
  d={'python_version':'3.14.7','pycolmap_version':'4.2.0','node_version':'v24.22.0','cuda_execution':'NOT_RUN','native_science_rebuilt':False,'private_fixed_seed0_equivalence':False,'base_image':'ghcr.io/bu5hm4nn/colmap-runtime@sha256:fc9e5c3ef7685da3e2d0d09cf6e2afe6e3e9d047b6d5fd2610cce9d3c9af2fe4','interface_probe_options':{'max_image_size':-1},'fusion_interface_probe':{'max_image_size':-1,'use_cache':True,'cache_size':1.0},'base_file_sha256':{k:'a'*64 for k in ('python/bin/python3.14','verify_runtime.py','runtime-lock.json')},'raw_log':'DO_NOT_EMIT_PRIVATE_PATH_OR_CAP','stereo_fusion_doc':'DO_NOT_EMIT_PRIVATE_PATH_OR_CAP'}
  paths=[root/name for name in ('doctor','expanded','published')];paths[0].write_text(json.dumps(d));paths[1].write_text('12345\n');paths[2].write_text(json.dumps({'containerimage.digest':'sha256:'+'b'*64,'private_context':'DO_NOT_EMIT_PRIVATE_PATH_OR_CAP'}));return d,paths
 def test_complete_allowlisted_result_does_not_forward_extra_fields(self):
  with tempfile.TemporaryDirectory() as temp:
   d,paths=self.inputs(Path(temp));out=safe_proof(*paths);encoded=json.dumps(out)
   self.assertNotIn('DO_NOT_EMIT',encoded);self.assertNotIn(temp,encoded);self.assertNotIn('python/bin',encoded);self.assertEqual(out['expanded_image_bytes'],12345);self.assertFalse(out['gpu_execution_validated']);self.assertEqual(out['status'],'cpu_api_passed')
 def test_cpu_evidence_before_publication_does_not_fabricate_published_digest(self):
  with tempfile.TemporaryDirectory() as tmp:
   d,paths=self.inputs(Path(tmp));out=safe_proof(paths[0],paths[1]);self.assertIsNone(out['published_digest']);self.assertEqual(out['status'],'cpu_api_passed')
 def test_corrected_carrier_is_not_mislabeled_as_original_payload_image(self):
  with tempfile.TemporaryDirectory() as temp:
   d,paths=self.inputs(Path(temp));d['native_payload_source_image']=d.pop('base_image');d['carrier_image_ref']='ghcr.io/uncloud-tech/colmap-runtime@sha256:'+'c'*64;paths[0].write_text(json.dumps(d));out=safe_proof(*paths)
   self.assertEqual(out['carrier_image_digest'],'sha256:'+'c'*64);self.assertNotEqual(out['carrier_image_digest'],out['native_payload_digest'])
 def test_bad_proof_fails_without_exception_text_paths_or_input_echo(self):
  with tempfile.TemporaryDirectory() as temp:
   d,paths=self.inputs(Path(temp));d['python_version']='DO_NOT_EMIT_PRIVATE_PATH_OR_CAP';paths[0].write_text(json.dumps(d))
   r=subprocess.run([sys.executable,str(ROOT/'scripts/private_build_input.py'),'proof',*map(str,paths)],capture_output=True,text=True)
   self.assertEqual(r.returncode,2);self.assertEqual(r.stderr,'');self.assertEqual(json.loads(r.stdout),{'stage':'proof','status':'failed','code':'SAFE_PROOF_REJECTED'});self.assertNotIn(temp,r.stdout)
 def test_size_and_digest_fail_closed(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);d,paths=self.inputs(root)
   for value in ('-1','abc','0',str(65*1024**3)):
    paths[1].write_text(value)
    with self.assertRaises(ValueError):safe_proof(*paths)
   paths[1].write_text('12345');paths[2].write_text('{"containerimage.digest":"PRIVATE_NOT_A_DIGEST"}')
   with self.assertRaises(ValueError):safe_proof(*paths)
