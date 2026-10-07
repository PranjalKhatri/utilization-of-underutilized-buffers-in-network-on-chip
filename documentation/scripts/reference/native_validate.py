import concurrent.futures,json,os,struct,subprocess,time
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
BIN=ROOT/'cpu2017/cpu2017/binaries/namd';INPUT=ROOT/'cpu2017/cpu2017/data/namd/all/input/namd.input'
OUT=P/'native_validation';OUT.mkdir(exist_ok=False)
def run(d,env):
 d.mkdir(exist_ok=True)
 with (d/'stdout.log').open('w') as out,(d/'stderr.log').open('w') as err:
  return subprocess.run([str(BIN),'--input',str(INPUT),'--iterations','2','--output',str(d/'result.output')],env=env,stdout=out,stderr=err).returncode
start=time.monotonic();gold=run(OUT,os.environ)
assert gold==0
shared=OUT/'gate.bin';shared.write_bytes(bytes(4096))
def worker(i):
 return run(OUT/str(i),dict(os.environ,LD_PRELOAD=str(P/'compute_gate.so'),NAMD_GATE_FILE=str(shared),NAMD_GATE_EXPECTED='4',NAMD_GATE_WORKER=str(i),NAMD_GATE_NATIVE_TEST='1'))
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:codes=list(pool.map(worker,range(4)))
g=shared.read_bytes();done,go=struct.unpack_from('<II',g);offsets=struct.unpack_from('<4Q',g,264)
matches=[(OUT/str(i)/'result.output').read_bytes()==(OUT/'result.output').read_bytes() for i in range(4)]
logs=[(OUT/str(i)/'stderr.log').read_text() for i in range(4)]
valid_counts=all(log.count('COMPUTE_ENTER ')==12 and log.count('COMPUTE_EXIT ')==12 and log.count('COMPUTE_SELECTED ')==1 for log in logs)
result={'passed':gold==0 and codes==[0]*4 and done==4 and go==1 and offsets==(0x1625,)*4 and all(matches) and valid_counts,'returncodes':codes,'arrivals':done,'released':go,'return_offsets':offsets,'native_output_matches':matches,'call_count_validated':valid_counts,'seconds':time.monotonic()-start}
(OUT/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2),flush=True)
if not result['passed']:raise SystemExit(1)
