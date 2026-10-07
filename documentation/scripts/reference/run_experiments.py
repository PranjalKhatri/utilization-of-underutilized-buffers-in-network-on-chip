"""Validate cold-checkpoint compatibility and run only the two requested modes."""
import argparse,hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
import srfd_eval
parser=argparse.ArgumentParser()
parser.add_argument('--reserved-vcs',type=int,default=2)
args=parser.parse_args()
reserve=args.reserved_vcs
if not 0<=reserve<=6:parser.error('reserve must be in [0,6]')
capacity=6-reserve

def save(stage,**fields):
 (HERE/'workflow_status.json').write_text(json.dumps({'stage':stage,'reserved_vcs':reserve,'storage_limit':capacity,**fields},indent=2))

def wait_memory(name):
 while True:
  available=int(re.search(r'^MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])*1024
  if available>=9*1024**3:break
  save('waiting_for_memory',next_case=name,available_bytes=available,required_bytes=9*1024**3)
  time.sleep(30)

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024**2),b''):h.update(chunk)
 return h.hexdigest()

def launch(name,mode,mesh,warmup,budget,kvm=False):
 wait_memory(name);save('running',case=name,mode=mode)
 cmd=[sys.executable,str(HERE/'run_checkpoint.py'),'--action=restore',f'--mode={mode}',f'--mesh-rows={mesh}',f'--checkpoint={HERE/("cpt_2x2_compute" if mesh==2 else "cpt_4x4_compute")}',f'--output={HERE/name}',f'--srfd-reserved-vcs={reserve}',f'--warmup-insts={warmup}',f'--roi-insts={budget}','--timeout=86400','--roi-seconds='+('600' if kvm else '120')]
 if kvm:cmd+=['--roi-cpu=kvm']
 with (HERE/(name+'_launcher.log')).open('w') as log:
  subprocess.run(cmd,cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdout=log,stderr=subprocess.STDOUT,check=True)
 out=HERE/name;v=json.loads((out/'verification.json').read_text())
 if not v['passed']:raise RuntimeError(name+' verification failed')
 if kvm:return v
 if v['status'].get('events'):raise RuntimeError(name+' escaped computation call')
 phase=v['status']['phases']['roi'];counts=phase['instructions']
 if len(counts)!=mesh**2 or min(counts)<budget:raise RuntimeError('Incomplete per-core measurement')
 s=srfd_eval.parse_stats(str(out/'roi_stats.txt'));a=srfd_eval.aggregate_srfd(s,mode);p=srfd_eval.aggregate_paper_metrics(s)
 srfd_eval.validate_srfd_accounting(a,p,name)
 if a['max_stored']>capacity:raise RuntimeError('Storage cap exceeded')
 ticks=phase['end_tick']-phase['start_tick'];insts=sum(counts)
 if s['simTicks']!=ticks or s['simInsts']!=insts:raise RuntimeError('ROI counter mismatch')
 cfg=json.loads((out/'config.json').read_text())['system'];net=cfg['ruby']['network']
 corners=sorted(int(re.search(r'routers(\d+)$',link['int_node'])[1]) for link in net['ext_links'] if 'dir_cntrl' in link['ext_node'])
 if net['vcs_per_vnet']!=6 or net['srfd_reserved_vcs']!=reserve or net['srfd_mode']!=mode or corners!=[0,mesh-1,mesh*(mesh-1),mesh*mesh-1]:raise RuntimeError('Configuration mismatch')
 result={'mode':mode,'reserved_vcs':reserve,'storage_limit':capacity,'passed':True,'roi_instructions':counts,'aggregate_instructions':insts,'roi_ticks':ticks,'aggregate_ipc':insts/(ticks/500),'average_ipc_per_core':insts/(ticks/500)/(mesh**2),'llc_completion_mean_cycles':p['combined_mean_cycles'],'srfd':a,'lifecycle_validated':p['lifecycle_accounting_verified'],'host_seconds':s['hostSeconds'],'host_inst_rate':s['hostInstRate'],'configuration_verified':True}
 (out/'analysis.json').write_text(json.dumps(result,indent=2));print(name,'passed',flush=True)
 return result

