import bpy
from os.path import isfile
import subprocess
import glob
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import re
import os
import tempfile
from blender_asset_tracer.blendfile import open_cached

####################################
DIRECTORY = "C:/Users/romai/Documents/Projets/26 - Bezier Quest/"
PREFIX = DIRECTORY + "SP Assets"
# To move as a preference
####################################

# ─────────────────────────── ANSI COLORS ─────────────────────────────────── #
RED = "\033[91m"
GREEN = "\033[32m"
BLUE = "\033[94m"
RESET = "\033[0m"
# ──────────────────────────────────────────────────────────────────────────── #

def blue(text: str) -> str:
    return f"{BLUE}{text}{RESET}"


def find_level_from_path(path) -> int:
    match = re.search(r"Level (\d*)\.blend$", path)
    if match:
        lvl = match.group(1)
        return int(lvl)
    else:
        return -1


def node_group_level(ng: bpy.types.GeometryNodeTree) -> int:
    max_lvl = -1
    for node in ng.nodes:
        if node.type == "GROUP":
            if node.node_tree.library:
                lvl = find_level_from_path(node.node_tree.library.filepath)
                if lvl != -1:
                    if max_lvl < lvl:
                        max_lvl = lvl
                else:
                    raise Exception(
                        f"'{node.node_tree.name}' must be sent to a lower level first"
                    )
            else:
                raise Exception(
                    f"'{node.node_tree.name}' must be sent to a lower level first"
                )
    return max_lvl + 1


def append_node_group_to_file(target_filepath, node_group_name):
    source_path = bpy.data.filepath.replace("\\", "/")

    script = (
        f"import bpy"
        + f"\nwith bpy.data.libraries.load('{source_path}', link=True, recursive=False) as (_, data_to):"
        + f"\n  data_to.node_groups = ['{node_group_name}']"
        + "\nng = data_to.node_groups[0]"
        + "\nif ng is not None:"
        + "\n    ng.make_local()"
        + "\n    ng.use_fake_user = True"
        + "\n    bpy.ops.wm.save_mainfile()"
        + f"\nelse: print(f'{RED}Node group not found{RESET}')"
    )

    command = ["blender", "--background", target_filepath, "--python-expr", script]

    # Run the command
    subprocess.run(command, check=True)


def link_node_group(target_filepath, ng_name: str) -> list[bpy.types.NodeGroup]:
    with bpy.data.libraries.load(target_filepath, link=True, recursive=False) as (
        _,
        data_to,
    ):
        data_to.node_groups = [ng_name]

    linked_ng = data_to.node_groups[0]
    return linked_ng


def create_file(filepath):
    """Create an empty .blend file at the specified path without affecting the current session or leaving temporary files."""
    # Command to run Blender in the background and execute a Python command directly
    command = [
        "blender",
        "--background",
        "--python-expr",
        f"import bpy; bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.wm.save_as_mainfile(filepath='{filepath}')",
    ]

    # Run the command
    subprocess.run(command, check=True)


def children_files(parent: str, lvl):
    files = glob.glob(DIRECTORY + "SP*.blend")
    current_path = Path(bpy.data.filepath)
    children = []
    parent = Path(parent)
    for f in files:
        # format
        fp = Path(f)
        if fp != current_path and fp != parent:
            f_lvl = find_level_from_path(f)
            if f_lvl > lvl or f_lvl == -1:
                children.append(f)
    return children


def file_contains_node_group(filepath, ng_name):
    """Check if a blend file contains a specific node group using BAT (no Blender process)."""
    try:
        with open_cached(filepath) as bf:
            for nt in bf.find_blocks_from_code(b"NT"):
                if nt.id.name.decode().removeprefix("NT") == ng_name:
                    return True
            return False
    except Exception:
        return False


