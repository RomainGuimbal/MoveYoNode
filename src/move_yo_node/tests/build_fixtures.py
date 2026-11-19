"""Build a multi-level .blend hierarchy for the MoveYoNode test suite.

The hierarchy mirrors a real project:

    SP Level 0.blend   BaseGroup, LeafGroup          (primitives, no deps)
    SP Level 1.blend   MidGroup  -> links BaseGroup
    SP Level 2.blend   TopGroup  -> links MidGroup
    SP Level 3.blend   SceneGroup -> links TopGroup

Each level links from the level below, so a group can only be moved up once
everything it depends on has been moved first.

Run inside Blender:
    blender --background --factory-startup --python tests/build_fixtures.py -- <outdir>
"""

import sys
from pathlib import Path

import bpy


def _new_group(name: str) -> bpy.types.NodeTree:
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    ng.use_fake_user = True
    return ng


def _add_group_node(parent: bpy.types.NodeTree, child: bpy.types.NodeTree, name: str):
    node = parent.nodes.new("GeometryNodeGroup")
    node.node_tree = child
    node.name = name
    return node


def _save(path: Path):
    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def _link(path: Path, names: list[str]) -> list:
    with bpy.data.libraries.load(str(path), link=True, recursive=False) as (_, data_to):
        data_to.node_groups = names
    return data_to.node_groups


def build(outdir: Path, prefix: str = "SP", suffix: str = "Level") -> dict:
    """Create the level files and return a description of what was built."""
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {lvl: outdir / f"{prefix} {suffix} {lvl}.blend" for lvl in range(4)}

    # ── Level 0: primitives, no dependencies ──────────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _new_group("BaseGroup")
    _new_group("LeafGroup")
    _save(paths[0])

    # ── Level 1: links BaseGroup ──────────────────────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)
    base = _link(paths[0], ["BaseGroup"])[0]
    mid = _new_group("MidGroup")
    _add_group_node(mid, base, "BaseGroupNode")
    _save(paths[1])

    # ── Level 2: links MidGroup ───────────────────────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mid_linked = _link(paths[1], ["MidGroup"])[0]
    top = _new_group("TopGroup")
    _add_group_node(top, mid_linked, "MidGroupNode")
    _save(paths[2])

    # ── Level 3: links TopGroup ───────────────────────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)
    top_linked = _link(paths[2], ["TopGroup"])[0]
    scene = _new_group("SceneGroup")
    _add_group_node(scene, top_linked, "TopGroupNode")
    _save(paths[3])

    return {"paths": paths, "outdir": outdir}


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1 :] if "--" in argv else []
    outdir = Path(args[0]) if args else Path.cwd() / "fixtures"
    info = build(outdir)
    for lvl, path in info["paths"].items():
        print(f"[FIXTURE] level {lvl}: {path} exists={path.is_file()}")


if __name__ == "__main__":
    main()
