"""Actual workflow ordering and cleanup filesystem seam; not a Docker-driver qualification."""
from pathlib import Path
import os,subprocess,tempfile,textwrap,unittest
ROOT=Path(__file__).resolve().parents[1]
class BuildxConfigLifecycleTests(unittest.TestCase):
 def workflow(self):return (ROOT/'.github/workflows/build-dev.yml').read_text().split('\n  specialization:\n',1)[1]
 def script(self,name):
  block=self.workflow().split('      - name: '+name+'\n',1)[1].split('      - name:',1)[0]
  lines=[]
  for line in block.split('        run: |\n',1)[1].splitlines(True):
   if line.strip() and not line.startswith('          '):break
   lines.append(line)
  return textwrap.dedent(''.join(lines))
 def test_config_is_established_before_buildx_state_is_created(self):
  s=self.workflow();self.assertLess(s.index('      - name: Private registry authentication'),s.index('      - uses: docker/setup-buildx-action@'))
  self.assertIn('echo "DOCKER_CONFIG=$DOCKER_CONFIG" >> "$GITHUB_ENV"',s)
 def test_actual_auth_and_cleanup_scripts_preserve_builder_state_not_auth(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);env={'PATH':os.environ['PATH'],'RUNNER_TEMP':tmp,'GITHUB_ENV':str(root/'env')}
   auth=self.script('Private registry authentication (no persisted checkout credentials)').replace('${{ runner.environment }}','self-hosted')
   # Run the real configuration script; exclude the external registry login.
   config_script=auth.split('printf \'%s\' "$REGISTRY_TOKEN" | docker login',1)[0]
   subprocess.run(['bash','-euo','pipefail','-c',config_script],env=env,check=True,capture_output=True)
   config=root/'registry-auth';(config/'config.json').write_text('{}')
   self.assertEqual((root/'env').read_text().strip(),'DOCKER_CONFIG='+str(config))
   state=config/'buildx/instances/synthetic';state.parent.mkdir(parents=True);state.write_text('synthetic builder state')
   private=root/'private-context';private.mkdir();(private/'input').write_text('synthetic')
   subprocess.run(['bash','-euo','pipefail','-c',self.script('Remove ephemeral sensitive workspace and registry auth')],env=env,check=True,capture_output=True)
   self.assertTrue(state.exists(),'cleanup must leave buildx state for native post-action')
   self.assertFalse((config/'config.json').exists());self.assertFalse(private.exists())