try:
 tests=json.loads((HERE/'reservation_tests_passed.json').read_text())
 if not tests['passed']:raise RuntimeError('Reservation regressions must pass first')
 old=(HERE/'old_binary_sha256.txt').read_text().strip()
 current=sha(ROOT/'build/X86_MOESI_CMP_directory/gem5.opt')
 compat={'old_binary_sha256':old,'new_binary_sha256':current,'functional_restore_verified':False,'scope':'Only existing cold baseline computation-call-7 checkpoints. Changes are SRFD reservation/admission and statistics; CPU/ISA/serialization code is unchanged. Default-zero randomized ticks match the preserved binary.'}
 (HERE/'checkpoint_compatibility.json').write_text(json.dumps(compat,indent=2))
 trial=launch('checkpoint_compat_2x2','cbdb-aggressive',2,0,1,True)
 if not all(trial.get('native_output_matches',[])) or len(trial['native_output_matches'])!=4:raise RuntimeError('Checkpoint restore outputs mismatch')
 compat['functional_restore_verified']=True;compat['validation_case']='checkpoint_compat_2x2'
 (HERE/'checkpoint_compatibility.json').write_text(json.dumps(compat,indent=2))
 for mode in ['cbdb-aggressive','cbdb-defensive']:
  launch('smoke_2x2_'+mode,mode,2,10000,100000)
 save('smokes_passed')
 baseline=json.loads((ROOT/'PAPER_TESTS/namd_compute_roi_20261006/roi_4x4_baseline/analysis.json').read_text())
 rows=[]
 for mode in ['cbdb-aggressive','cbdb-defensive']:
  row=launch('roi_4x4_'+mode,mode,4,100000,20000000)
  row['ipc_ratio_vs_existing_baseline']=row['aggregate_ipc']/baseline['aggregate_ipc']
  row['target_time_ratio_vs_existing_baseline']=baseline['roi_ticks']/row['roi_ticks']
  rows.append(row);(HERE/'results.json').write_text(json.dumps(rows,indent=2))
  lines=['# NAMD computation-only reserved-capacity comparison','','Existing baseline result reused; no baseline timing run was launched. The existing cold KVM checkpoint was compatibility-validated under the rebuilt binary.','','| Mode | Cap | Aggregate IPC | LLC cycles | Dirty stored | Clean stored | Pressure releases | Dirty bypassed | Clean bypassed | IPC ratio vs prior baseline |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
  lines.append(f"| Prior baseline | — | {baseline['aggregate_ipc']:.6f} | {baseline['llc_completion_mean_cycles']:.6f} | 0 | 0 | 0 | — | — | 1.000000x |")
  for r in rows:
   a=r['srfd'];lines.append(f"| {r['mode']} | {capacity} | {r['aggregate_ipc']:.6f} | {r['llc_completion_mean_cycles']:.6f} | {a['dirty_stored']:,.0f} | {a['clean_stored']:,.0f} | {a['pressure_events']:,.0f} | {a['dirty_bypassed']:,.0f} | {a['clean_bypassed']:,.0f} | {r['ipc_ratio_vs_existing_baseline']:.6f}x |")
  lines+=['','16 O3 cores, 4x4 mesh, six VCs/vnet, corner directories. 100k minimum warmup and 20M minimum measured instructions per core, within the selected force computation call. Faster cores remain active, so actual counts differ. Reservation is per local data input. Bypass events are not pressure releases. Baseline mode logic is unchanged, but the reused baseline is from the prior binary; host throughput is not a controlled comparison.']
  (HERE/'RESULTS.md').write_text('\n'.join(lines)+'\n')
 save('complete')
except BaseException as error:
 save('failed',error=str(error));(HERE/'RUN_FAILED.json').write_text(json.dumps({'error':str(error)},indent=2));raise
