# move_yo_node — Specification

A Blender 5.3 addon for moving and organizing node groups across a hierarchy of
`.blend` files, keeping linked data valid. Package: `src/move_yo_node/`.

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

Moving `MidGroup` to level 0 would be invalid because `BaseGroup` lives at
level 0 and `MidGroup` uses it.

---

## 2. Features

Filesystem locations are user preferences (`Edit > Preferences > Add-ons >
Move yo' Node`), not module globals: `project_directory` (empty = folder of the
current `.blend`), `file_prefix` (`SP`), `file_suffix` (`Level`),
`blender_executable` (empty = the running Blender). `preferences.settings()`
returns a plain `Settings` dataclass, mirroring the registered
`AddonPreferences` when installed and acting as the source of truth when not.

| # | Feature | Operator | Status |
|---|---|---|---|
| 2.1 | Level detection: `find_level_from_path`, `node_group_level` (level a group *must* be at), `get_level_from_ng` (level it *is* at, `-1` = local) | — | tested |
| 2.2 | Level file discovery: `level_files()`, `children_files(parent, lvl)` | — | tested |
| 2.3 | Move a group to a level file: create target, copy as local with fake user, link back and remap users, relink children | `node.myn_move_node_group` | partial |
| 2.4 | Rename a group across files: rename, save, rewrite every file above it | `node.myn_rename_node_group` | partial |
| 2.5 | Find socket users: per instantiating group, report node name, socket presence, connection and links. Pure analysis, works in `--background`; `open_pinned_windows` is the GUI half | `nodes.myn_find_nodegroup_socket_users` | tested |
| 2.6 | Rename `NODES` modifiers to their group's name | `object.myn_rename_gn_modifiers_to_group_name` | tested |
| 2.7 | Node group report: per level file, local vs linked and from where; flags duplicates, collisions, similar names. Writes to console and a `BAT_NodeGroup_Report_<name>` text | `node.myn_node_group_report` | tested |
| 2.8 | Add a group node for every local Geometry Nodes group, gridded from the cursor | `node.add_local_geometry_node_groups` | untested |
| 2.9 | `bat_utils` helpers over Blender Asset Tracer: `local_node_group_name`, `library_path`, `node_groups_in_blend`, `libraries_in_blend` | — | tested |

**Important:** linked node groups are *not* stored as `NT` blocks in the
referencing file; the link appears as an `LI` block. Any code asking "does this
file reference group X" must check the library list.

---

## 3. Testing

```
python run_tests.py              # everything
python run_tests.py test_move    # one module
python run_tests.py -v           # verbose
```

`run_tests.py` launches Blender with `--background --factory-startup
--python-exit-code 1`, found via `MYN_BLENDER` or the newest
`C:/Program Files/Blender Foundation/Blender */`. Tests run inside Blender
because the addon imports `bpy`. `MynTestCase` builds a fresh four-level
hierarchy in a temporary directory per test; fixtures come from
`tests/build_fixtures.py`, no `.blend` files are committed.

**Current state: 70 tests, 67 pass, 1 expected failure, 2 failures** — the two
failures are TODO 4.2, the expected failure is TODO 4.1.

---

## 4. TODO

### 4.1 Move into a level file that does not exist yet

**Bug.** `move_ng_to_level_file` returns `False` when the target level file has
to be created first. `create_file` makes an empty `.blend`, then
`append_node_group_to_file` links the group out of the source and saves it
locally; that round-trip does not produce the group in the new file. Covered by
`test_move_creates_missing_level_file` (`expectedFailure`).

### 4.2 Rename does not propagate to child files

**Bug.** `rename_node_group` renames and saves correctly, but `_remap_script`
fails in every child with `could not link '<new_name>'`. Suspected cause: the
script removes the old linked datablock before loading the new one, leaving the
group node pointing at a freed tree. Unverified. Covered by
`test_rename_updates_children_files` and `test_rename_keeps_group_node_connection`.

### 4.3 Test the "add local geometry node groups" operator

Needs a fake `NODE_EDITOR` context, likely via `bpy.context.temp_override`.

### 4.4 Make level file paths relative

Level files are referenced by absolute path. Storing them relative
(`//SP Level 0.blend`) would make a project folder movable.

### 4.5 Move between levels by linking, not appending

`append_node_group_to_file` copies the group into the target file. Linking
instead would avoid duplicating the datablock.

### 4.6 Auto-move children when a group is upgraded

When a group moves up a level, groups that use it may also need to move.

### 4.7 De-duplicate and rename utilities

`find_level_from_path`, `resolve_library_path` and the BAT helpers overlap with
`bat_utils`. Consolidate.

### 4.8 "Make local > edit > replace" workflow

Make a linked group local, edit it, then push it back and relink.

### 4.9 "Append > edit > replace" workflow

Append a group, edit it, replace the original.

### 4.10 Copy a node group to a new file
