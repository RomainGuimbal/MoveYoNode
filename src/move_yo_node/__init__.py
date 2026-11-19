"""move_yo_node — manage node groups across a hierarchy of level .blend files.

Level 0 holds the most primitive node groups; higher levels link from lower
ones. Moving a node group to level N means: store it in "<prefix> Level N.blend"
and relink every file that used it.
"""

import glob
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import bpy

from . import node_report, preferences

# ─────────────────────────── ANSI COLORS ─────────────────────────────────── #
RED = "\033[91m"
GREEN = "\033[32m"
BLUE = "\033[94m"
RESET = "\033[0m"
# ──────────────────────────────────────────────────────────────────────────── #


def blue(text: str) -> str:
    return f"{BLUE}{text}{RESET}"


# ─────────────────────────── LEVEL HELPERS ───────────────────────────────── #


def find_level_from_path(path) -> int:
    """Extract the level number from a level file path, or -1 if not one.

    Works on both absolute paths and Blender's relative form ("//SP Level 0.blend").
    """
    if not path:
        return -1
    # Blender stores linked paths relative to the .blend ("//SP Level 0.blend").
    # Path() treats a leading "//" as a UNC root on Windows, so strip it first.
    text = str(path).replace("\\", "/")
    if text.startswith("//"):
        text = text[2:]
    name = text.rsplit("/", 1)[-1]
    prefix = re.escape(preferences.file_prefix())
    suffix = re.escape(preferences.file_suffix())
    match = re.search(rf"{prefix} {suffix} (\d+)\.blend$", name)
    if match:
        return int(match.group(1))
    return -1


def resolve_library_path(ng: bpy.types.NodeTree) -> str | None:
    """Absolute path of the library a node group is linked from, or None."""
    if not ng.library:
        return None
    return bpy.path.abspath(ng.library.filepath)


def node_group_level(ng: bpy.types.NodeTree) -> int:
    """Level a node group must be stored at, given what it depends on.

    A group must live strictly above every group it uses. Local (unlinked)
    dependencies are treated as level 0, so a group using only local groups
    can be moved to level 1.
    """
    max_lvl = -1
    for node in ng.nodes:
        if node.type != "GROUP" or node.node_tree is None:
            continue
        dep = node.node_tree
        if dep.library:
            lvl = find_level_from_path(resolve_library_path(dep))
            if lvl == -1:
                raise ValueError(
                    f"'{dep.name}' is linked from '{dep.library.filepath}', "
                    f"which is not a level file"
                )
        else:
            lvl = 0
        max_lvl = max(max_lvl, lvl)
    return max_lvl + 1


def get_level_from_ng(ng: bpy.types.NodeTree) -> int:
    """Level a node group is currently stored at, or -1 if not linked."""
    if ng.library:
        return find_level_from_path(resolve_library_path(ng))
    return -1


# ─────────────────────────── FILE HELPERS ────────────────────────────────── #


def level_files(context=None) -> list[Path]:
    """Every level file in the project directory, sorted by level."""
    pattern = preferences.level_file_glob(context)
    files = [Path(f) for f in glob.glob(str(preferences.project_directory(context) / pattern))]
    return sorted(files, key=lambda p: (find_level_from_path(p), p.name))


def children_files(parent: str, lvl: int, context=None) -> list[Path]:
    """Level files that may reference a group stored at `lvl`.

    Any file above `lvl` can link it; the current file and the parent file are
    excluded because they are handled separately.
    """
    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    parent_path = Path(parent).resolve() if parent else None

    children = []
    for fp in level_files(context):
        resolved = fp.resolve()
        if resolved == current or resolved == parent_path:
            continue
        f_lvl = find_level_from_path(fp)
        if f_lvl > lvl or f_lvl == -1:
            children.append(fp)
    return children


def file_contains_node_group(filepath, ng_name: str) -> bool:
    """True if the file stores or links a node group with this name.

    Uses Blender Asset Tracer to avoid launching Blender. Linked node groups are
    not stored as NT blocks, so a file that only links the group is detected
    through its library blocks instead.
    """
    try:
        from blender_asset_tracer.blendfile import open_cached
    except ImportError:
        return True  # cannot filter, let the caller decide

    try:
        with open_cached(Path(filepath)) as bf:
            for block in bf.find_blocks_from_code(b"NT"):
                raw = block.id_name
                if not raw:
                    continue
                stored = raw.decode(errors="ignore")
                if stored.startswith("NT"):
                    stored = stored[2:]
                if stored == ng_name:
                    return True
            # A file that links the group has no NT block for it; it references
            # the library that stores it. Be permissive: any library reference
            # means the file may need relinking.
            for block in bf.find_blocks_from_code(b"LI"):
                if block.get(b"name"):
                    return True
            return False
    except Exception as exc:
        print(f"{RED}[BAT ERROR] {filepath}: {exc}{RESET}")
        return True  # conservative: don't filter a file out on error


