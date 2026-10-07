import os,subprocess
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[1];OUT=P/'native_profile'
env=dict(os.environ,LD_PRELOAD=str(P/'compute_gate.so'),NAMD_GATE_FILE=str(OUT/'gate.bin'),NAMD_GATE_EXPECTED='1',NAMD_GATE_WORKER='0',NAMD_GATE_NATIVE_TEST='1')
cmd=['perf','record','--clockid','mono','-e','instructions:u','-c','1000000','-o',str(OUT/'perf.data'),'--','env']+[k+'='+env[k] for k in ['LD_PRELOAD','NAMD_GATE_FILE','NAMD_GATE_EXPECTED','NAMD_GATE_WORKER','NAMD_GATE_NATIVE_TEST']]+[str(ROOT/'cpu2017/cpu2017/binaries/namd'),'--input',str(ROOT/'cpu2017/cpu2017/data/namd/all/input/namd.input'),'--iterations','2','--output',str(OUT/'result.output')]
with (OUT/'stdout.log').open('w') as out,(OUT/'stderr.log').open('w') as err:
 code=subprocess.run(cmd,env=os.environ,stdout=out,stderr=err).returncode
if code:raise SystemExit(code)
with (OUT/'samples.txt').open('w') as out:
 subprocess.run(['perf','script','-i',str(OUT/'perf.data'),'-F','time,period,ip,sym'],stdout=out,check=True)
