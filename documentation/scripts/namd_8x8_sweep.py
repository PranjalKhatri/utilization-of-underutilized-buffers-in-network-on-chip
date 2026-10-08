#!/usr/bin/env python3
"""Validate a large-memory guest, then queue matched 64-core NAMD ROIs."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
p.add_argument('--roi-insts',type=int,default=20000000)
p.add_argument('--directional-cap5',action=argparse.BooleanOptionalAction,default=True)
a=p.parse_args()
HERE=a.output.resolve()
if not HERE.is_relative_to(ROOT/'PAPER_TESTS') or a.roi_insts<=0:
    p.error('use PAPER_TESTS and a positive per-core ROI target')
HERE.mkdir(parents=True,exist_ok=True)
RUNNER=Path(__file__).with_name('directional_namd.py')
sys.path.insert(0,str(ROOT))
import srfd_eval

def state(stage,**fields):
    (HERE/'workflow_status.json').write_text(json.dumps(dict(stage=stage,**fields),indent=2))

def launch(name,rows,action='restore',mode='baseline',cap=6,directional=False,
           kvm=False,roi=None,warmup=100000):
    # One gem5 job at a time; avoid launching during host memory pressure.
    while True:
        lines=Path('/proc/meminfo').read_text().splitlines()
        available=int(next(x for x in lines if x.startswith('MemAvailable:')).split()[1])
        if available>=20*1024**2:break
        state('waiting_for_memory',case=name,available_kib=available,required_gib=20)
        time.sleep(30)
    out=HERE/name
    existing=out/'verification.json'
    if existing.exists():
        saved=json.loads(existing.read_text())
        if saved['passed']:return saved
        raise RuntimeError(name+': previous failed attempt requires inspection')
    if out.exists():
        # The separately launched 2x2 preparatory checkpoint may still be
        # compressing. Wait for its actual verification rather than restart it.
        if name!='create_2x2_16gb':raise RuntimeError(name+': incomplete previous output')
        state('waiting_for_checkpoint_validation',case=name)
        while not existing.exists():
            status=out/'fs_roi_status.json'
            if status.exists() and json.loads(status.read_text()).get('status')=='failed':
                raise RuntimeError(name+': checkpoint creation failed')
            time.sleep(10)
        saved=json.loads(existing.read_text())
        if not saved['passed']:raise RuntimeError(name+': checkpoint verification failed')
        return saved
    state('running',case=name)
    checkpoint=HERE/f'cpt_{rows}x{rows}_16gb'
    command=[sys.executable,str(RUNNER),f'--action={action}',f'--mesh-rows={rows}',
             '--mem-size=16GB','--no-access-backing-store',f'--mode={mode}',
             f'--srfd-reserved-vcs={6-cap}',f'--checkpoint={checkpoint}',
             f'--output={out}',f'--warmup-insts={warmup}',
             f'--roi-insts={a.roi_insts if roi is None else roi}',
             f'--roi-cpu={"kvm" if kvm else "o3"}',
             '--roi-seconds=600' if kvm else '--roi-seconds=120','--timeout=172800']
    if directional:command.append('--srfd-directional-storage')
    with (HERE/f'{name}_launcher.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,check=True,stdout=log,stderr=subprocess.STDOUT,
                       env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    saved=json.loads(existing.read_text())
    if not saved['passed']:raise RuntimeError(name+': verification failed')
    return saved

def analyze(name,mode,rows,target,directional,cap):
    out=HERE/name
    v=json.loads((out/'verification.json').read_text())
    s=v['status']
    phase=s['phases']['roi']
    counts=phase['instructions']
    if s['events'] or len(counts)!=rows**2 or min(counts)<target:
        raise RuntimeError(name+': incomplete computation-only window')
    stats=srfd_eval.parse_stats(str(out/'roi_stats.txt'))
    actions=srfd_eval.aggregate_srfd(stats,mode)
    paper=srfd_eval.aggregate_paper_metrics(stats)
    srfd_eval.validate_srfd_accounting(actions,paper,name)
    ticks=phase['end_tick']-phase['start_tick'];insts=sum(counts)
    if stats['simTicks']!=ticks or stats['simInsts']!=insts:
        raise RuntimeError(name+': ROI stats mismatch')
    net=json.loads((out/'config.json').read_text())['system']['ruby']['network']
    if (len(net['routers'])!=rows**2 or net['vcs_per_vnet']!=6 or
        net['srfd_reserved_vcs']!=6-cap or net['srfd_directional_storage']!=directional):
        raise RuntimeError(name+': network configuration mismatch')
    if mode!='baseline' and actions['max_stored']>cap:raise RuntimeError('cap exceeded')
    result=dict(name=name,mode=mode,cores=rows**2,mem_size='16GB',
                access_backing_store=False,srfd_directional_storage=directional,
                storage_limit=cap,roi_ticks=ticks,aggregate_instructions=insts,
                roi_instructions=counts,aggregate_ipc=insts/(ticks/500),
                average_ipc_per_core=insts/(ticks/500)/(rows**2),
                llc_completion_mean_cycles=paper['combined_mean_cycles'],
                message_stall_ticks=paper['message_stall_ticks'],srfd=actions,
                host_seconds=stats['hostSeconds'],host_inst_rate=stats['hostInstRate'])
    (out/'analysis.json').write_text(json.dumps(result,indent=2))
    return result

try:
    launch('create_2x2_16gb',2,action='create')
    launch('validate_2x2_16gb',2,kvm=True,roi=1,warmup=0)
    launch('smoke_2x2_16gb',2,mode='cbdb-aggressive',cap=4,directional=True,roi=1000000)
    analyze('smoke_2x2_16gb','cbdb-aggressive',2,1000000,True,4)
    launch('create_8x8_16gb',8,action='create')
    verified=launch('validate_8x8_16gb',8,kvm=True,roi=1,warmup=0)
    if len(verified.get('native_output_matches',[]))!=64 or not all(verified['native_output_matches']):
        raise RuntimeError('64-core native output mismatch')
    cases=[('local_baseline','baseline',6,False),
           ('local_cbdb_cap6','cbdb-aggressive',6,False),
           ('local_cbdb_cap4','cbdb-aggressive',4,False),
           ('directional_baseline','baseline',4,True),
           ('directional_cbdb_cap4','cbdb-aggressive',4,True)]
    if a.directional_cap5:cases.append(('directional_cbdb_cap5','cbdb-aggressive',5,True))
    for label,mode,cap,directional in cases:
        name='smoke_8x8_'+label
        launch(name,8,mode=mode,cap=cap,directional=directional,roi=100000,warmup=10000)
        analyze(name,mode,8,100000,directional,cap)
    results=[];baselines={}
    for label,mode,cap,directional in cases:
        name='roi_8x8_'+label
        launch(name,8,mode=mode,cap=cap,directional=directional)
        row=analyze(name,mode,8,a.roi_insts,directional,cap)
        if mode=='baseline':baselines[directional]=row
        else:
            base=baselines[directional]
            row['ipc_ratio_vs_matched_baseline']=row['aggregate_ipc']/base['aggregate_ipc']
            row['llc_penalty_ratio_vs_matched_baseline']=row['llc_completion_mean_cycles']/base['llc_completion_mean_cycles']
        results.append(row)
        (HERE/'results.json').write_text(json.dumps(results,indent=2))
    state('complete',cases=len(results),cap6_directional='unsupported: escape VC limits retention to 5')
except BaseException as error:
    state('failed',error=str(error))
    raise
