"""Create a shared computation snapshot, then measure 20M per-core targets."""
import concurrent.futures,json,os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
import srfd_eval
validation=json.loads((HERE/'validation_results.json').read_text())
if len(validation)!=4 or not all(row['passed'] for row in validation):
 raise SystemExit('The complete small checkpoint validation must pass first')
native=json.loads((HERE/'native_validation/verification.json').read_text())
if not native['passed']:raise SystemExit('Native computation gate validation must pass')
profile=json.loads((HERE/'native_profile/selected_compute_profile.json').read_text())
if profile['samples']<100 or any('ComputeNonbondedUtil::calc_' not in symbol for symbol,count in profile['top_symbols']):raise SystemExit('Selected native computation profile must contain force kernels')
cp=HERE/'cpt_4x4_compute'
def launch(name,args):
 command=[sys.executable,str(HERE/'run_checkpoint.py'),'--mesh-rows=4',f'--checkpoint={cp}',f'--output={HERE/name}','--timeout=86400','--roi-seconds=120']+args
 with (HERE/(name+'_launcher.log')).open('w') as log:
  code=subprocess.run(command,cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdout=log,stderr=subprocess.STDOUT).returncode
 if code:raise RuntimeError(f'{name} failed; see its launcher and run logs')
 return json.loads((HERE/name/'verification.json').read_text())
if not cp.exists():launch('create_4x4',['--action=create','--mode=baseline'])
rows=[]
def measure(mode):
 name='roi_4x4_'+mode
 result=launch(name,['--action=restore','--mode='+mode,'--warmup-insts=100000','--roi-insts=20000000'])
 out=HERE/name
 phase=result['status']['phases']['roi']
 if result['status'].get('events'):raise RuntimeError('Unexpected compute-end or guest event during bounded measurement')
 if len(phase['instructions'])!=16 or min(phase['instructions'])<20000000:raise RuntimeError('Incomplete per-core budgets')
 stats=srfd_eval.parse_stats(str(out/'roi_stats.txt'))
 srfd=srfd_eval.aggregate_srfd(stats,mode)
 paper=srfd_eval.aggregate_paper_metrics(stats)
 srfd_eval.validate_srfd_accounting(srfd,paper,name)
 ticks=phase['end_tick']-phase['start_tick']; insts=sum(phase['instructions'])
 if stats['simTicks']!=ticks or stats['simInsts']!=insts:raise RuntimeError('ROI statistics and phase counters disagree')
 row={'mode':mode,'passed':True,'roi_ticks':ticks,'roi_instructions':phase['instructions'],'aggregate_instructions':insts,'aggregate_ipc':insts/(ticks/500),
      'dirty_hits':srfd['dirty_hits'],'clean_hits':srfd['clean_hits'],'local_reply_rate_percentage':srfd['local_reply_rate_percentage'],'llc_completion_mean_cycles':paper['combined_mean_cycles'],'lifecycle_validated':paper['lifecycle_accounting_verified']}
 (out/'analysis.json').write_text(json.dumps(row,indent=2))
 return row
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 for row in pool.map(measure,['baseline','cbdb-aggressive']):
  rows.append(row);(HERE/'results_4x4.json').write_text(json.dumps(rows,indent=2));print(row,flush=True)
a,b=rows
comparison={'target_completion_time_ratio':a['roi_ticks']/b['roi_ticks'],'aggregate_ipc_ratio':b['aggregate_ipc']/a['aggregate_ipc'],
 'method':'All CPUs stay active; stop after every core reaches at least 20M. Faster cores retire extra work; this is not the previous equal-budget paused-core SE method.'}
(HERE/'comparison_4x4.json').write_text(json.dumps(comparison,indent=2));print(comparison,flush=True)
