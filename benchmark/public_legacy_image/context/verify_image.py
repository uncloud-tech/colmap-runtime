"""CPU-only actual legacy image/transport API check. Never runs CUDA/MVS/DHT."""
import hashlib,importlib.util,json,pathlib,re,subprocess,sys
BASE='ghcr.io/bu5hm4nn/colmap-runtime@sha256:fc9e5c3ef7685da3e2d0d09cf6e2afe6e3e9d047b6d5fd2610cce9d3c9af2fe4'
ROOT=pathlib.Path('/opt/colmap-runtime')
EXPECTED={'python/bin/python3.14':'5a91882290532b2719eaca77c0f3a7448bd73b9214e56df57bc59004560a80c6','verify_runtime.py':'17b2e81595b3382b660865d93ad5eb1fbfa88bb1ca97a7db94a39d4dcb88ed99','runtime-lock.json':'9690c6a95693a38d96171e292f45b74fdd26873bb6d8422b588f5206fd6beedf'}
OPTIONS={'max_image_size':-1,'gpu_index':'0','window_radius':5,'window_step':1,'num_samples':15,'num_iterations':5,'cache_size':1.0,'num_threads':-1,'depth_min':-1.0,'depth_max':-1.0,'geom_consistency':True,'filter':True,'write_consistency_graph':False,'allow_missing_files':False,'min_triangulation_angle':1.0,'sigma_spatial':-1.0,'sigma_color':0.2,'ncc_sigma':0.6,'incident_angle_sigma':0.9,'geom_consistency_regularizer':0.3,'geom_consistency_max_cost':3.0,'filter_min_ncc':0.1,'filter_min_triangulation_angle':3.0,'filter_min_num_consistent':2,'filter_geom_consistency_max_cost':1.0}

def main():
 carrier=(pathlib.Path(__file__).parent/'carrier-image-ref').read_text().strip()
 if not re.fullmatch(r'ghcr\.io/uncloud-tech/colmap-runtime@sha256:[a-f0-9]{64}',carrier):raise ValueError('inspected key-free carrier identity required')
 hashes={}
 for name,expected in EXPECTED.items():
  actual=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
  if actual!=expected:raise ValueError('legacy base identity changed')
  hashes[name]=actual
 subprocess.run([sys.executable,str(ROOT/'verify_runtime.py'),'--mode','cpu','--require-installer-free','--output','/tmp/legacy-runtime-check.json'],check=True,stdout=subprocess.DEVNULL,timeout=60)
 import pycolmap
 if not str(pycolmap.__version__).startswith('4.2.'):raise ValueError('expected legacy PyCOLMAP4.2')
 options=pycolmap.PatchMatchOptions()
 pm_defaults={key:getattr(options,key) for key in OPTIONS}
 for key,value in OPTIONS.items():setattr(options,key,value)
 if hasattr(options,'random_seed'):raise ValueError('unexpected stereo seed interface; do not invent equivalence')
 if options.check() is False:raise ValueError('legacy MVS options refused')
 fusion=pycolmap.StereoFusionOptions()
 fusion_defaults={key:getattr(fusion,key) for key in ('max_image_size','min_num_pixels','max_num_pixels','max_traversal_depth','max_reproj_error','max_depth_error','max_normal_error','check_num_images','use_cache','cache_size','num_threads')}
 fusion_defaults['mask_path']=str(fusion.mask_path)
 fusion_defaults['bounding_box']=[list(map(float,corner)) for corner in fusion.bounding_box]
 fusion.max_image_size=-1;fusion.use_cache=True;fusion.cache_size=1.0
 if fusion.check() is False:raise ValueError('fusion resource options refused')
 if not callable(pycolmap.stereo_fusion):raise ValueError('legacy fusion API unavailable')
 pycolmap.set_random_seed(0) # HOST PRNG only, never claim GPU fixed-seed equivalence.
 node='/opt/benchmark-node/bin/node';version=subprocess.check_output([node,'--version'],text=True,timeout=5).strip()
 if version!='v24.22.0':raise ValueError('Node identity')
 subprocess.run([node,'-e','require("/opt/benchmark-transport/node_modules/hyperswarm")'],check=True,timeout=5)
 spec=importlib.util.spec_from_file_location('legacy_sender','/opt/benchmark-transport/legacy_submit.py');sender=importlib.util.module_from_spec(spec);spec.loader.exec_module(sender)
 _,wire=sender.build_payload('cpu-check','eth3d-facade-fullres-quality',BASE.split('@')[1],7)
 if json.loads(wire)['transport_version']!=2:raise ValueError('legacy raw-results ABI')
 source_builds=json.loads((ROOT/'runtime-lock.json').read_bytes()).get('source_builds',[])
 print(json.dumps({'native_payload_source_image':BASE,'carrier_image_ref':carrier,'base_file_sha256':hashes,'native_source_builds':source_builds,'python_version':sys.version.split()[0],'pycolmap_version':pycolmap.__version__,'node_version':version,'interface_probe_options':OPTIONS,'patchmatch_interface_defaults':pm_defaults,'fusion_interface_defaults':fusion_defaults,'fusion_interface_probe':{'max_image_size':-1,'use_cache':True,'cache_size':1.0},'stereo_fusion_doc':pycolmap.stereo_fusion.__doc__,'fusion_executed':False,'host_prng_seed':0,'host_prng_api':'pycolmap.set_random_seed','stereo_random_seed_option_available':False,'gpu_prng_policy':'COLMAP4.2 stock curand_init(pixel_id,0,0)','private_fixed_seed0_equivalence':False,'cuda_execution':'NOT_RUN','native_science_rebuilt':False,'source320_claimed':False},sort_keys=True))
if __name__=='__main__':main()
