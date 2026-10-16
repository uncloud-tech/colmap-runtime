"""Synthetic runtime-copy and public-evidence seams, not a CVE clearance claim."""
import json,tempfile,unittest
from pathlib import Path
from scripts import private_build_input as helper
ROOT=Path(__file__).resolve().parents[1]
class PublicTransportEvidenceTests(unittest.TestCase):
 def test_final_stage_copies_node_binary_and_notice_not_npm_distribution(self):
  text=(ROOT/'benchmark/public_legacy_image/context/Dockerfile').read_text().split('FROM ${BASE} AS payload-base',1)[1]
  self.assertIn('COPY --from=transport-build /opt/benchmark-node/bin/node /opt/benchmark-node/bin/node',text)
  self.assertIn('COPY --from=transport-build /opt/benchmark-node/LICENSE /opt/benchmark-node/LICENSE',text)
  self.assertNotIn('COPY --from=transport-build /opt/benchmark-node /opt/benchmark-node',text)
 def test_high_findings_summary_only_emits_fixed_advisory_fields(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'report.json';path.write_text(json.dumps({'Results':[{'Vulnerabilities':[{'VulnerabilityID':'CVE-2099-12345','PkgName':'example-package','InstalledVersion':'1.0','FixedVersion':'1.1','Severity':'HIGH','Description':'DO_NOT_EMIT','Environment':'DO_NOT_EMIT'},{'Severity':'LOW','VulnerabilityID':'LOW_NOT_EMITTED'}]}],'arbitrary':'DO_NOT_EMIT'}))
   out=helper.security_summary(path);self.assertEqual(out['high_critical_findings'],[{'id':'CVE-2099-12345','package':'example-package','installed':'1.0','fixed':'1.1','severity':'HIGH'}]);self.assertNotIn('DO_NOT_EMIT',json.dumps(out));self.assertNotIn('LOW_NOT_EMITTED',json.dumps(out))
 def test_failure_retention_is_only_fixed_public_metadata_paths(self):
  text=(ROOT/'.github/workflows/build-dev.yml').read_text();block=text.split('      - name: Retain allowlisted public validation evidence even on failure\n',1)[1].split('      - name:',1)[0]
  self.assertIn("if: always() && inputs.private_stage == 'public-base'",block)
  self.assertIn('actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a',block)
  paths=[line.strip() for line in block.split('          path: |\n',1)[1].splitlines()]
  self.assertEqual(paths,['${{ runner.temp }}/public-vulnerabilities.json','${{ runner.temp }}/public-cpu-proof.json','${{ runner.temp }}/public-expanded-bytes','${{ runner.temp }}/public-oci-binding.json'])
  self.assertIn('python3 scripts/private_build_input.py security-summary',text)
  self.assertIn('python3 scripts/check_security.py "$RUNNER_TEMP/public-vulnerabilities.json"',text)
