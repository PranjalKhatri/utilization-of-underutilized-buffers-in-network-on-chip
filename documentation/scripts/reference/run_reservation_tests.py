import concurrent.futures,json,os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
import srfd_eval
BIN=ROOT/'build/X86_MOESI_CMP_directory/gem5.opt'
BASE=['--num-cpus=4','--num-dirs=4','--num-l2caches=4','--ruby','--network=garnet','--topology=MeshDirCorners_XY','--mesh-rows=2','--buffers-per-data-vc=5','--link-width-bits=128','--router-latency=2','--routing-algorithm=1','--maxloads=20000']
CASES=[('legacy_default',HERE/'gem5_before.opt',0,6,'cbdb-aggressive',True),('new_default',BIN,0,6,'cbdb-aggressive',False)]
for mode in ['cbdb-aggressive','cbdb-defensive']:
 for vcs,reserve in [(6,2),(2,1),(2,2)]:CASES.append((mode+'_'+str(vcs)+'vc_reserve'+str(reserve),BIN,reserve,vcs,mode,False))
CASES += [('invalid_negative',BIN,-1,6,'cbdb-aggressive',False),('invalid_excess',BIN,7,6,'cbdb-aggressive',False)]
def run(case):
 name,binary,reserve,vcs,mode,legacy=case;out=HERE/('test_'+name);out.mkdir(exist_ok=False)
 script=HERE/'legacy_random_wrapper.py' if legacy else ROOT/'configs/example/ruby_random_test.py'
 cmd=[str(binary),'-d',str(out),str(script)]+BASE+['--vcs-per-vnet='+str(vcs),'--srfd-mode='+mode]
 if not legacy:cmd+=['--srfd-reserved-vcs='+str(reserve)]
 (out/'command.json').write_text(json.dumps(cmd,indent=2))
 with (out/'run.log').open('w') as log:
  try:code=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
  except subprocess.TimeoutExpired:raise RuntimeError(name+' timeout')
 if name.startswith('invalid'):
  passed=code!=0 and '--srfd-reserved-vcs must be between' in (out/'run.log').read_text()
  return {'case':name,'passed':passed,'returncode':code}
 if code:raise RuntimeError(name+' failed; inspect run.log')
 stats=srfd_eval.parse_stats(str(out/'stats.txt'));s=srfd_eval.aggregate_srfd(stats,mode);p=srfd_eval.aggregate_paper_metrics(stats);srfd_eval.validate_srfd_accounting(s,p,name)
 limit=vcs-reserve
 if s['max_stored']>limit:raise RuntimeError(name+' exceeded storage cap')
 if reserve==vcs and (s['dirty_stored'] or s['clean_stored'] or s['dirty_hits'] or s['clean_hits']):raise RuntimeError(name+' stored/replied with zero capacity')
 if reserve>0 and s['dirty_bypassed']+s['clean_bypassed']==0:raise RuntimeError(name+' did not exercise overflow admission')
 return {'case':name,'passed':True,'sim_ticks':stats['simTicks'],'storage_limit':limit,'max_stored':s['max_stored'],'dirty_bypassed':s['dirty_bypassed'],'clean_bypassed':s['clean_bypassed'],'dirty_hits':s['dirty_hits'],'clean_hits':s['clean_hits'],'accounting_verified':p['lifecycle_accounting_verified']}
rows=[]
try:
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  for row in pool.map(run,CASES):
   rows.append(row);(HERE/'reservation_test_results.json').write_text(json.dumps(rows,indent=2));print(row,flush=True)
 if not all(r['passed'] for r in rows):raise RuntimeError('A rejection test failed')
 if rows[0]['sim_ticks']!=rows[1]['sim_ticks']:raise RuntimeError('Default-zero tick count changed from preserved binary')
 (HERE/'reservation_tests_passed.json').write_text(json.dumps({'passed':True,'cases':len(rows),'default_zero_ticks_unchanged':True},indent=2))
except BaseException as error:
 (HERE/'reservation_tests_failed.json').write_text(json.dumps({'error':str(error)},indent=2));raise
