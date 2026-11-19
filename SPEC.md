# move_yo_node — Specification

A Blender addon for moving and organizing node groups across a hierarchy of
`.blend` files, keeping linked data valid.

Blender 5.3. Addon package: `src/move_yo_node/`.

---

## 1. Core concept: dependency levels

A project is a set of `.blend` files named `<prefix> <suffix> <n>.blend`, e.g.
`SP Level 0.blend`, `SP Level 1.blend`, …

**Level 0 holds primitives.** A file at level *n* may link node groups from any
file at level *< n*. A group must be stored strictly above every group it uses.

```
SP Level 0.blend   BaseGroup, LeafGroup        (no dependencies)
SP Level 1.blend   MidGroup  -> links BaseGroup
SP Level 2.blend   TopGroup  -> links MidGroup
SP Level 3.blend   SceneGroup -> links TopGroup
```

The rule exists so that a group can only be moved up once everything it depends
on has already been moved. Moving `MidGroup` to level 0 would be invalid because
`BaseGroup` lives at level 0 and `MidGroup` uses it.

---

## 2. Features

### 2.1 Preferences

**Status: implemented, tested** (`tests/test_levels.py`)

All filesystem locations are user preferences, not module globals. Configured in
`Edit > Preferences > Add-ons > Move yo' Node`.

| Preference | Default | Meaning |
|---|---|---|
| `project_directory` | empty | Folder holding the level files. Empty = folder of the current `.blend`. |
| `file_prefix` | `SP` | Prefix of level file names. |
| `file_suffix` | `Level` | Word between prefix and level number. |
| `blender_executable` | empty | Blender binary for background work. Empty = the running Blender. |

`preferences.settings()` returns a plain `Settings` dataclass. When the addon is
installed it mirrors the registered `AddonPreferences`; when it is not (test
harness, Text Editor) the dataclass is the source of truth. This indirection
exists because RNA structs cannot be instantiated outside the addon registry.

**Acceptance:** changing `file_prefix` changes which files are treated as level
files. An empty `project_directory` falls back to the current file's folder.

---

### 2.2 Level detection

**Status: implemented, tested** (`tests/test_levels.py`)

`find_level_from_path(path) -> int` extracts *n* from a level file path, or `-1`
if the path is not a level file. Handles both absolute paths and Blender's
relative form `//SP Level 0.blend`.

`node_group_level(ng) -> int` returns the level a group *must* be stored at:
one above the highest level among the groups it uses. Local (unlinked)
dependencies count as level 0, so a group using only local groups can move to
level 1. Raises `ValueError` if a dependency is linked from a non-level file.

`get_level_from_ng(ng) -> int` returns the level a group is *currently* stored
at, or `-1` if it is local.

**Acceptance:** a group with no dependencies reports level 0. A group using a
level-2 group reports level 3. A local group reports `-1` from
`get_level_from_ng`.

---

### 2.3 Level file discovery

**Status: implemented, tested** (`tests/test_levels.py`, `tests/test_move.py`)

`level_files()` returns every level file in the project directory, sorted by
level. `children_files(parent, lvl)` returns the level files above `lvl`,
excluding the current file and the parent file.

**Acceptance:** at level 0 with four files, `children_files` returns levels 1, 2
and 3. At level 3 it returns an empty list.

---

### 2.4 Move a node group to a level file

**Status: implemented, partially tested** (`tests/test_move.py`)

Operator: `node.myn_move_node_group`. Select a group node in the Node Editor,
run it, confirm the detected level.

`move_ng_to_level_file(ng_name, level)`:

1. Creates the target level file if it does not exist.
2. Copies the group into the target file as a local datablock with a fake user.
3. If the target is a different file, links the group back and remaps the
   original datablock's users onto the linked copy.
4. Relinks every child file so it points at the new location.

The source for step 2 is the group's own library when the group is linked,
otherwise the current file. Blender refuses to link from the file it already
has open, so step 3 is skipped when the target *is* the current file.

**Acceptance:** after moving `BaseGroup` to level 0, level 1 links `BaseGroup`
from `SP Level 0.blend` and the group node in `MidGroup` still resolves.

**Known gap:** moving into a level file that does not exist yet returns `False`.
See TODO 4.1.

---

### 2.5 Rename a node group across files

**Status: implemented, partially tested** (`tests/test_rename.py`)

Operator: `node.myn_rename_node_group`. Select a group node, enter a new name.

`rename_node_group(ng_name, new_name, level, parent_file)` renames the datablock,
saves the file that stores it, then rewrites every file above `level` that
references the group.

**Acceptance:** renaming `BaseGroup` to `RenamedBase` at level 0 leaves level 1
with a `RenamedBase` group and no `BaseGroup`.

**Known bug:** the child relink fails with `could not link '<new_name>'`. The
rename and save succeed; the relink script does not. See TODO 4.2.

---

### 2.6 Find socket users

**Status: implemented, tested** (`tests/test_find_users.py`)

Operator: `nodes.myn_find_nodegroup_socket_users`.

`find_users(target_group_name, target_socket, socket_side) -> dict` collects
every group that instantiates the target group, keyed by parent group name. For
each instance it reports the node name, whether the socket exists, whether it is
connected, and the links on it. `target_socket` is an index or a socket name;
`socket_side` is `INPUT` or `OUTPUT`.

This is pure analysis — it opens no windows, so it works in `--background`.
`open_pinned_windows(users)` is a separate GUI-only function that opens a pinned
Geometry Nodes window per connected parent group.

