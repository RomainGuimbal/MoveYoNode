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
    """True if the file stores the group or links a library that stores it.

    A file that could not be parsed answers True: it might reference the group,
    and skipping it would leave a link pointing at the old location.
    """
    return Path(filepath) in referencing_files(ng_name)


# ─────────────────────────── BLENDER SUBPROCESS ──────────────────────────── #


def _blender_command(*args) -> list[str]:
    """Build a Blender command line that never touches the user's preferences."""
    return [
        preferences.blender_executable(),
        "--background",
        "--factory-startup",
        *args,
    ]


def _run_blender_script(script: str, echo_prefix: str = "[") -> subprocess.CompletedProcess:
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
            if line.startswith(echo_prefix):
                print(line)
        if result.returncode != 0:
            print(f"{RED}[BLENDER ERROR]{RESET} {result.stderr.strip()}")
        return result
    finally:
        os.remove(script_path)


def _move_group_script(source_path, target_filepath, ng_name):
    """Script that performs a move: this copy goes, the source links it back.
    Runs inside the source file, so the group it stores locally is *the* copy
    being moved. The order matters and is not negotiable:

    1. Link the group from the target and make it local there. That gives the
       move something to hand the users over to.
    2. ``user_remap`` while the local copy is still alive. Removing first frees
       the datablock under the group nodes and loses them.
    3. Drop the local copy and save once. The source file ends up linking the
       group from its new home, in the same place its own copy occupied.

    Saving once is what keeps this safe: until the save, the session holds the
    old copy and the users still resolve. Refusing every write before the save
    means a failed move cannot leave both files claiming the group.
    """
    return (
        "import bpy, os, traceback\n"
        f"target = {str(target_filepath)!r}\n"
        f"name = {ng_name!r}\n"
        "local = bpy.data.node_groups.get(name)\n"
        "if local is None or local.library is not None:\n"
        "    print('[ERROR] the source file does not store this group locally')\n"
        "    print('[moved] False')\n"
        "else:\n"
        "    try:\n"
        "        with bpy.data.libraries.load(target, link=True, recursive=False) as (_, data_to):\n"
        "            data_to.node_groups = [name]\n"
        "        linked = data_to.node_groups[0]\n"
        "        if linked is None:\n"
        "            print('[ERROR] %r is not stored in %s' % (name, target))\n"
        "            print('[moved] False')\n"
        "        else:\n"
        "            local.user_remap(linked)\n"
        "            local.use_fake_user = False\n"
        "            bpy.data.node_groups.remove(local)\n"
        "            bpy.ops.wm.save_mainfile(filepath=os.path.abspath(bpy.data.filepath))\n"
        f"            print('[Moved] {ng_name} -> {target_filepath}')\n"
        "            print('[moved] True')\n"
        "    except Exception as e:\n"
        "        print('[ERROR] move failed, nothing written: %s' % e)\n"
        "        traceback.print_exc()\n"
        "        print('[moved] False')\n"
    )


