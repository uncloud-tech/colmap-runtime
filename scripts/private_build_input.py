"""Generic bounded private-context packing/unpacking for manual trusted CI.
No secret contents or exception strings are printed. Public source archive is
fetched separately; never include it or receiver/operational keys in secrets.
"""
import argparse,base64,gzip,hashlib,io,json,os,re,tarfile,sys
from pathlib import Path
MAX_EXPANDED=2*1024**2

def pack(context,out):
 context=Path(context);raw=io.BytesIO()
 with tarfile.open(fileobj=raw,mode='w') as t:
  for p in sorted(context.rglob('*')):
   if not p.is_file() or p.name=='baseline.tar':continue
   if p.is_symlink():raise ValueError('regular inputs only')
   data=p.read_bytes();i=tarfile.TarInfo(str(p.relative_to(context)));i.size=len(data);i.mode=0o755 if p.name=='submit-results' else 0o600;t.addfile(i,io.BytesIO(data))
 if len(raw.getvalue())>MAX_EXPANDED:raise ValueError('context expanded cap')
 compressed=gzip.compress(raw.getvalue(),mtime=0);encoded=base64.b64encode(compressed);chunks=[encoded[i:i+48000] for i in range(0,len(encoded),48000)]
 if not 1<=len(chunks)<=2:raise ValueError('requires more than two scoped secrets; refuse route')
 out=Path(out);out.mkdir(mode=0o700,exist_ok=False)
 for i,c in enumerate(chunks,1):p=out/('context-'+str(i));p.write_bytes(c);p.chmod(0o400)
 result={'gzip_sha256':hashlib.sha256(compressed).hexdigest(),'compressed_bytes':len(compressed),'encoded_bytes':len(encoded),'secret_count':len(chunks),'contains_public_baseline_archive':False};(out/'binding.json').write_text(json.dumps(result,indent=2)+'\n');return result

def unpack(encoded,expected,out):
 if not re.fullmatch('[0-9a-f]{64}',expected) or len(encoded)>96000:raise ValueError('bounded input/hash required')
 compressed=base64.b64decode(encoded,validate=True)
 if hashlib.sha256(compressed).hexdigest()!=expected:raise ValueError('input hash mismatch')
 with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:raw=f.read(MAX_EXPANDED+1)
 if len(raw)>MAX_EXPANDED:raise ValueError('expanded cap')
 out=Path(out);out.mkdir(mode=0o700,exist_ok=False)
 with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as t:
  seen=set()
  for m in t:
   if m.name in seen or not m.isfile() or not re.fullmatch('[A-Za-z0-9_./-]+',m.name) or m.name.startswith('/') or Path(m.name).as_posix()!=m.name or '..' in m.name.split('/') or m.size>MAX_EXPANDED:raise ValueError('regular relative unique files only')
   seen.add(m.name);p=out/m.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(t.extractfile(m).read());p.chmod(0o755 if p.name=='submit-results' else 0o600)
 return out

def require_oci_size(size):
 # Whole OCI tar contains compressed layers AND config/manifest/index/overhead.
 if type(size) is not int or not 0<size<=7*1024**3:raise ValueError('complete compressed OCI payload exceeds approved bound')
 return size

