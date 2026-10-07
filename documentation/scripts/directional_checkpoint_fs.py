"""MOESI/Garnet full-system runner using guest workbegin/workend markers.

Reuse gem5's legacy FS construction, with KVM boot and O3 ROI execution.
All output is isolated under the supplied gem5 outdir; disks use COW overlays.
"""
import argparse
import json
import runpy
import shutil
import sys
from pathlib import Path

import m5
from m5.objects import X86O3CPU

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'configs'))
from common import Simulation

parser = argparse.ArgumentParser()
parser.add_argument('--action', choices=['create','restore'], required=True)
parser.add_argument('--checkpoint-dir', required=True)
parser.add_argument('--warmup-insts', type=int, default=100000)
parser.add_argument('--roi-insts', type=int, default=100000000)
parser.add_argument('--srfd-reserved-vcs', type=int, default=0)
parser.add_argument('--srfd-directional-storage', action='store_true')
parser.add_argument('--no-srfd-directional-storage', action='store_false', dest='srfd_directional_storage')
parser.add_argument('--mesh-rows', type=int, default=2)
parser.add_argument('--topology', default='MeshDirCorners_XY',
                    choices=['MeshDirCorners_XY', 'Mesh_XY',
                             'MeshDirMedials_XY'])
parser.add_argument('--srfd-mode', default='baseline', choices=['baseline', 'db-aggressive', 'cbdb-aggressive', 'cbdb-defensive'])
parser.add_argument('--kernel', required=True)
parser.add_argument('--disk-image', required=True)
parser.add_argument('--payload-image')
parser.add_argument('--script', required=True)
parser.add_argument('--roi-cpu', choices=['o3','kvm'], default='o3')
parser.add_argument('--smoke-only', action='store_true')
parser.add_argument('--trace-roi', action='store_true')
parser.add_argument('--boot-seconds', type=float, default=600.0)
parser.add_argument('--roi-seconds', type=float, default=120.0)
parser.add_argument('--post-roi-seconds', type=float, default=10.0)
args = parser.parse_args()
if args.mesh_rows < 2 or args.warmup_insts < 0 or args.roi_insts <= 0 or min(args.boot_seconds,args.roi_seconds,args.post_roi_seconds) <= 0:
    parser.error('mesh must be at least 2x2 and time bounds positive')
for path in [args.kernel,args.disk_image,args.script,args.payload_image]:
    if path and not Path(path).is_file():
        parser.error(f'missing resource: {path}')
cores = args.mesh_rows ** 2
OUT = Path(m5.options.outdir)
status = {'status': 'configuring', 'cores': cores, 'mesh_rows': args.mesh_rows,
          'topology': args.topology, 'srfd_mode': args.srfd_mode,
          'srfd_reserved_vcs': args.srfd_reserved_vcs,
          'srfd_directional_storage': args.srfd_directional_storage, 'srfd_storage_limit': 6-args.srfd_reserved_vcs, 'events': [],
          'roi_cpu_type': 'X86O3CPU' if args.roi_cpu=='o3' else 'X86KvmCPU',
          'disk_io': 'PIO'}


def save():
    (OUT / 'fs_roi_status.json').write_text(json.dumps(status, indent=2))


def simulate_phase(name, seconds, expected, cpus):
    status['status'] = name
    save()
    deadline = m5.curTick() + m5.ticks.fromSeconds(float(seconds))
    quantum = m5.ticks.fromSeconds(2.0 if name in ('boot_and_setup','compute_preparation') or args.roi_cpu=='kvm' else 0.001)
    while True:
        event = m5.simulate(min(quantum, deadline - m5.curTick()))
        cause = event.getCause()
        if cause != 'simulate() limit reached' or m5.curTick() >= deadline:
            break
        status['active_phase'] = {'name': name, 'tick': m5.curTick(),
            'instructions': [cpu.totalInsts() for cpu in cpus]}
        save()
    status.pop('active_phase', None)
    status['events'].append({'phase': name, 'tick': m5.curTick(), 'cause': cause,
                             'code': event.getCode()})
    save()
    print(f'FS_PHASE {name}: {cause} at {m5.curTick()}', flush=True)
    expected_code = 0x434f4d50 if (name == 'compute_preparation' and expected == 'workbegin') or name.startswith('selected_compute_end_') else 0
    if cause != expected or event.getCode() != expected_code:
        if name == 'roi':
            m5.stats.dump()
            shutil.copyfile(OUT / 'stats.txt', OUT / 'diagnostic_stats.txt')
        raise RuntimeError(f'{name}: expected {expected!r}, got {cause!r}, code={event.getCode()}')


