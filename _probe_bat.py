import sys, os, glob
sys.path.insert(0, r"C:\Users\romai\AppData\Local\Temp\bat_wheel")
from pathlib import Path
from blender_asset_tracer.blendfile import open_cached

files = glob.glob(r"C:\Users\romai\Documents\Projets\26 - Bezier Quest\SP*.blend")
target = "SP - Chord-length Parametrization Cyclic Unclamped PROTO"
for f in files:
    with open_cached(Path(f)) as bf:
        linked = 0
        local_hit = False
        linked_hit = False
        samples = []
        for nt in bf.find_blocks_from_code(b"NT"):
            name = nt.id_name
            if name is None:
                continue
            lib = nt[b"id", b"lib"]
            if lib:
                linked += 1
                stored = name.decode(errors="ignore")
                if target in stored:
                    linked_hit = True
                if len(samples) < 3:
                    samples.append(stored)
            else:
                stored = name.decode(errors="ignore")[2:]  # strip NT
                if stored == target:
                    local_hit = True
        print(f"{os.path.basename(f)}: local={local_hit} linked={linked_hit} (linked blocks={linked}) samples={samples}")