def _store_group_script(target_filepath, source_path, ng_name):
    """Script that adds a group to the target file as a local datablock.

    Used when the group is linked from elsewhere: the target is opened, the
    group is linked in and made local, and the rest of the dependency chain it
    drags in is dropped so only the requested group is added. The target is
    saved once at the end.
    """
    return (
        "import bpy, os, traceback\n"
        f"source = {str(source_path)!r}\n"
        f"target = {str(target_filepath)!r}\n"
        f"name = {ng_name!r}\n"
        "try:\n"
        "    if os.path.isfile(target):\n"
        "        bpy.ops.wm.open_mainfile(filepath=target)\n"
        "    else:\n"
        "        bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "    # Only groups that were already stored locally belong in this file.\n"
        "    before = {g.name for g in bpy.data.node_groups if not g.library}\n"
        "    with bpy.data.libraries.load(source, link=True, recursive=False) as (_, data_to):\n"
        "        data_to.node_groups = [name]\n"
        "    ng = data_to.node_groups[0]\n"
        "    if ng is None:\n"
        "        print('[ERROR] node group not found in source:', name)\n"
        "        print('[stored] False')\n"
        "    else:\n"
        "        with bpy.context.temp_override(id=ng):\n"
        "            bpy.ops.object.make_local(type='ALL')\n"
        "        ng.use_fake_user = True\n"
        "        # Linking a group also pulls the groups it uses, and make_local\n"
        "        # makes that whole chain local. Only the requested group belongs\n"
        "        # in this file; drop the rest of the chain it dragged along.\n"
        "        for other in list(bpy.data.node_groups):\n"
        "            if other is ng or other.name in before:\n"
        "                continue\n"
        "            other.use_fake_user = False\n"
        "            bpy.data.node_groups.remove(other)\n"
        "        bpy.ops.wm.save_as_mainfile(filepath=target, check_existing=False)\n"
        f"        print('[Stored] {ng_name} -> {target_filepath}')\n"
        "        print('[stored] True')\n"
        "except Exception as e:\n"
        "    print('[ERROR] store failed, nothing written: %s' % e)\n"
        "    traceback.print_exc()\n"
        "    print('[stored] False')\n"
    )


def _script_succeeded(script: str, marker: str) -> bool:
    """Run a script in background Blender and check for its success marker."""
    return marker in _run_blender_script(script).stdout


def _remove_group_from(filepath, ng_name: str) -> bool:
    """Delete a locally stored node group from a file on disk.

    Refuses to remove anything that is only linked from that file: a link is
    not a copy, and deleting it would detach the file that owns nothing.
    """
    script = (
        "import bpy, os, traceback\n"
        f"path = {str(filepath)!r}\n"
        f"name = {ng_name!r}\n"
        "try:\n"
        "    bpy.ops.wm.open_mainfile(filepath=path)\n"
        "    ng = bpy.data.node_groups.get(name)\n"
        "    if ng is None or ng.library is not None:\n"
        "        print('[ERROR] %r is not stored in %s' % (name, path))\n"
        "        print('[removed] False')\n"
        "    else:\n"
        "        # Anything still using it here would be broken by the removal;\n"
        "        # the callers are repointed before this runs.\n"
        "        users = ng.users\n"
        "        ng.use_fake_user = False\n"
        "        bpy.data.node_groups.remove(ng)\n"
        "        bpy.ops.wm.save_mainfile(filepath=path)\n"
        "        print('[Removed] %s (had %d user(s))' % (name, users))\n"
        "        print('[removed] True')\n"
        "except Exception as e:\n"
        "    print('[ERROR] remove failed: %s' % e)\n"
        "    traceback.print_exc()\n"
        "    print('[removed] False')\n"
    )
    return _script_succeeded(script, "[removed] True")