def remap_in_children_files(parent_file, ng_name, lvl):
    """
    Remap Node Group in every file of the current folder
    """

    targets = children_files(parent_file, lvl)
    if not targets:
        return

    # Fast path: filter files using BAT without opening Blender
    files_with_ng = [f for f in targets if file_contains_node_group(f, ng_name)]

    if not files_with_ng:
        return

    max_workers = min(2, os.cpu_count() or 2, len(files_with_ng))
    # split files evenly across workers
    chunks = [files_with_ng[i::max_workers] for i in range(max_workers)]

    def make_script(file_list):
        return (
            "import bpy, traceback, pathlib\n"
            f"files = {file_list!r}\n"
            f"ng_name = {ng_name!r}\n"
            f"parent_file = {parent_file!r}\n"
            "for f in files:\n"
            "    try:\n"
            "        bpy.ops.wm.open_mainfile(filepath=f)\n"
            "        existing = bpy.data.node_groups.get(ng_name)\n"
            "        if existing is None or existing.is_library_indirect:\n"
            "            print(f'[Skip] {f}: no local node group named {ng_name!r}')\n"
            "            continue\n"
            "        with bpy.data.libraries.load(parent_file, link=True, recursive=False) as (_, data_to):\n"
            "            data_to.node_groups = [ng_name]\n"
            "        ng = data_to.node_groups[0]\n"
            "        if ng is None:\n"
            f"            print(f'{RED}[ERROR] Node group to link not found{RESET}')\n"
            "            continue\n"
            "        existing.user_remap(ng)\n"
            "        bpy.data.orphans_purge(do_recursive=True)\n"
            "        bpy.ops.wm.save_mainfile(filepath=f)\n"
            f"        print(f'{BLUE}[File Saved] {{f}}{RESET}')\n"
            "    except Exception as e:\n"
            f"        print(f'{RED}[ERROR] {{f}}: {{e}}{RESET}')\n"
            "        traceback.print_exc()\n"
        )

    def _run_blender(file_list):
        script = make_script(file_list)
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name
        try:
            result = subprocess.run(
                [
                    "blender",
                    "--background",
                    "--factory-startup",
                    "--python",
                    script_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("["):
                    print(line)
            return result
        finally:
            os.remove(script_path)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_run_blender, chunks))


def move_ng_to_level_file(ng_name: str, level):
    target_filepath = f"{PREFIX} Level {level}.blend"

    # Create file
    if not isfile(target_filepath):
        create_file(target_filepath)

    replaced_ng = bpy.data.node_groups[ng_name]

    append_node_group_to_file(target_filepath, ng_name)
    linked_ng = link_node_group(target_filepath, ng_name)
    if linked_ng is not None:
        replaced_ng.user_remap(linked_ng)
        remap_in_children_files(target_filepath, ng_name, level)
        return True
    return False


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
        return context.area.type == "NODE_EDITOR"

    def execute(self, context):
        context.window.cursor_set("WAIT")
        if move_ng_to_level_file(self.ng.name, self.level):
            print(BLUE, "Node group moved successfully", RESET)
            self.report({"INFO"}, "Node group moved successfully")
        else:
            self.report({"ERROR"}, "Node group move failed")
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"Detected Level: {self.level}")

    def invoke(self, context, event):
        self.ng = context.space_data.edit_tree.nodes.active.node_tree
        try:
            self.level = node_group_level(self.ng)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"FINISHED"}
        wm = context.window_manager
        return wm.invoke_props_dialog(self)


class MYN_OT_AddLocalGeometryNodeGroups(bpy.types.Operator):
    bl_idname = "node.add_local_geometry_node_groups"
    bl_label = "MYN - Add Local Geometry Node Groups"
    bl_options = {"REGISTER", "UNDO"}

    """Add all local Geometry Nodes groups to the active node tree. CODED BY MISTRAL LLM"""

    def execute(self, context):
        # Get the current node editor and its node tree
        area = next((a for a in context.screen.areas if a.type == "NODE_EDITOR"), None)
        if not area:
            self.report({"ERROR"}, "No Node Editor open")
            return {"CANCELLED"}

        space = area.spaces.active
        node_tree = space.node_tree
        if not node_tree or node_tree.type != "GEOMETRY":
            self.report({"ERROR"}, "No active Geometry Node tree in the editor")
            return {"CANCELLED"}

        # Get the cursor location for placing new nodes
        cursor = space.cursor_location

        # Collect all LOCAL Geometry Node groups (excluding the current one and linked ones)
        local_groups = [
            ng
            for ng in bpy.data.node_groups
            if ng.type == "GEOMETRY"
            and ng != node_tree
            and not ng.library  # Exclude linked groups
        ]

        if not local_groups:
            self.report({"INFO"}, "No other local Geometry Node groups found")
            return {"FINISHED"}

        # Add each group as a node, positioned in a grid pattern with 30 columns
        grid_width = 30  # Number of columns in the grid
        for i, ng in enumerate(local_groups):
            node = node_tree.nodes.new("GeometryNodeGroup")
            node.node_tree = ng
            # Calculate grid position
            row = i // grid_width
            col = i % grid_width
            node.location = (cursor.x + col * 160, cursor.y - row * 500)

        return {"FINISHED"}


