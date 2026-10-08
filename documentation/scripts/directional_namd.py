import argparse,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ASSETS=ROOT/'PAPER_TESTS/namd_compute_roi_20261006'
p=argparse.ArgumentParser()
p.add_argument('--action',choices=['create','restore'],required=True)
p.add_argument('--srfd-reserved-vcs',type=int,default=2)
p.add_argument('--srfd-directional-storage',action='store_true')
p.add_argument('--no-srfd-directional-storage',action='store_false',dest='srfd_directional_storage')
p.add_argument('--compatibility-trial',action='store_true')
p.add_argument('--mesh-rows',type=int,default=2)
p.add_argument('--mem-size',default='3GB')
p.add_argument('--no-access-backing-store',action='store_true')
p.add_argument('--topology',choices=['MeshDirCorners_XY','Mesh_XY','MeshDirMedials_XY'],default='MeshDirCorners_XY')
p.add_argument('--mode',choices=['baseline','cbdb-aggressive','db-aggressive','cbdb-defensive'],default='baseline')
p.add_argument('--checkpoint',required=True)
p.add_argument('--output',required=True)
p.add_argument('--warmup-insts',type=int,default=100000)
p.add_argument('--roi-insts',type=int,default=100000000)
p.add_argument('--roi-cpu',choices=['o3','kvm'],default='o3')
p.add_argument('--trace-roi',action='store_true')
p.add_argument('--iterations',type=int,default=2)
p.add_argument('--timeout',type=int,default=3600)
p.add_argument('--roi-seconds',type=float,default=120)
a=p.parse_args()
cores=a.mesh_rows**2
out=Path(a.output).resolve();cpt=Path(a.checkpoint).resolve()
if not out.is_relative_to(ROOT/'PAPER_TESTS') or not cpt.is_relative_to(ROOT/'PAPER_TESTS'):p.error('artifacts must be in PAPER_TESTS')
if a.compatibility_trial and (a.action!='restore' or a.roi_cpu!='kvm' or a.mode!='baseline' or a.srfd_directional_storage):p.error('compatibility trial requires baseline KVM restore')
if a.srfd_directional_storage and a.srfd_reserved_vcs<1:p.error('directional storage reserves one escape VC; maximum cap is 5')
if a.action=='create' and (a.mode!='baseline' or cpt.exists()):p.error('create requires baseline and a new checkpoint path')
if a.action=='restore':
 meta=json.loads((cpt/'post_input_metadata.json').read_text())
 if meta['cores']!=cores:p.error('checkpoint geometry mismatch')
 if meta.get('srfd_mode')!='baseline' or meta.get('compute_boundary',{}).get('call')!=7:p.error('expected the saved baseline computation-call-7 checkpoint')
 if meta.get('topology','MeshDirCorners_XY')!=a.topology:p.error('checkpoint topology mismatch')
 if meta.get('mem_size','3GB')!=a.mem_size or meta.get('access_backing_store',True)==a.no_access_backing_store:p.error('checkpoint memory size/backing mode mismatch')