# ─────────────────────────── BLENDER SUBPROCESS ──────────────────────────── #


def _blender_command(*args) -> list[str]:
    """Build a Blender command line that never touches the user's preferences."""
    return [
        preferences.blender_executable(),
        "--background",
        "--factory-startup",
        *args,
    ]


def _run_blender_script(script: str) -> subprocess.CompletedProcess:
    """Run a Python script in a throwaway Blender process."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(script)
        script_path = tmp.name
    try:
        result = subprocess.run(
            _blender_command("--python", script_path),
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("["):
                print(line)
        if result.returncode != 0:
            print(f"{RED}[BLENDER ERROR]{RESET} {result.stderr.strip()}")
        return result
    finally:
        os.remove(script_path)


def create_file(filepath):
    """Create an empty .blend file at the given path."""
    filepath = str(filepath).replace("\\", "/")
    script = (
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        f"bpy.ops.wm.save_as_mainfile(filepath={filepath!r})\n"
    )
    _run_blender_script(script)


def append_node_group_to_file(target_filepath, node_group_name, source_path=None):
    """Store a copy of a node group inside another file, as a local datablock.

    `source_path` defaults to the file that actually stores the group: the
    library it is linked from when it is linked, otherwise the current file.
    """
    if source_path is None:
        ng = bpy.data.node_groups.get(node_group_name)
        source_path = resolve_library_path(ng) if ng and ng.library else bpy.data.filepath
    source_path = str(source_path).replace("\\", "/")
    target_filepath = str(target_filepath).replace("\\", "/")

    script = (
        "import bpy\n"
        f"bpy.ops.wm.open_mainfile(filepath={target_filepath!r})\n"
        f"with bpy.data.libraries.load({source_path!r}, link=True, recursive=False) as (_, data_to):\n"
        f"    data_to.node_groups = [{node_group_name!r}]\n"
        "ng = data_to.node_groups[0]\n"
        "if ng is None:\n"
        f"    print('[ERROR] node group {node_group_name!r} not found in source')\n"
        "else:\n"
        "    ng.make_local()\n"
        "    ng.use_fake_user = True\n"
        "    bpy.ops.wm.save_mainfile()\n"
        f"    print('[Stored] {node_group_name} -> {target_filepath}')\n"
    )
    _run_blender_script(script)


def link_node_group(target_filepath, ng_name: str):
    """Link a node group from a file into the current session."""
    with bpy.data.libraries.load(str(target_filepath), link=True, recursive=False) as (
        _,
        data_to,
    ):
        data_to.node_groups = [ng_name]
    return data_to.node_groups[0]


# ─────────────────────────── REMAPPING ───────────────────────────────────── #


def _remap_script(files, ng_name, parent_file, new_name=None):
    """Script that relinks (and optionally renames) a group in several files."""
    return (
        "import bpy, traceback\n"
        f"files = {[str(f) for f in files]!r}\n"
        f"ng_name = {ng_name!r}\n"
        f"new_name = {new_name!r}\n"
        f"parent_file = {parent_file!r}\n"
        "for f in files:\n"
        "    try:\n"
        "        bpy.ops.wm.open_mainfile(filepath=f)\n"
        "        existing = bpy.data.node_groups.get(ng_name)\n"
        "        if existing is None:\n"
        "            print(f'[Skip] {f}: no node group named {ng_name!r}')\n"
        "            continue\n"
        "        if existing.library:\n"
        "            existing.user_clear()\n"
        "            bpy.data.node_groups.remove(existing)\n"
        "        with bpy.data.libraries.load(parent_file, link=True, recursive=False) as (_, data_to):\n"
        "            data_to.node_groups = [new_name or ng_name]\n"
        "        linked = data_to.node_groups[0]\n"
        "        if linked is None:\n"
        "            print(f'[ERROR] {f}: could not link {new_name or ng_name!r}')\n"
        "            continue\n"
        "        if not existing.library:\n"
        "            existing.user_remap(linked)\n"
        "        bpy.data.orphans_purge(do_recursive=True)\n"
        "        bpy.ops.wm.save_mainfile(filepath=f)\n"
        "        print(f'[Relinked] {f}')\n"
        "    except Exception as e:\n"
        "        print(f'[ERROR] {f}: {e}')\n"
        "        traceback.print_exc()\n"
    )


def _run_in_parallel(files, script_factory, max_workers=None):
    """Split files across a few Blender processes and run them concurrently."""
    if not files:
        return
    workers = max_workers or min(2, os.cpu_count() or 2, len(files))
    chunks = [files[i::workers] for i in range(workers)]
    chunks = [c for c in chunks if c]
    with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
        list(ex.map(lambda c: _run_blender_script(script_factory(c)), chunks))


def remap_in_children_files(parent_file, ng_name, lvl):
    """Relink every file above `lvl` so it points at the new parent file."""
    targets = children_files(parent_file, lvl)
    if not targets:
        return

    files_with_ng = [f for f in targets if file_contains_node_group(f, ng_name)]
    if not files_with_ng:
        return

    _run_in_parallel(
        files_with_ng,
        lambda chunk: _remap_script(chunk, ng_name, str(parent_file)),
    )


def move_ng_to_level_file(ng_name: str, level) -> bool:
    """Store a node group in the level file for `level` and relink users."""
    target_filepath = preferences.level_file_path(level)

    if not target_filepath.is_file():
        create_file(target_filepath)

    replaced_ng = bpy.data.node_groups.get(ng_name)
    if replaced_ng is None:
        return False

    append_node_group_to_file(target_filepath, ng_name)

    # Blender refuses to link from the file it already has open, so when the
    # group is being stored in the current file there is nothing to relink here.
    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if current != target_filepath.resolve():
        linked_ng = link_node_group(target_filepath, ng_name)
        if linked_ng is None:
            return False
        replaced_ng.user_remap(linked_ng)

    remap_in_children_files(str(target_filepath), ng_name, level)
    return True


# ─────────────────────────── RENAME ──────────────────────────────────────── #


def remap_name_in_files(ng_name: str, new_name: str, level: int, parent_file: str):
    """Rename a node group in every file that stores or links it."""
    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    targets = []
    for fp in level_files():
        if fp.resolve() == current:
            continue
        f_lvl = find_level_from_path(fp)
        if f_lvl >= level or f_lvl == -1:
            targets.append(fp)

    if not targets:
        return

    files_with_ng = [f for f in targets if file_contains_node_group(f, ng_name)]
    if not files_with_ng:
        return

    _run_in_parallel(
        files_with_ng,
        lambda chunk: _remap_script(chunk, ng_name, parent_file, new_name=new_name),
    )


def rename_node_group(ng_name: str, new_name: str, level: int, parent_file: str) -> bool:
    """Rename a node group and update every file that references it.

    The file that stores the group must be saved before the children relink,
    otherwise they look for the new name in a file that still has the old one.
    """
    current_ng = bpy.data.node_groups.get(ng_name)
    if current_ng is None or not new_name or new_name == ng_name:
        return False

    current_ng.name = new_name
    if bpy.data.filepath:
        bpy.ops.wm.save_mainfile()
    remap_name_in_files(ng_name, new_name, level, parent_file)
    return True


# ─────────────────────────── OPERATORS ───────────────────────────────────── #


class MYN_OT_move_node_group(bpy.types.Operator):
    bl_idname = "node.myn_move_node_group"
    bl_label = "MYN - Move Node Group"
    bl_options = {"REGISTER", "UNDO"}

    level: bpy.props.IntProperty(
        name="Dependency Level", description="", default=0, min=0
    )

    ng = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "NODE_EDITOR"

    def execute(self, context):
        context.window.cursor_set("WAIT")
        try:
            ok = move_ng_to_level_file(self.ng.name, self.level)
        finally:
            context.window.cursor_set("DEFAULT")
        if ok:
            self.report({"INFO"}, "Node group moved successfully")
        else:
            self.report({"ERROR"}, "Node group move failed")
        return {"FINISHED"}

    def draw(self, context):
        self.layout.label(text=f"Detected Level: {self.level}")

    def invoke(self, context, event):
        node = context.space_data.edit_tree.nodes.active
        if node is None or node.type != "GROUP" or node.node_tree is None:
            self.report({"ERROR"}, "Select a group node first")
            return {"CANCELLED"}
        self.ng = node.node_tree
        try:
            self.level = node_group_level(self.ng)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)


class MYN_OT_AddLocalGeometryNodeGroups(bpy.types.Operator):
    bl_idname = "node.add_local_geometry_node_groups"
    bl_label = "MYN - Add Local Geometry Node Groups"
    bl_options = {"REGISTER", "UNDO"}

    """Add all local Geometry Nodes groups to the active node tree."""

    def execute(self, context):
        area = next((a for a in context.screen.areas if a.type == "NODE_EDITOR"), None)
        if not area:
            self.report({"ERROR"}, "No Node Editor open")
            return {"CANCELLED"}

        space = area.spaces.active
        node_tree = space.node_tree
        if not node_tree or node_tree.type != "GEOMETRY":
            self.report({"ERROR"}, "No active Geometry Node tree in the editor")
            return {"CANCELLED"}

        cursor = space.cursor_location
        local_groups = [
            ng
            for ng in bpy.data.node_groups
            if ng.type == "GEOMETRY" and ng != node_tree and not ng.library
        ]

        if not local_groups:
            self.report({"INFO"}, "No other local Geometry Node groups found")
            return {"FINISHED"}

        grid_width = 30
        for i, ng in enumerate(local_groups):
            node = node_tree.nodes.new("GeometryNodeGroup")
            node.node_tree = ng
            row = i // grid_width
            col = i % grid_width
            node.location = (cursor.x + col * 160, cursor.y - row * 500)

        return {"FINISHED"}


class MYN_OT_rename_node_group(bpy.types.Operator):
    bl_idname = "node.myn_rename_node_group"
    bl_label = "MYN - Rename Node Group"
    bl_options = {"REGISTER", "UNDO"}

    new_name: bpy.props.StringProperty(name="New Name", description="", default="")

    ng = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "NODE_EDITOR"

    def execute(self, context):
        context.window.cursor_set("WAIT")
        try:
            level = get_level_from_ng(self.ng)
            parent_file = bpy.data.filepath
            ok = rename_node_group(self.ng.name, self.new_name, level, parent_file)
        finally:
            context.window.cursor_set("DEFAULT")
        if ok:
            self.report({"INFO"}, "Node group renamed successfully")
        else:
            self.report({"ERROR"}, "Node group rename failed")
        return {"FINISHED"}

    def draw(self, context):
        self.layout.label(text=f"Current Name: {self.ng.name}")
        self.layout.prop(self, "new_name", text="New Name")

    def invoke(self, context, event):
        node = context.space_data.edit_tree.nodes.active
        if node is None or node.type != "GROUP" or node.node_tree is None:
            self.report({"INFO"}, "Select a node group to rename")
            return {"CANCELLED"}
        self.ng = node.node_tree
        self.new_name = self.ng.name
        return context.window_manager.invoke_props_dialog(self)


def find_users(target_group_name: str, target_socket, socket_side: str) -> dict:
    """Collect every group that uses `target_group_name` on the given socket.

    Pure analysis: returns a dict keyed by parent group name. Opening windows is
    left to the caller so this stays usable in background mode.
    """
    side = socket_side.upper()
    if side not in ("INPUT", "OUTPUT"):
        raise ValueError("socket_side must be 'INPUT' or 'OUTPUT'")

    target_ng = bpy.data.node_groups.get(target_group_name)
    if target_ng is None:
        raise ValueError(f"Node group '{target_group_name}' not found")

    users: dict = {}
    for ng in bpy.data.node_groups:
        if ng is target_ng or not hasattr(ng, "nodes"):
            continue
        for node in ng.nodes:
            if node.type != "GROUP" or node.node_tree is not target_ng:
                continue

            if ng.name not in users:
                users[ng.name] = {"ng": ng, "nodes": []}

            sockets = node.inputs if side == "INPUT" else node.outputs
            matched = None
            if isinstance(target_socket, int):
                if 0 <= target_socket < len(sockets):
                    matched = sockets[target_socket]
            else:
                matched = sockets.get(target_socket)

            info = {
                "node_name": node.name,
                "node_label": node.label,
                "socket_found": matched is not None,
                "connected": False,
                "socket_name": None,
                "links": [],
            }
            if matched is not None:
                info["socket_name"] = matched.name
                info["connected"] = matched.is_linked
                for link in matched.links:
                    if side == "INPUT":
                        info["links"].append(
                            f"{link.from_node.name!r} -> socket '{link.from_socket.name}'"
                        )
                    else:
                        info["links"].append(
                            f"-> {link.to_node.name!r} socket '{link.to_socket.name}'"
                        )
            users[ng.name]["nodes"].append(info)
    return users


def report_users(users: dict, target_group_name: str, target_socket, socket_side: str):
    """Print a human-readable report of find_users() output."""
    side = socket_side.upper()
    total = sum(len(v["nodes"]) for v in users.values())
    print("=" * 60)
    print(f"Target node group : '{target_group_name}'")
    print(f"Socket side       : {side}")
    print(f"Socket filter     : {target_socket!r}")
    print("=" * 60)
    print(f"\n> Node groups that USE '{target_group_name}': {len(users)} ({total} instance(s))")
    for name, data in users.items():
        print(f"   - {name}  [{len(data['nodes'])} instance(s)]")

    connected = [
        (name, ni)
        for name, data in users.items()
        for ni in data["nodes"]
        if ni["connected"]
    ]
    groups = len({name for name, _ in connected})
    print(f"\n> Instances connected to {side} socket {target_socket!r}: {len(connected)} across {groups} group(s)")

    for name, data in users.items():
        print(f"\n  [{name}] ({len(data['nodes'])})")
        for ni in data["nodes"]:
            if not ni["socket_found"]:
                tag = "socket not found"
            elif ni["connected"]:
                tag = blue("LINKED")
            else:
                continue
            label = f" (label: '{ni['node_label']}')" if ni["node_label"] else ""
            print(f"    node: '{ni['node_name']}'{label}  -  {tag}")
            for lnk in ni["links"]:
                print(f"         {lnk}")
    print("\n" + "=" * 60)


def open_pinned_windows(users: dict):
    """Open a pinned Geometry Nodes window per connected parent group (GUI only)."""
    connected = {
        name: data
        for name, data in users.items()
        if any(ni["connected"] for ni in data["nodes"])
    }
    if not connected:
        return

    wm = bpy.context.window_manager
    original = bpy.context.window
    created = []
    for name, data in connected.items():
        before = list(wm.windows)
        with bpy.context.temp_override(window=original, screen=original.screen):
            bpy.ops.wm.window_new()
        new_win = next((w for w in wm.windows if w not in before), None)
        if not new_win:
            continue
        new_win.screen.areas[0].type = "NODE_EDITOR"
        created.append((new_win, name, data["ng"]))

    for new_win, name, ng in created:
        space = new_win.screen.areas[0].spaces.active
        if space and space.type == "NODE_EDITOR":
            space.tree_type = "GeometryNodeTree"
            space.pin = True
            space.node_tree = ng


class MYN_OT_find_nodegroup_socket_users(bpy.types.Operator):
    bl_idname = "nodes.myn_find_nodegroup_socket_users"
    bl_label = "MYN - Find Node Group Socket Users"
    bl_description = (
        "Find every node group that uses the target node group and has a "
        "connection on the specified socket, then open pinned GN windows"
    )

    target_group_name: bpy.props.StringProperty(name="Target Node Group", default="")
    target_socket: bpy.props.StringProperty(name="Socket Name", default="")
    socket_side: bpy.props.EnumProperty(
        name="Socket Side",
        items=[("INPUT", "Input", ""), ("OUTPUT", "Output", "")],
        default="OUTPUT",
    )

    def execute(self, context):
        try:
            users = find_users(self.target_group_name, self.target_socket, self.socket_side)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        report_users(users, self.target_group_name, self.target_socket, self.socket_side)
        if not bpy.app.background:
            open_pinned_windows(users)
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MYN_OT_rename_gn_modifiers_to_group_name(bpy.types.Operator):
    bl_idname = "object.myn_rename_gn_modifiers_to_group_name"
    bl_label = "Rename Modifiers to Node Group Name"

    def execute(self, context):
        for obj in bpy.data.objects:
            for mod in obj.modifiers:
                if mod.type == "NODES" and mod.node_group:
                    mod.name = mod.node_group.name
        return {"FINISHED"}


classes = [
    MYN_OT_move_node_group,
    MYN_OT_AddLocalGeometryNodeGroups,
    MYN_OT_rename_node_group,
    MYN_OT_find_nodegroup_socket_users,
    MYN_OT_rename_gn_modifiers_to_group_name,
]


def register():
    preferences.register()
    for c in classes:
        bpy.utils.register_class(c)
    node_report.register()


def unregister():
    node_report.unregister()
    for c in classes[::-1]:
        bpy.utils.unregister_class(c)
    preferences.unregister()


if __package__ == "__main__":
    register()