def get_level_from_ng(ng: bpy.types.NodeGroup) -> int:
    """Get the level of a node group from its library filepath."""
    if ng.library:
        return find_level_from_path(ng.library.filepath.replace("\\", "/"))
    # If not linked, check all level files to find where it might be stored
    # Default to level 0 if not found
    return 0


def remap_name_in_files(ng_name: str, new_name: str, level: int, parent_file: str):
    """
    Remap a node group name in all files at or above the given level.
    Similar to remap_in_children_files but for renaming.
    """
    # Find all files at the given level or higher
    files = glob.glob(DIRECTORY + "SP*.blend")
    targets = []
    for f in files:
        f_lvl = find_level_from_path(f)
        if f_lvl >= level or f_lvl == -1:
            if Path(f) != Path(bpy.data.filepath):
                targets.append(f)

    if not targets:
        return

    max_workers = min(2, os.cpu_count() or 2, len(targets))
    chunks = [targets[i::max_workers] for i in range(max_workers)]

    def make_script(file_list):
        return (
            "import bpy, traceback, pathlib\n"
            f"files = {file_list!r}\n"
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
            "        # If the node group is linked, relink it from the source file\n"
            "        if existing.library:\n"
            "            # Unlink the old node group\n"
            "            existing.user_clear()\n"
            "            bpy.data.node_groups.remove(existing)\n"
            "            # Relink the renamed node group from the source file\n"
            "            with bpy.data.libraries.load(parent_file, link=True, recursive=False) as (_, data_to):\n"
            "                data_to.node_groups = [new_name]\n"
            "            if data_to.node_groups:\n"
            f"                print(f'{BLUE}[Relinked] {{f}}: {{ng_name}} -> {{new_name}}{RESET}')\n"
            "            else:\n"
            f"                print(f'{RED}[ERROR] {{f}}: Failed to relink {{new_name}}{RESET}')\n"
            "        else:\n"
            "            # Rename the local node group\n"
            "            existing.name = new_name\n"
            f"            print(f'{BLUE}[Renamed] {{f}}: {{ng_name}} -> {{new_name}}{RESET}')\n"
            "        bpy.ops.wm.save_mainfile(filepath=f)\n"
            "    except Exception as e:\n"
            f"        print(f'{RED}[ERROR] {{f}}: {{e}}{RESET}')\n"
            "        traceback.print_exc()\n"
        )

    def _run_blender(file_list):
        script = make_script(file_list)
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name
        try:
            result = subprocess.run(
                [
                    "blender",
                    "--background",
                    "--factory-startup",
                    "--python",
                    script_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("["):
                    print(line)
            return result
        finally:
            os.remove(script_path)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_run_blender, chunks))


def rename_node_group(
    ng_name: str, new_name: str, level: int, parent_file: str
) -> bool:
    """
    Rename a node group and update references in all related files.
    """
    # Rename in current file
    current_ng = bpy.data.node_groups.get(ng_name)
    if current_ng is None:
        return False

    current_ng.name = new_name

    # Update in all files at this level and above
    remap_name_in_files(ng_name, new_name, level, parent_file)

    return True