out.mkdir(parents=True,exist_ok=False)
script=out/'guest.rcS'
script.write_text(f'''#!/bin/bash
set -e
mount -t proc proc /proc
mount -t sysfs sysfs /sys
exec 2>/tmp/checkpoint_stderr.log
trap 'echo POSTINPUT_GUEST_FAILED command=$BASH_COMMAND > /tmp/checkpoint_failure.txt; cat /tmp/checkpoint_stderr.log >> /tmp/checkpoint_failure.txt; for errfile in /tmp/postinput-runs/*/stderr.log; do if [ -s "$errfile" ]; then echo "$errfile" >> /tmp/checkpoint_failure.txt; cat "$errfile" >> /tmp/checkpoint_failure.txt; fi; done; /sbin/m5 --addr writefile /tmp/checkpoint_failure.txt checkpoint_failure.txt; /sbin/m5 --addr fail 1' ERR
mkdir -p /mnt/spec /tmp/postinput-runs
mount -t ext4 -o ro /dev/hdb /mnt/spec
dd if=/dev/zero of=/tmp/namd_compute_gate.bin bs=4096 count=1
pids=()
for i in $(seq 0 {cores-1}); do
 mkdir -p /tmp/postinput-runs/$i
 (cd /tmp/postinput-runs/$i; taskset -c $i env LD_PRELOAD=/mnt/spec/binaries/compute_gate.so NAMD_GATE_FILE=/tmp/namd_compute_gate.bin NAMD_GATE_EXPECTED={cores} NAMD_GATE_WORKER=$i /mnt/spec/binaries/namd --input /mnt/spec/data/namd/all/input/namd.input --iterations {a.iterations} --output result.output >stdout.log 2>stderr.log) &
 pids+=($!)
done
for pid in "${{pids[@]}}"; do wait "$pid"; done
for i in $(seq 0 {cores-1}); do grep -q 'SUCCESSFUL COMPLETION' /tmp/postinput-runs/$i/stdout.log; done
/mnt/spec/binaries/m5 --addr workend 0 0
for i in $(seq 0 {cores-1}); do
 /mnt/spec/binaries/m5 --addr writefile /tmp/postinput-runs/$i/stdout.log checkpoint_core_$i.stdout
 /mnt/spec/binaries/m5 --addr writefile /tmp/postinput-runs/$i/stderr.log checkpoint_core_$i.stderr
 /mnt/spec/binaries/m5 --addr writefile /tmp/postinput-runs/$i/result.output checkpoint_core_$i.output
done
/mnt/spec/binaries/m5 --addr writefile /tmp/namd_compute_gate.bin restored_gate.bin
echo POSTINPUT_GUEST_SUCCESS > /tmp/checkpoint_success.txt
/mnt/spec/binaries/m5 --addr writefile /tmp/checkpoint_success.txt checkpoint_success.txt
/mnt/spec/binaries/m5 --addr exit
''')
binary=ROOT/'build/X86_MOESI_CMP_directory/gem5.opt'
cmd=[str(binary),'-d',str(out),str(HERE/'directional_checkpoint_fs.py'),f'--action={a.action}',f'--checkpoint-dir={cpt}',f'--mesh-rows={a.mesh_rows}',f'--topology={a.topology}',f'--srfd-mode={a.mode}',f'--srfd-reserved-vcs={a.srfd_reserved_vcs}',f'--warmup-insts={a.warmup_insts}',f'--roi-insts={a.roi_insts}',f'--roi-cpu={a.roi_cpu}',f'--roi-seconds={a.roi_seconds}',
 '--kernel=/root/.cache/gem5/x86-linux-kernel-4.19.83-1.0.0','--disk-image=/root/.cache/gem5/x86-parsec-1.0.0',f'--payload-image={ASSETS/"payload_compute.img"}',f'--script={script}']
if a.trace_roi:cmd.append('--trace-roi')
if a.srfd_directional_storage:cmd.append('--srfd-directional-storage')
cmd.append(f'--mem-size={a.mem_size}')
if a.no_access_backing_store:cmd.append('--no-access-backing-store')
(out/'command.json').write_text(json.dumps(cmd,indent=2))
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024**2),b''):h.update(chunk)
 return h.hexdigest()