def prepare_oci(archive,out):
 """Verify the measured export and stage ONLY its OCI layout, never a rootfs.
 Publication imports these gzip blobs with force-compression=false. Do not use
 docker push on the --load copy: daemon recompression would invalidate the bound.
 """
 import shutil,stat
 archive=Path(archive);info=archive.lstat()
 if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('regular owned export required')
 size=require_oci_size(info.st_size);out=Path(out);out.mkdir(mode=0o700,exist_ok=False)
 with tarfile.open(archive,'r:') as t:
  seen=set()
  for member in t:
   name=member.name
   if member.isdir() and name.rstrip('/') in ('blobs','blobs/sha256'):continue
   if name in seen or len(seen)>=128 or not member.isfile() or not (name in ('index.json','oci-layout') or re.fullmatch('blobs/sha256/[0-9a-f]{64}',name)):raise ValueError('literal regular unique OCI files required')
   if not 0<=member.size<=size:raise ValueError('OCI member size')
   if name in ('index.json','oci-layout') and member.size>1024**2:raise ValueError('bounded OCI metadata required')
   seen.add(name);dest=out/name;dest.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256()
   with t.extractfile(member) as src,dest.open('xb') as dst:
    while block:=src.read(1024**2):h.update(block);dst.write(block)
   if name.startswith('blobs/') and h.hexdigest()!=name.rsplit('/',1)[1]:raise ValueError('OCI blob hash mismatch')
 def document(digest):
  if not re.fullmatch('sha256:[0-9a-f]{64}',digest):raise ValueError('OCI digest required')
  p=out/'blobs/sha256'/digest[7:]
  if p.stat().st_size>1024**2:raise ValueError('bounded OCI document required')
  return json.loads(p.read_bytes())
 index=json.loads((out/'index.json').read_bytes())
 if len(index['manifests'])!=1:raise ValueError('single image export required')
 digest=index['manifests'][0]['digest'];manifest=document(digest);config=manifest['config']['digest'];document(config)
 if not manifest['layers']:raise ValueError('nonempty payload required')
 for layer in manifest['layers']:
  if layer['mediaType']!='application/vnd.oci.image.layer.v1.tar+gzip' or not re.fullmatch('sha256:[0-9a-f]{64}',layer['digest']):raise ValueError('preserved gzip layers required')
  if type(layer['size']) is not int or (out/'blobs/sha256'/layer['digest'][7:]).stat().st_size!=layer['size']:raise ValueError('layer byte mismatch')
 return {'manifest_digest':digest,'config_digest':config,'complete_oci_archive_bytes':size}

def registry_check(digest):
 import urllib.request,urllib.error
 if not re.fullmatch('sha256:[0-9a-f]{64}',digest):raise ValueError('manifest digest required')
 package='uncloud-tech/colmap-calibration-private';secret=os.environ['REGISTRY_TOKEN'];actor=os.environ['GITHUB_ACTOR']
 def get(url,headers={}):
  with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=20) as r:return json.load(r)
 meta=get('https://api.github.com/orgs/uncloud-tech/packages/container/colmap-calibration-private',{'Authorization':'Bearer '+secret,'Accept':'application/vnd.github+json'})
 if meta['visibility']!='private':raise ValueError('package ACL must be private')
 url='https://ghcr.io/token?service=ghcr.io&scope=repository:'+package+':pull'
 auth='Basic '+base64.b64encode((actor+':'+secret).encode()).decode();token=get(url,{'Authorization':auth})['token']
 manifest='https://ghcr.io/v2/'+package+'/manifests/'+digest;accept='application/vnd.oci.image.manifest.v1+json'
 get(manifest,{'Authorization':'Bearer '+token,'Accept':accept}) # authorized read must work
 try:
  anonymous=get(url)['token'];get(manifest,{'Authorization':'Bearer '+anonymous,'Accept':accept})
 except urllib.error.HTTPError as e:
  if e.code not in (401,403):raise
 else:raise ValueError('anonymous package read unexpectedly allowed')

def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True);a=s.add_parser('pack');a.add_argument('context',type=Path);a.add_argument('out',type=Path);a=s.add_parser('unpack');a.add_argument('sha256');a.add_argument('out',type=Path);a=s.add_parser('registry-check');a.add_argument('digest');a=s.add_parser('oci-check');a.add_argument('archive',type=Path);a.add_argument('out',type=Path);a=p.parse_args()
 if a.mode=='pack':print(json.dumps(pack(a.context,a.out)))
 elif a.mode=='unpack':unpack((os.environ.get('PRIVATE_CONTEXT_1','')+os.environ.get('PRIVATE_CONTEXT_2','')).encode(),a.sha256,a.out)
 elif a.mode=='oci-check':print(json.dumps(prepare_oci(a.archive,a.out)))
 else:registry_check(a.digest)
if __name__=='__main__':
 try:main()
 except Exception:
  print('private context rejected; no input details logged',file=sys.stderr);raise SystemExit(2)
