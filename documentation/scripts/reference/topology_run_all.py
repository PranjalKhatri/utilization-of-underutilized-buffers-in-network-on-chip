"""Run cap-five corners and paired cap-four topology comparisons serially."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import srfd_eval

ORIGINAL = ROOT / 'PAPER_TESTS/namd_compute_roi_20261006'
HEADROOM = ROOT / 'PAPER_TESTS/srfd_headroom_20261006'
CURRENT_RUNNER = HERE / 'run_checkpoint.py'
OLD_RUNNER = HEADROOM / 'run_checkpoint.py'
RESULTS = HERE / 'results.json'


def save(stage, **fields):
    (HERE / 'workflow_status.json').write_text(json.dumps({
        'stage': stage, **fields
    }, indent=2))


def wait_memory(case):
    while True:
        text = Path('/proc/meminfo').read_text()
        available = int(re.search(r'^MemAvailable:\s+(\d+)', text, re.M)[1]) * 1024
        if available >= 9 * 1024**3:
            return
        save('waiting_for_memory', next_case=case,
             available_bytes=available, required_bytes=9 * 1024**3)
        time.sleep(30)


def launch(name, runner, args):
    wait_memory(name)
    save('running', case=name)
    command = [sys.executable, str(runner), *args,
               '--timeout=86400']
    with (HERE / f'{name}_launcher.log').open('w') as log:
        subprocess.run(command, cwd=ROOT,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    verification = json.loads((HERE / name / 'verification.json').read_text())
    if not verification['passed']:
        raise RuntimeError(f'{name}: verification failed')
    return verification


def analyze(name, mode, topology, cap, expected_dirs):
    out = HERE / name
    verification = json.loads((out / 'verification.json').read_text())
    status = verification['status']
    if status.get('events'):
        raise RuntimeError(f'{name}: selected computation ended during ROI')
    phase = status['phases']['roi']
    counts = phase['instructions']
    if len(counts) != 16 or min(counts) < 20_000_000:
        raise RuntimeError(f'{name}: incomplete per-core ROI')
    stats = srfd_eval.parse_stats(str(out / 'roi_stats.txt'))
    srfd = srfd_eval.aggregate_srfd(stats, mode)
    paper = srfd_eval.aggregate_paper_metrics(stats)
    srfd_eval.validate_srfd_accounting(srfd, paper, name)
    ticks = phase['end_tick'] - phase['start_tick']
    insts = sum(counts)
    if stats['simTicks'] != ticks or stats['simInsts'] != insts:
        raise RuntimeError(f'{name}: ROI counter mismatch')
    config = json.loads((out / 'config.json').read_text())['system']
    network = config['ruby']['network']
    dirs = sorted(int(re.search(r'routers(\d+)$', link['int_node'])[1])
                  for link in network['ext_links']
                  if 'dir_cntrl' in link['ext_node'])
    if dirs != expected_dirs:
        raise RuntimeError(f'{name}: directory placement {dirs}, expected {expected_dirs}')
    if network['vcs_per_vnet'] != 6 or network['srfd_reserved_vcs'] != 6-cap:
        raise RuntimeError(f'{name}: VC configuration mismatch')
    if mode != 'baseline' and srfd['max_stored'] > cap:
        raise RuntimeError(f'{name}: storage cap exceeded')
    result = {
        'name': name, 'mode': mode, 'topology': topology,
        'directory_routers': dirs, 'storage_limit': cap,
        'roi_ticks': ticks, 'roi_instructions': counts,
        'aggregate_instructions': insts,
        'aggregate_ipc': insts / (ticks / 500),
        'average_ipc_per_core': insts / (ticks / 500) / 16,
        'llc_completion_mean_cycles': paper['combined_mean_cycles'],
        'srfd': srfd, 'lifecycle_validated': paper['lifecycle_accounting_verified'],
        'host_seconds': stats['hostSeconds'],
        'host_inst_rate': stats['hostInstRate'],
    }
    (out / 'analysis.json').write_text(json.dumps(result, indent=2))
    return result


def restore_args(checkpoint, output, topology, mode, reserved, warmup, roi,
                 kvm=False):
    args = [
        '--action=restore', '--mesh-rows=4', f'--checkpoint={checkpoint}',
        f'--output={output}', f'--mode={mode}',
        f'--srfd-reserved-vcs={reserved}', f'--warmup-insts={warmup}',
        f'--roi-insts={roi}', '--roi-seconds=' + ('600' if kvm else '120'),
    ]
    if topology:
        args.append(f'--topology={topology}')
    if kvm:
        args.append('--roi-cpu=kvm')
    return args


rows = []
try:
    # Five retained blocks on the already validated six-VC corner topology.
    cap5_name = 'corners_cbdb_aggressive_cap5'
    launch(cap5_name, OLD_RUNNER, restore_args(
        HEADROOM / 'cpt_4x4_compute', HERE / cap5_name, None,
        'cbdb-aggressive', 1, 100_000, 20_000_000))
    cap5 = analyze(cap5_name, 'cbdb-aggressive', 'MeshDirCorners_XY', 5,
                   [0, 3, 12, 15])
    prior_baseline = json.loads(
        (ORIGINAL / 'roi_4x4_baseline/analysis.json').read_text())
    cap5['ipc_ratio_vs_existing_corners_baseline'] = (
        cap5['aggregate_ipc'] / prior_baseline['aggregate_ipc'])
    cap5['target_time_ratio_vs_existing_corners_baseline'] = (
        prior_baseline['roi_ticks'] / cap5['roi_ticks'])
    rows.append(cap5)
    RESULTS.write_text(json.dumps(rows, indent=2))

    cases = [
        ('mesh_xy', 'Mesh_XY', [0, 0, 0, 0]),
        ('medials', 'MeshDirMedials_XY', [5, 6, 9, 10]),
    ]
    for label, topology, expected_dirs in cases:
        checkpoint = HERE / f'cpt_4x4_{label}'
        launch(f'create_{label}', CURRENT_RUNNER, [
            '--action=create', '--mesh-rows=4', f'--topology={topology}',
            '--mode=baseline', f'--checkpoint={checkpoint}',
            f'--output={HERE / ("create_" + label)}', '--roi-seconds=120'])

        validation_name = f'validate_{label}_kvm'
        validation = launch(validation_name, CURRENT_RUNNER, restore_args(
            checkpoint, HERE / validation_name, topology, 'baseline',
            2, 0, 1, kvm=True))
        matches = validation.get('native_output_matches', [])
        if len(matches) != 16 or not all(matches):
            raise RuntimeError(f'{validation_name}: native output mismatch')

        smoke_name = f'smoke_{label}_cbdb_cap4'
        launch(smoke_name, CURRENT_RUNNER, restore_args(
            checkpoint, HERE / smoke_name, topology, 'cbdb-aggressive',
            2, 10_000, 100_000))

        pair = []
        for mode in ('baseline', 'cbdb-aggressive'):
            name = f'roi_{label}_{mode.replace("-", "_")}_cap4'
            launch(name, CURRENT_RUNNER, restore_args(
                checkpoint, HERE / name, topology, mode,
                2, 100_000, 20_000_000))
            row = analyze(name, mode, topology, 4, expected_dirs)
            rows.append(row)
            pair.append(row)
            RESULTS.write_text(json.dumps(rows, indent=2))
        baseline, variant = pair
        variant['ipc_ratio_vs_topology_baseline'] = (
            variant['aggregate_ipc'] / baseline['aggregate_ipc'])
        variant['target_time_ratio_vs_topology_baseline'] = (
            baseline['roi_ticks'] / variant['roi_ticks'])
        RESULTS.write_text(json.dumps(rows, indent=2))

    save('complete', cases=len(rows))
except BaseException as error:
    save('failed', error=str(error))
    (HERE / 'RUN_FAILED.json').write_text(json.dumps({'error': str(error)}, indent=2))
    raise
