import hashlib,json,shutil,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
stage=HERE/'payload_compute.files';stage.mkdir(exist_ok=False)
(stage/'binaries').mkdir()
shutil.copy2(ROOT/'cpu2017/cpu2017/binaries/namd',stage/'binaries/namd')
shutil.copy2(ROOT/'util/m5/build/x86/out/m5',stage/'binaries/m5')
shutil.copy2(HERE/'compute_gate.so',stage/'binaries/compute_gate.so')
shutil.copytree(ROOT/'cpu2017/cpu2017/data/namd',stage/'data/namd')
image=HERE/'payload_compute.img'
with image.open('xb') as f:f.truncate(128*1024**2)
subprocess.run(['mke2fs','-q','-t','ext2','-F','-L','COMPUTE','-d',str(stage),str(image)],check=True)
manifest={str(p.relative_to(stage)):hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.rglob('*') if p.is_file()}
(HERE/'payload_compute_manifest.json').write_text(json.dumps(manifest,indent=2))