def stored_in_file(filepath, ng_name: str) -> bool:
    """True if the file on disk stores the group as a local datablock.

    A file that does not exist yet stores nothing, which is the normal case for
    a level file the move is about to create.
    """
    from blender_asset_tracer.blendfile import open_cached

    path = Path(filepath)
    if not path.is_file():
        return False
    with open_cached(path) as bfile:
        return ng_name in _stored_groups(bfile)


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
    """Script that relinks (and optionally renames) a group in several files.

    The replacement is loaded *before* the stale datablock is touched, so the
    group nodes always have a live tree to point at. Removing first would free
    the datablock while nodes still reference it, which loses the users and
    raises ``StructRNA ... has been removed``.
    """
    return (
        "import bpy, traceback\n"
        f"files = {[str(f) for f in files]!r}\n"
        f"ng_name = {ng_name!r}\n"
        f"new_name = {new_name!r}\n"
        f"parent_file = {parent_file!r}\n"
        "for f in files:\n"
        "    try:\n"
        "        bpy.ops.wm.open_mainfile(filepath=f)\n"
        "        target_name = new_name or ng_name\n"
        "        existing = bpy.data.node_groups.get(ng_name)\n"
        "        if existing is None:\n"
        "            print('[Skip] %s: no node group named %r' % (f, ng_name))\n"
        "            continue\n"
        "        already = bpy.data.node_groups.get(target_name)\n"
        "        if existing.library and already is existing:\n"
        "            print('[Skip] %s: already links from the right place' % f)\n"
        "            continue\n"
        "        with bpy.data.libraries.load(parent_file, link=True, recursive=False) as (_, data_to):\n"
        "            data_to.node_groups = [target_name]\n"
        "        linked = data_to.node_groups[0]\n"
        "        if linked is None:\n"
        "            print('[ERROR] %s: could not link %r' % (f, target_name))\n"
        "            continue\n"
        "        # Redirect the users while the old datablock is still alive.\n"
        "        if existing is not linked:\n"
        "            existing.user_remap(linked)\n"
        "        bpy.data.orphans_purge(do_recursive=True)\n"
        "        bpy.ops.wm.save_mainfile(filepath=f)\n"
        "        print('[Relinked] %s' % f)\n"
        "    except Exception as e:\n"
        "        print('[ERROR] %s: %s' % (f, e))\n"
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


def all_blend_files(context=None) -> list[Path]:
    """Every .blend file in the project directory, sorted by name."""
    directory = preferences.project_directory(context)
    return sorted(directory.glob("*.blend"), key=lambda p: p.name)


# Key under which group_references() reports files it could not parse.
UNREADABLE = "\0unreadable"


def _stored_groups(bfile) -> set[str]:
    """Names of the node groups a .blend file stores locally."""
    names = set()
    for block in bfile.find_blocks_from_code(b"NT"):
        raw = block.id_name
        if not raw:
            continue
        name = raw.decode(errors="ignore")
        if name.startswith("NT"):
            name = name[2:]
        names.add(name)
    return names


def group_references(context=None) -> dict[str, set[Path]]:
    """Map every node group name to the files that reference it.

    One pass over the project directory: each file is parsed once to read both
    the groups it stores and the libraries it links. A file that links a library
    which stores the group counts as a reference, because that is how a linked
    node group appears on disk. Used by moves and renames to avoid re-reading
    the same .blend for every operation.

    Files that cannot be read are reported under the ``UNREADABLE`` key so the
    caller can keep them in the run instead of silently dropping their links.
    """
    files = all_blend_files(context)
    stored: dict[Path, set[str]] = {}
    linked: dict[Path, set[Path]] = {}
    unreadable: set[Path] = set()

    try:
        from blender_asset_tracer.blendfile import open_cached
    except ImportError:
        return {UNREADABLE: set(files)}

    for path in files:
        try:
            with open_cached(path) as bfile:
                stored[path] = _stored_groups(bfile)
                linked[path] = {Path(lib) for lib in bat_utils.libraries_in_blend(bfile)}
        except Exception as exc:
            print(f"{RED}[BAT ERROR] {path}: {exc}{RESET}")
            unreadable.add(path)

    refs: dict[str, set[Path]] = {}
    for path, names in stored.items():
        for name in names:
            refs.setdefault(name, set()).add(path)

    # A file referencing a library that stores the group references the group.
    for path, libraries in linked.items():
        for library in libraries:
            for name in stored.get(library, ()):
                refs.setdefault(name, set()).add(path)

    if unreadable:
        refs[UNREADABLE] = unreadable
    return refs


def referencing_files(ng_name: str, context=None) -> set[Path]:
    """Files that reference `ng_name`, including any that could not be read."""
    refs = group_references(context)
    return refs.get(ng_name, set()) | refs.get(UNREADABLE, set())


def remap_in_children_files(parent_file, ng_name, lvl, previous_file=None, files=None):
    """Relink every other file that references the group to its new location.

    A moved group is followed by all of its users, wherever they live: the
    files are not limited to those above `lvl`, because a file at any level may
    link the group and every one of those links must point at the new home.

    `files` is the list gathered before the move, when the old location still
    existed. Passing it avoids re-reading the directory after the group has
    already changed hands, which would miss the files that used to point there.

    `previous_file` is where the group used to be stored. That file is skipped:
    it is handled by the move itself, which replaces its local copy with a link.
    """
    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    target = Path(str(parent_file)).resolve() if parent_file else None
    previous = Path(str(previous_file)).resolve() if previous_file else None

    candidates = files if files is not None else referencing_files(ng_name)
    files_with_ng = [
        f
        for f in candidates
        if f.resolve() not in (current, target, previous)
    ]
    if not files_with_ng:
        return

    _run_in_parallel(
        files_with_ng,
        lambda chunk: _remap_script(chunk, ng_name, str(parent_file)),
    )


def move_ng_to_level_file(ng_name: str, level) -> bool:
    """Move a node group into the level file for `level`.

    A move takes the group *out* of the file that stored it: that file ends up
    linking the group from its new home, and every other file that referenced
    the group is repointed too. Storing a group where it already lives is
    refused rather than perfomed twice, because a second copy in the target
    file is a duplicate nobody asked for.
    """
    target_filepath = preferences.level_file_path(level)
    target_resolved = target_filepath.resolve()

    moved_ng = bpy.data.node_groups.get(ng_name)
    if moved_ng is None:
        return False

    # Where the group is stored right now: the library it is linked from, or
    # the current file when it is local here.
    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    stored_in = resolve_library_path(moved_ng)
    source = Path(stored_in).resolve() if stored_in else current
    if source is None:
        return False

    if source == target_resolved:
        print(f"{RED}[Move] {ng_name} is already stored in {target_filepath.name}{RESET}")
        return False
    if stored_in_file(target_filepath, ng_name):
        print(f"{RED}[Move] {target_filepath.name} already stores {ng_name}{RESET}")
        return False

    # Everything that linked the group before the move, gathered while the old
    # location still exists. The source is handled on its own below, and the
    # target is where the group is going.
    followers = [
        f
        for f in referencing_files(ng_name)
        if f.resolve() not in (source, current, target_resolved)
    ]

    if stored_in is None:
        # The group is stored here. Linking a file into itself is impossible in
        # Blender, so the copy has to be added to the target before this file
        # can link it back.
        if current is None or not os.path.isfile(current):
            return False
        bpy.ops.wm.save_mainfile()
        if not _script_succeeded(_store_group_script(target_filepath, str(current), ng_name), "[stored] True"):
            return False
        if not _script_succeeded(_move_group_script(str(current), str(target_filepath), ng_name), "[moved] True"):
            return False
        # The file has already been rewritten: the session still holds the old
        # local copy, so reload from disk to pick up the link that replaced it.
        bpy.ops.wm.open_mainfile(filepath=str(current))
        moved_ng = bpy.data.node_groups.get(ng_name)
        if moved_ng is None or moved_ng.library is None:
            return False
        previous_home = str(current)
    else:
        # The group lives in another file: store it in the target, then that
        # file stops being the home of this group.
        if not _script_succeeded(_store_group_script(target_filepath, stored_in, ng_name), "[stored] True"):
            return False
        if not _remove_group_from(stored_in, ng_name):
            return False
        previous_home = stored_in
        linked_ng = link_node_group(target_filepath, ng_name)
        if linked_ng is None:
            return False
        moved_ng.user_remap(linked_ng)
        if bpy.data.filepath and os.path.isfile(bpy.data.filepath):
            bpy.ops.wm.save_mainfile()

    remap_in_children_files(str(target_filepath), ng_name, level, previous_file=previous_home, files=followers)
    return True


# ─────────────────────────── RENAME ──────────────────────────────────────── #


def remap_name_in_files(ng_name: str, new_name: str, level: int, parent_file: str):
    """Rename a node group in every other file that stores or links it.

    Like a move, a rename must be followed by every user: the files are not
    filtered by level, because a file at any level may link the group.
    """
    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    parent = Path(str(parent_file)).resolve() if parent_file else None

    files_with_ng = [
        f
        for f in referencing_files(ng_name)
        if f.resolve() not in (current, parent)
    ]
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