def run_fs(options, root, system, future_class):
    assert future_class is None
    timing_cpus = []
    for i, old in enumerate(system.cpu):
        old.usePerf = False
        old.usePerfOverflow = False
        cpu = X86O3CPU(cpu_id=i, switched_out=True, system=system,
                       clk_domain=system.cpu_clk_domain, isa=old.isa)
        cpu.createThreads()
        timing_cpus.append(cpu)
    system.switch_cpus = timing_cpus
    # KVM boot uses parallel queues. Restore consolidates queues before
    # Ruby replay and the switch to the O3 CPUs, which all use queue zero.
    if args.action == 'restore' and args.roi_cpu == 'o3':
        for cpu in system.cpu:
            cpu.eventq_index = 0
        root.sim_quantum = 0
    system.exit_on_work_items = True
    if args.action == 'create':
        if args.srfd_mode != 'baseline':
            raise RuntimeError('Only baseline may create the checkpoint')
        m5.instantiate()
        simulate_phase('compute_preparation', args.boot_seconds, 'workbegin', system.cpu)
        status['compute_marker_tick'] = m5.curTick()
        status['status'] = 'checkpointing'
        save()
        m5.checkpoint(args.checkpoint_dir)
        status['checkpoint_tick'] = m5.curTick()
        status['checkpoint_dir'] = args.checkpoint_dir
        status['compute_boundary'] = {'symbol':'ComputeList::runComputes(PatchList*)','entry_offset':0x3830,'call':7,'main_return_offset':0x1625,'completed_calls_before_boundary':6}
        status['status'] = 'checkpoint_complete'
        save()
        Path(args.checkpoint_dir, 'post_input_metadata.json').write_text(json.dumps(status,indent=2))
        print('POST_INPUT_CHECKPOINT_COMPLETE', json.dumps(status), flush=True)
        return
    m5.instantiate(args.checkpoint_dir)
    # Startup is deferred until simulate(); initialize pipeline stages before
    # takeOverFrom resets the O3 fetch priority list.
    startup_event=m5.simulate(0)
    if startup_event.getCause()!='simulate() limit reached':
        raise RuntimeError('Unexpected restore startup exit: '+startup_event.getCause())
    status['restored_from'] = args.checkpoint_dir
    if args.roi_cpu == 'kvm':
        for i in range(cores):
            simulate_phase('selected_compute_end_'+str(i), args.roi_seconds, 'workend', system.cpu)
        simulate_phase('restored_full_validation', args.roi_seconds, 'workend', system.cpu)
        simulate_phase('guest_validation', args.post_roi_seconds, 'm5_exit instruction encountered', system.cpu)
        status['status'] = 'full_validation_complete'
        save()
        return
    m5.switchCpus(system, list(zip(system.cpu,system.switch_cpus)))
    cpus=list(system.switch_cpus)
    def instruction_phase(target, name):
        status['status']=name
        save()
        initial=[cpu.getCurrentInstCount(0) for cpu in cpus]
        pending=set(range(len(cpus)))
        causes={f'POSTINPUT {name} CPU {i}':i for i in pending}
        for i,cpu in enumerate(cpus):cpu.scheduleInstStop(0,target,f'POSTINPUT {name} CPU {i}')
        begin=m5.curTick()
        deadline=begin+m5.ticks.fromSeconds(float(args.roi_seconds))
        poll=m5.ticks.fromSeconds(0.0001)
        while pending:
            event=m5.simulate(min(poll,max(0,deadline-m5.curTick())))
            cause=event.getCause()
            counts=[cpu.getCurrentInstCount(0)-n for cpu,n in zip(cpus,initial)]
            if cause in causes:pending.discard(causes[cause])
            elif cause!='simulate() limit reached':raise RuntimeError(f'{name} incomplete: {cause}')
            if m5.curTick()>=deadline and pending:raise RuntimeError(f'{name} exceeded simulated-time bound')
            status['active_phase']={'name':name,'tick':m5.curTick(),'pending_cpus':sorted(pending),'instructions':counts}
            save()
        status.setdefault('phases',{})[name]={'requested_per_core':target,'instructions':counts,'start_tick':begin,'end_tick':m5.curTick()}
        status.pop('active_phase',None)
        save()
    if args.warmup_insts:instruction_phase(args.warmup_insts,'warmup')
    if args.trace_roi:
        m5.trace.output(str(OUT/'exec_trace.log'))
        m5.debug.flags['Exec'].enable()
        m5.trace.enable()
    m5.stats.reset()
    instruction_phase(args.roi_insts,'roi')
    m5.stats.dump()
    shutil.copyfile(OUT/'stats.txt',OUT/'roi_stats.txt')
    status['status']='complete'
    save()
    print('POST_INPUT_ROI_COMPLETE',json.dumps(status),flush=True)


Simulation.run = run_fs
legacy = ROOT / 'configs/deprecated/example/fs.py'
sys.argv = [str(legacy), '--cpu-type=X86KvmCPU', f'--num-cpus={cores}',
    '--num-dirs=4', f'--num-l2caches={cores}', '--ruby', '--access-backing-store',
    '--network=garnet', f'--topology={args.topology}', f'--mesh-rows={args.mesh_rows}',
    '--vcs-per-vnet=6', '--buffers-per-data-vc=5', '--link-width-bits=128',
    '--router-latency=2', '--routing-algorithm=1', f'--srfd-mode={args.srfd_mode}', f'--srfd-reserved-vcs={args.srfd_reserved_vcs}',
    '--mem-size=3GB', '--sys-clock=2GHz', '--cpu-clock=2GHz', '--ruby-clock=2GHz',
    '--l1d_size=16kB', '--l1d_assoc=4', '--l1i_size=16kB', '--l1i_assoc=4',
    '--l2_size=128kB', '--l2_assoc=8', f'--kernel={args.kernel}',
    f'--disk-image={args.disk_image}', '--root-device=/dev/hda1', f'--script={args.script}',
    '--command-line=earlyprintk=ttyS0 console=ttyS0 lpj=7999923 root=/dev/hda1 rw ide_core.nodma=0.0 ide_core.nodma=0.1 devtmpfs.mount=1 init=/bin/bash HOME=/root -- -i']
if args.srfd_directional_storage:
    sys.argv.append('--srfd-directional-storage')
if args.payload_image:
    sys.argv.append(f'--disk-image={args.payload_image}')
try:
    runpy.run_path(str(legacy), run_name='__m5_main__')
except BaseException as error:
    status['status'] = 'failed'
    status['error'] = str(error)
    save()
    raise
