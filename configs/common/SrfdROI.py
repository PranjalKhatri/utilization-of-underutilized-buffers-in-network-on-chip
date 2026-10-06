"""Equal per-core instruction windows for single-thread SE SRFD experiments.

Each CPU pauses at its target, so the measured duration is a makespan for
approximately equal work. Timing warmup, unlike atomic fast-forward, exercises
Ruby. A guest exit before any target invalidates the run.
"""
import json
import os

import m5


def run_roi(options, system, switch_cpus, maxtick):
    report = {"status": "running", "phases": {}}
    path = os.path.join(m5.options.outdir, "roi_status.json")

    def save():
        with open(path, "w", encoding="utf-8") as output:
            json.dump(report, output, indent=2)

    def activate(cpus):
        for cpu in cpus:
            cpu.setThreadActive(0, True)

    def phase(cpus, instructions, name):
        starts = [cpu.getCurrentInstCount(0) for cpu in cpus]
        pending = set(range(len(cpus)))
        causes = {f"SRFD {name} CPU {index}": index for index in pending}
        for index, cpu in enumerate(cpus):
            cpu.scheduleInstStop(0, instructions, f"SRFD {name} CPU {index}")
        activate(cpus)
        start_tick = m5.curTick()
        # Poll even if no instruction event arrives. A halted guest must not
        # leave the harness waiting until MaxTick on CPU progress events.
        poll_ticks = max(1, int(m5.ticks.fromSeconds(0.0001)))
        while pending:
            for index in pending:
                if cpus[index].isThreadHalted(0):
                    raise RuntimeError(f"CPU {index} exited before {name} target")
            event = m5.simulate(min(poll_ticks, max(0, maxtick - m5.curTick())))
            cause = event.getCause()
            if cause == "simulate() limit reached" and m5.curTick() < maxtick:
                report["active_phase"] = {
                    "name": name, "tick": m5.curTick(),
                    "pending_cpus": sorted(pending),
                    "instructions": [cpu.getCurrentInstCount(0) - start
                                     for cpu, start in zip(cpus, starts)],
                }
                save()
                continue
            if cause not in causes or causes[cause] not in pending:
                raise RuntimeError(f"Incomplete {name}: {cause}")
            index = causes[cause]
            cpus[index].setThreadActive(0, False)
            pending.remove(index)
        counts = [cpu.getCurrentInstCount(0) - start
                  for cpu, start in zip(cpus, starts)]
        # Instruction events are serviced within a commit batch on O3 CPUs.
        if any(count < instructions or count > instructions + 64 for count in counts):
            raise RuntimeError(f"Unexpected {name} instruction counts: {counts}")
        report["phases"][name] = {
            "requested_instructions": instructions,
            "instructions": counts, "start_tick": start_tick,
            "end_tick": m5.curTick(),
        }
        report.pop("active_phase", None)
        save()

    try:
        cpus = list(system.cpu)
        if switch_cpus:
            if not options.fast_forward:
                raise RuntimeError("SRFD CPU switching requires instruction fast-forward")
            phase(cpus, int(options.fast_forward), "fast_forward")
            # SimpleCPU instruction events can stop inside an x86 microcode
            # sequence. Its drain cannot finish while its tick is suspended.
            # Reactivate before draining so every macro-instruction completes.
            activate(cpus)
            m5.switchCpus(system, list(zip(cpus, switch_cpus)))
            cpus = list(switch_cpus)
        if options.srfd_warmup_insts:
            phase(cpus, options.srfd_warmup_insts, "warmup")
        # With no preparatory phase, startup has not run yet. Draining a
        # pristine O3 pipeline before startup corrupts its ROB state.
        if switch_cpus or options.srfd_warmup_insts:
            m5.drain()
        m5.stats.reset()
        phase(cpus, options.srfd_roi_insts, "roi")
        m5.stats.dump()
        report["status"] = "complete"
        save()
        print(f"SRFD ROI completed on all {len(cpus)} CPUs @ tick {m5.curTick()}")
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = str(error)
        save()
        raise