**Acceptance:** a consumer group wiring `BaseGroup`'s output onward is reported
with `connected: True` and one link. Running `find_users` in background does not
change the window count.

---

### 2.7 Rename modifiers to node group name

**Status: implemented, tested** (`tests/test_modifiers.py`)

Operator: `object.myn_rename_gn_modifiers_to_group_name`. For every object, every
`NODES` modifier with a node group is renamed to match that group's name.

**Acceptance:** a modifier named `GeometryNodes` on a `BaseGroup` modifier
becomes `BaseGroup`. Non-`NODES` modifiers and `NODES` modifiers without a group
are untouched.

---

### 2.8 Node group report

**Status: implemented, tested** (`tests/test_report.py`)

Operator: `node.myn_node_group_report`. Scans every level file in the project
directory for a node group and reports, per file, whether it stores the group
locally, links it, and from where. Flags duplicate names, local/linked
collisions, and similar names. Writes the report to the system console and to a
Text datablock named `BAT_NodeGroup_Report_<name>`.

Uses Blender Asset Tracer to read `.blend` files without launching Blender.

**Acceptance:** a file storing the group reports `local_target: True`. A file
with a similar name reports it under `variants`. An unreadable file reports an
error rather than raising.

---

### 2.9 Add local geometry node groups

**Status: implemented, untested**

Operator: `node.add_local_geometry_node_groups`. Adds a group node for every
local Geometry Nodes group to the active node tree, laid out in a grid from the
cursor location.

**Acceptance:** with three local geometry groups, the active tree gains three
group nodes. Not yet covered — needs a fake `NODE_EDITOR` context.

---

### 2.10 File inspection helpers

**Status: implemented, tested** (`tests/test_report.py`)

`bat_utils` wraps Blender Asset Tracer:

- `local_node_group_name(block)` — name of an `NT` block, without the `NT`
  prefix.
- `library_path(block)` — source library of a linked datablock, or `None`. Reads
  `(b"id", b"lib")` because `bNodeTree` has no top-level `lib` field.
- `node_groups_in_blend(bfile)` — every node group stored in a file.
- `libraries_in_blend(bfile)` — every library a file links from.

**Important:** linked node groups are *not* stored as `NT` blocks in the
referencing file. A file that links `BaseGroup` has no `NT` block for it; the
link appears as an `LI` block. Any code asking "does this file reference group
X" must check the library list, not expect an `NT` block.

**Acceptance:** level 0 has no libraries. Level 1 has exactly one, pointing at
`SP Level 0.blend`, and stores only `MidGroup`.

---

## 3. Testing

Run the suite with:

```
python run_tests.py              # everything
python run_tests.py test_move    # one module
python run_tests.py -v           # verbose
```

`run_tests.py` launches Blender with `--background --factory-startup
--python-exit-code 1`. It finds Blender via the `MYN_BLENDER` environment
variable, else the newest `C:/Program Files/Blender Foundation/Blender */`.

Tests run inside Blender because the addon imports `bpy`. `MynTestCase` builds a
fresh four-level hierarchy in a temporary directory per test and points the
preferences at it. Fixtures are generated at test time by
`tests/build_fixtures.py` — no `.blend` files are committed.

**Current state: 70 tests, 67 pass, 1 expected failure, 2 failures.**

| Module | Covers | Result |
|---|---|---|
| `test_levels` | 2.1, 2.2, 2.3 | 12/12 |
| `test_move` | 2.3, 2.4 | 18 pass, 1 expected failure |
| `test_rename` | 2.5 | 8/10 |
| `test_find_users` | 2.6 | pass |
| `test_modifiers` | 2.7 | pass |
| `test_report` | 2.8, 2.10 | pass |
| `test_add_local_groups` | 2.9 | not written |

---

## 4. TODO

### 4.1 Move into a level file that does not exist yet

**Bug.** `move_ng_to_level_file` returns `False` when the target level file has
to be created first. `create_file` makes an empty `.blend`, then
`append_node_group_to_file` links the group out of the source and saves it
locally; that round-trip does not produce the group in the new file.

Covered by `test_move_creates_missing_level_file`, currently marked
`expectedFailure`.

### 4.2 Rename does not propagate to child files

**Bug.** `rename_node_group` renames and saves the storing file correctly, but
`_remap_script` then fails in every child with `could not link '<new_name>'`.
Suspected cause: the script removes the old linked datablock before loading the
new one, leaving the group node pointing at a freed tree. Unverified.

Covered by `test_rename_updates_children_files` and
`test_rename_keeps_group_node_connection`, both failing.

### 4.3 Test the "add local geometry node groups" operator

Needs a fake `NODE_EDITOR` context, likely via `bpy.context.temp_override`.

### 4.4 Make level file paths relative

Level files are currently referenced by absolute path. Storing them relative
(`//SP Level 0.blend`) would make a project folder movable.

### 4.5 Move between levels by linking, not appending

`append_node_group_to_file` copies the group into the target file. Linking
instead would avoid duplicating the datablock.

### 4.6 Auto-move children when a group is upgraded

When a group moves up a level, groups that use it may also need to move. Not
implemented.

### 4.7 De-duplicate and rename utilities

`find_level_from_path`, `resolve_library_path` and the BAT helpers overlap with
`bat_utils`. Consolidate.

### 4.8 "Make local > edit > replace" workflow

Make a linked group local, edit it, then push it back and relink. Not
implemented.

### 4.9 "Append > edit > replace" workflow

Append a group, edit it, replace the original. Not implemented.

### 4.10 Copy a node group to a new file

Not implemented.
