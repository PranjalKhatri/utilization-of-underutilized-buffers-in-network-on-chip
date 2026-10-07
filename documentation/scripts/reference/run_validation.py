"""Validate a fresh baseline computation checkpoint before the larger run."""
import json,os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
cp=HERE/'cpt_2x2_compute'
rows=[]
def run(name,extra):
 cmd=[sys.executable,str(HERE/'run_checkpoint.py'),'--mesh-rows=2',f'--checkpoint={cp}',f'--output={HERE/name}']+extra
 with (HERE/(name+'_launcher.log')).open('w') as log:
  code=subprocess.run(cmd,cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdout=log,stderr=subprocess.STDOUT).returncode
 result=json.loads((HERE/name/'verification.json').read_text()) if (HERE/name/'verification.json').exists() else {'passed':False}
 rows.append({'case':name,'returncode':code,'passed':result['passed']})
 (HERE/'validation_results.json').write_text(json.dumps(rows,indent=2))
 print(rows[-1],flush=True)
 if code or not result['passed']:raise SystemExit(1)
run('create_2x2_compute',['--action=create'])
run('restore_2x2_compute_full',['--action=restore','--mode=baseline','--roi-cpu=kvm','--roi-seconds=600','--timeout=3600'])
for mode in ['baseline','cbdb-aggressive']:
 run('restore_2x2_compute_'+mode,['--action=restore','--mode='+mode,'--warmup-insts=10000','--roi-insts=100000'])
