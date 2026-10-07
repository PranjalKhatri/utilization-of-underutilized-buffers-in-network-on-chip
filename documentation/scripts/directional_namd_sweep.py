#!/usr/bin/env python3
"""Validate cold NAMD checkpoints, then run the six-VC directional comparison."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
output = args.output.resolve()
if not output.is_relative_to(ROOT / 'PAPER_TESTS'):
    parser.error('outputs must be under PAPER_TESTS')
output.mkdir(parents=True, exist_ok=True)
runner = Path(__file__).with_name('directional_namd.py')
checkpoints = ROOT / 'PAPER_TESTS/namd_compute_roi_20261006'
sys.path.insert(0, str(ROOT))
import srfd_eval

def status(stage, **fields):
    (output / 'workflow_status.json').write_text(json.dumps(
        dict(stage=stage, **fields), indent=2))

def launch(name, rows, mode='baseline', reserve=2, enabled=False,
           warmup=100000, roi=20000000, kvm=False, trial=False):
    existing=output/name/'verification.json'
    if kvm and trial and existing.exists():
        saved=json.loads(existing.read_text())
        manifest=json.loads((output/name/'manifest.json').read_text())
        with (ROOT/'build/X86_MOESI_CMP_directory/gem5.opt').open('rb') as binary:
            current=hashlib.file_digest(binary,'sha256').hexdigest()
        if (saved['passed'] and all(saved.get('native_output_matches',[]))
                and len(saved.get('native_output_matches',[]))==rows**2
                and manifest['binary_sha256']==current):
            return saved
        raise RuntimeError('existing compatibility result does not match this binary')
    # Run serially and wait for sufficient host memory without busy polling.
    while True:
        info = Path('/proc/meminfo').read_text().splitlines()
        available = int(next(line for line in info if line.startswith('MemAvailable:')).split()[1])
        if available >= 9 * 1024**2: break
        status('waiting_for_memory', case=name, available_kib=available)
        time.sleep(30)
    status('running', case=name)
    cmd = [sys.executable, str(runner), '--action=restore',
           f'--checkpoint={checkpoints / f"cpt_{rows}x{rows}_compute"}',
           f'--output={output/name}', f'--mesh-rows={rows}', f'--mode={mode}',
           f'--srfd-reserved-vcs={reserve}', f'--warmup-insts={warmup}',
           f'--roi-insts={roi}', f'--roi-cpu={"kvm" if kvm else "o3"}',
           '--roi-seconds=600' if kvm else '--roi-seconds=120', '--timeout=86400']
    if enabled: cmd.append('--srfd-directional-storage')
    if trial: cmd.append('--compatibility-trial')
    with (output / f'{name}_launcher.log').open('w') as log:
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=log,
                       stderr=subprocess.STDOUT,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    result = json.loads((output/name/'verification.json').read_text())
    if not result['passed']: raise RuntimeError(name + ': verification failed')
    return result

def analyze(name, mode):
    out = output/name
    verification = json.loads((out/'verification.json').read_text())
    phase = verification['status']['phases']['roi']
    if verification['status']['events']: raise RuntimeError('measurement escaped computation')
    stats = srfd_eval.parse_stats(str(out/'roi_stats.txt'))
    actions = srfd_eval.aggregate_srfd(stats, mode)
    paper = srfd_eval.aggregate_paper_metrics(stats)
    srfd_eval.validate_srfd_accounting(actions, paper, name)
    ticks = phase['end_tick']-phase['start_tick']
    instructions = sum(phase['instructions'])
    if ticks != stats['simTicks'] or instructions != stats['simInsts']:
        raise RuntimeError('ROI counter mismatch')
    network = json.loads((out/'config.json').read_text())['system']['ruby']['network']
    if network['vcs_per_vnet'] != 6 or not network['srfd_directional_storage']:
        raise RuntimeError('directional six-VC configuration mismatch')
    result = dict(name=name, mode=mode, storage_limit=6-network['srfd_reserved_vcs'],
                  srfd_directional_storage=True, roi_ticks=ticks,
                  aggregate_instructions=instructions,
                  roi_instructions=phase['instructions'],
                  aggregate_ipc=instructions/(ticks/500),
                  average_ipc_per_core=instructions/(ticks/500)/len(phase['instructions']),
                  llc_completion_mean_cycles=paper['combined_mean_cycles'],
                  message_stall_ticks=paper['message_stall_ticks'],
                  srfd=actions, host_seconds=stats['hostSeconds'],
                  host_inst_rate=stats['hostInstRate'])
    directional = {}
    for suffix in ('lease_requests','lease_grants','lease_denials','lease_releases',
                   'opening_leases','closing_leases','transfer_flits',
                   'reclaim_requests','reclaim_releases'):
        directional[suffix] = sum(v for n,v in stats.items()
                                  if '.srfd_' in n and n.endswith('.'+suffix))
    if directional['opening_leases']+directional['lease_grants'] != (
            directional['lease_releases']+directional['closing_leases']):
        raise RuntimeError('lease lifecycle mismatch')
    result['directional'] = directional
    (out/'analysis.json').write_text(json.dumps(result,indent=2))
    return result

try:
    for rows in (2,4):
        launch(f'compat_{rows}x{rows}', rows, warmup=0, roi=1, kvm=True, trial=True)
    for mode,cap in [('baseline',4),('cbdb-aggressive',4),('cbdb-aggressive',5)]:
        name=f'smoke_2x2_{mode}_cap{cap}'
        launch(name,2,mode,6-cap,True,warmup=10000,roi=100000)
        analyze(name,mode)
    # A matched baseline is required because ordinary traffic loses one VC
    # to the dedicated escape path in every feature-enabled measurement.
    results=[]
    for mode,cap in [('baseline',4),('cbdb-aggressive',4),('cbdb-aggressive',5)]:
        name=f'roi_4x4_{mode}_cap{cap}'
        launch(name,4,mode,6-cap,True)
        result=analyze(name,mode)
        if results:
            result['ipc_ratio_vs_directional_baseline']=result['aggregate_ipc']/results[0]['aggregate_ipc']
        results.append(result)
        (output/'results.json').write_text(json.dumps(results,indent=2))
    status('complete', cases=len(results), cap6='unavailable: six VCs include one unborrowable escape VC')
except BaseException as error:
    status('failed', error=str(error))
    raise