sources=[HERE/'directional_checkpoint_fs.py',HERE/'directional_namd.py',ASSETS/'compute_gate.c',script]
snap=out/'source_snapshot';snap.mkdir()
for f in sources:shutil.copy2(f,snap/f.name)
manifest={'command':cmd,'binary_sha256':sha(binary),'payload_sha256':sha(ASSETS/'payload_compute.img'),'hook_sha256':sha(ASSETS/'compute_gate.so'),'sources':{str(f.relative_to(ROOT)):sha(f) for f in sources},'cores':cores,'topology':a.topology,'budget_convention':'all CPUs remain active; stop once each reaches requested target','iterations':a.iterations,'srfd_reserved_vcs':a.srfd_reserved_vcs,'srfd_storage_limit':6-a.srfd_reserved_vcs,'srfd_directional_storage':a.srfd_directional_storage}
git=['git','-c',f'safe.directory={ROOT}']
manifest['git_head']=subprocess.check_output(git+['rev-parse','HEAD'],cwd=ROOT).decode().strip()
manifest['mem_size']=a.mem_size
manifest['access_backing_store']=not a.no_access_backing_store
changed=subprocess.check_output(git+['diff','--name-only','--','src','configs','srfd_eval.py'],cwd=ROOT).decode().splitlines()
manifest['modified_source_sha256']={name:sha(ROOT/name) for name in changed if (ROOT/name).is_file()}
if changed:
 (out/'source_changes.patch').write_bytes(subprocess.check_output(git+['diff','--','src','configs','srfd_eval.py'],cwd=ROOT))
if a.action=='restore':
 creator_manifest=json.loads((cpt/'creation_manifest.json').read_text())
 if manifest['payload_sha256']!=creator_manifest['payload_sha256']:
  p.error('checkpoint payload differs from creator')
 if manifest['binary_sha256']!=creator_manifest['binary_sha256']:
  import re
  if not re.search(r'^cache_trace_size=0$',(cpt/'m5.cpt').read_text(),re.M):
   p.error('only cold baseline checkpoints qualify for this compatibility path')
  trial=a.compatibility_trial and a.roi_cpu=='kvm' and a.mode=='baseline' and not a.srfd_directional_storage
  compatibility=out.parent/'checkpoint_compatibility.json'
  compatible=json.loads(compatibility.read_text()) if compatibility.exists() else {}
  key=str(cores)
  record=compatible.get(key,{})
  if not trial and (record.get('old_binary_sha256')!=creator_manifest['binary_sha256'] or
                   record.get('new_binary_sha256')!=manifest['binary_sha256'] or
                   not record.get('functional_restore_verified')):
   p.error('run baseline KVM --compatibility-trial for this binary and geometry first')
  manifest['checkpoint_compatibility']=record if not trial else {'trial':True}

(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
start=time.monotonic()
with (out/'run.log').open('w') as log:
 child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
 (out/'pid.txt').write_text(str(child.pid)+'\n')
 try:code=child.wait(timeout=a.timeout)
 except subprocess.TimeoutExpired:child.kill();child.wait();code='timeout'
s=json.loads((out/'fs_roi_status.json').read_text()) if (out/'fs_roi_status.json').exists() else {}
if a.action=='create' and code==0 and s.get('status')=='checkpoint_complete':
 (cpt/'creation_manifest.json').write_text(json.dumps(manifest,indent=2))
expected='checkpoint_complete' if a.action=='create' else ('complete' if a.roi_cpu=='o3' else 'full_validation_complete')
passed=code==0 and s.get('status')==expected
result={'passed':passed,'returncode':code,'seconds':time.monotonic()-start,'status':s}
if a.action=='restore' and a.roi_cpu=='kvm' and passed:
 gold=(ASSETS/'native_validation/result.output').read_bytes()
 result['native_output_matches']=[(out/f'checkpoint_core_{i}.output').read_bytes()==gold for i in range(cores)]
 passed=passed and all(result['native_output_matches']);result['passed']=passed
(out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2),flush=True)
if not passed:raise SystemExit(1)
if a.compatibility_trial:
 if a.roi_cpu!='kvm' or a.mode!='baseline' or a.srfd_directional_storage:
  p.error('compatibility trials require baseline KVM without directional storage')
 compatibility=out.parent/'checkpoint_compatibility.json'
 records=json.loads(compatibility.read_text()) if compatibility.exists() else {}
 records[str(cores)]={'old_binary_sha256':creator_manifest['binary_sha256'],
                     'new_binary_sha256':manifest['binary_sha256'],
                     'functional_restore_verified':True,
                     'verification_path':str(out/'verification.json')}
 compatibility.write_text(json.dumps(records,indent=2))