### FAILS !!!!!!!
class MYN_OT_rename_node_group(bpy.types.Operator):
    bl_idname = "node.myn_rename_node_group"
    bl_label = "MYN - Rename Node Group"
    bl_options = {"REGISTER", "UNDO"}

    new_name: bpy.props.StringProperty(name="New Name", description="", default="")

    ng = None

    @classmethod
    def poll(cls, context):
        return context.area.type == "NODE_EDITOR"

    def execute(self, context):
        context.window.cursor_set("WAIT")
        level = get_level_from_ng(self.ng)
        parent_file = bpy.data.filepath
        if rename_node_group(self.ng.name, self.new_name, level, parent_file):
            print(GREEN, "Node group renamed successfully", RESET)
            self.report({"INFO"}, "Node group renamed successfully")
        else:
            self.report({"ERROR"}, "Node group rename failed")
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"Current Name: {self.ng.name}")
        layout.prop(self, "new_name", text="New Name")

    def invoke(self, context, event):
        self.ng = context.space_data.edit_tree.nodes.active.node_tree
        if self.ng is None:
            self.report({"INFO"}, "Select a node group to rename")
            return {"FINISHED"}
        self.new_name = self.ng.name
        wm = context.window_manager
        return wm.invoke_props_dialog(self)


def find_users(target_group_name: str, target_socket, socket_side: str) -> None:
    """
    Walk every node group in bpy.data.node_groups.
    For each one that contains a Group node referencing target_group_name,
    check whether that Group node has a connection on the requested socket.

    Prints a structured report to the console.
    """
    side = socket_side.upper()
    if side not in ("INPUT", "OUTPUT"):
        raise ValueError("socket_side must be 'INPUT' or 'OUTPUT'")

    target_ng = bpy.data.node_groups.get(target_group_name)
    if target_ng is None:
        print(
            f"[ERROR] Node group '{target_group_name}' not found in bpy.data.node_groups."
        )
        available = [ng.name for ng in bpy.data.node_groups]
        print(f"        Available groups: {available}")
        return

    print("=" * 60)
    print(f"Target node group : '{target_group_name}'")
    print(f"Socket side       : {side}")
    print(f"Socket filter     : {repr(target_socket)}")
    print("=" * 60)

    # { ng_name: { "ng": ng, "nodes": [ {node info}, … ] } }
    # Keeps insertion order; accumulates ALL instances per parent group.
    users: dict = {}

    for ng in bpy.data.node_groups:
        if ng is target_ng:  # skip the target itself
            continue
        if not hasattr(ng, "nodes"):
            continue

        for node in ng.nodes:
            # Only consider Group nodes that point to our target
            if node.type != "GROUP":
                continue
            if node.node_tree is not target_ng:
                continue

            # Ensure the parent group has an entry (may already exist from a
            # previous instance of the target inside the same parent).
            if ng.name not in users:
                users[ng.name] = {"ng": ng, "nodes": []}

            # ── Determine which socket collection to inspect ──────────────
            # node.inputs  → correspond to the group's inputs  (SOCKET_SIDE INPUT)
            # node.outputs → correspond to the group's outputs (SOCKET_SIDE OUTPUT)
            sockets = node.inputs if side == "INPUT" else node.outputs

            # ── Find the socket by name or index ─────────────────────────
            matched_socket = None
            if isinstance(target_socket, int):
                if 0 <= target_socket < len(sockets):
                    matched_socket = sockets[target_socket]
            else:
                matched_socket = sockets.get(target_socket)

            node_info = {
                "node_name": node.name,
                "node_label": node.label,
                "socket_found": matched_socket is not None,
                "connected": False,
                "socket_name": None,
                "links": [],
            }

            if matched_socket is not None:
                node_info["socket_name"] = matched_socket.name
                node_info["connected"] = matched_socket.is_linked

                if matched_socket.is_linked:
                    for link in matched_socket.links:
                        if side == "INPUT":
                            node_info["links"].append(
                                f"{link.from_node.name!r} → socket '{link.from_socket.name}'"
                            )
                        else:
                            node_info["links"].append(
                                f"→ {link.to_node.name!r} socket '{link.to_socket.name}'"
                            )

            users[ng.name]["nodes"].append(node_info)

    # ─── Report ──────────────────────────────────────────────────────────────
    total_instances = sum(len(v["nodes"]) for v in users.values())

    print(
        f"\n▶ Node groups that USE '{target_group_name}': {len(users)}"
        f"  ({total_instances} instance(s) total)"
    )
    for name, data in users.items():
        count = len(data["nodes"])
        print(f"   • {name}  [{count} instance{'s' if count > 1 else ''}]")

    # Count connected instances
    connected_instances = [
        (ng_name, ni)
        for ng_name, data in users.items()
        for ni in data["nodes"]
        if ni["connected"]
    ]
    connected_groups = len(set(ng_name for ng_name, _ in connected_instances))
    print(
        f"\n▶ Instances connected to {side} socket {repr(target_socket)}: "
        f"{len(connected_instances)} instance(s) across {connected_groups} group(s)"
    )

    if not users:
        print("\n   (no users found)")
    else:
        for ng_name, data in users.items():
            instance_count = len(data["nodes"])
            print(f"\n  ┌─ [{ng_name}] ({instance_count})")
            for i, ni in enumerate(data["nodes"]):
                prefix = "└─" if i == instance_count - 1 else "├─"
                label_str = (
                    f" (label: '{ni['node_label']}')" if ni["node_label"] else ""
                )

                if not ni["socket_found"]:
                    tag = "⚠ socket not found"
                elif ni["connected"]:
                    tag = blue("LINKED")
                else:
                    continue

                print(f"  {prefix} node: '{ni['node_name']}'{label_str}  —  {tag}")
                for lnk in ni["links"]:
                    print(f"         {lnk}")

    print("\n" + "=" * 60)
    print("Done.")

    # ─── Open a Geometry Nodes window for each connected parent group ─────────
    connected_groups_data = {
        ng_name: data
        for ng_name, data in users.items()
        if any(ni["connected"] for ni in data["nodes"])
    }

    if connected_groups_data:
        print(f"\nOpening {len(connected_groups_data)} Geometry Nodes window(s)…")
        wm = bpy.context.window_manager
        original_window = bpy.context.window

        # Pass 1: create all windows first so each one has time to initialise
        #         before we try to assign a node_tree to any of them.
        created: list[tuple] = []  # (new_win, ng_name, ng)
        for ng_name, data in connected_groups_data.items():
            ng = data["ng"]
            windows_before = list(wm.windows)
            with bpy.context.temp_override(
                window=original_window, screen=original_window.screen
            ):
                bpy.ops.wm.window_new()

            new_win = next((w for w in wm.windows if w not in windows_before), None)
            if not new_win:
                print(f"  [WARN] window_new() failed for '{ng_name}'")
                continue
            area = new_win.screen.areas[0]
            area.type = "NODE_EDITOR"
            created.append((new_win, ng_name, ng))

        # Pass 2: assign node_trees now that all windows are initialised
        for new_win, ng_name, ng in created:
            area = new_win.screen.areas[0]
            space = area.spaces.active
            if space and space.type == "NODE_EDITOR":
                space.tree_type = "GeometryNodeTree"
                space.pin = True
                space.node_tree = ng
                print(f"  ✓ Pinned '{ng_name}'")
            else:
                print(
                    f"  [WARN] Space type '{space.type if space else None}' for '{ng_name}'"
                )
    else:
        print("\n(No connected instances — no windows opened.)")


class MYN_OT_find_nodegroup_socket_users(bpy.types.Operator):
    bl_idname = "nodes.myn_find_nodegroup_socket_users"
    bl_label = "MYN - Find Node Group Socket Users"
    bl_description = (
        "Find every node group that uses the target node group and has a "
        "connection on the specified socket, then open pinned GN windows"
    )

    target_group_name: bpy.props.StringProperty(
        name="Target Node Group",
        default="",
    )
    target_socket: bpy.props.StringProperty(
        name="Socket Name",
        default="",
    )
    socket_side: bpy.props.EnumProperty(
        name="Socket Side",
        items=[("INPUT", "Input", ""), ("OUTPUT", "Output", "")],
        default="OUTPUT",
    )

    def execute(self, context):
        find_users(
            target_group_name=self.target_group_name,
            target_socket=self.target_socket,
            socket_side=self.socket_side,
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


classes = [
    MYN_OT_move_node_group,
    MYN_OT_AddLocalGeometryNodeGroups,
    # MYN_OT_rename_node_group,# broken
    MYN_OT_find_nodegroup_socket_users,
]


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in classes[::-1]:
        bpy.utils.unregister_class(c)


if __package__ == "__main__":
    register()

# TODO Make paths relative
# TODO move between level : Must use linking and not append somehow
# TODO automatically move all children when a group is upgraded
# TODO de-duplicate, rename and other utils
# TODO workflow "make local > edit > replace"

# TODO workflow "append > edit > replace" ?
