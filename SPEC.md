# MoveYoNode — Specification

A Blender 5.3 add-on (`move_yo_node`, UI name "Move yo' Node") for moving and
renaming node groups across a hierarchy of `.blend` files without breaking the
links between them. It also aims at including a variety diagnosis and managment tools. Package: `src/move_yo_node/`.

Blender has no API to relocate a datablock between files. Every operation here
is therefore implemented as: edit the current session, then rewrite the
affected files from throwaway `blender --background --factory-startup`
subprocesses driven by Blender Asset Tracer (BAT) reads of the bytes on disk.

---

## 1. Model

A **project** is one folder of level files named `<prefix> <suffix> <n>.blend`
(`SP Level 0.blend`, `SP Level 1.blend`, …). Folder, prefix and suffix are
add-on preferences; an empty folder means the folder of the open `.blend`.

**Level rule.** Level 0 holds primitives. A group must be stored strictly above
every group it uses; a file at level *n* may only link groups stored below *n*.

```
SP Level 0.blend   BaseGroup, LeafGroup        (no dependencies)
SP Level 1.blend   MidGroup     -> links BaseGroup
SP Level 2.blend   TopGroup     -> links MidGroup
SP Level 3.blend   SceneGroup   -> links TopGroup
```

A **home** is the one file that stores a group as a local datablock. Every other
file that uses the group links it from that home.

**Anatomy, and the two things that are easy to get wrong:**

* A linked group is not an `NT` block in the referencing file. Only the `LI`
  library block is there. "Does this file use group X" must be answered by
  following the library chain, never by looking for the group's `NT` block.
* A group's level is `-1` when it is local, and the level of its library when it
  is linked. A group's *required* level is `max(level of each group it uses)+1`,
  where an unlinked dependency counts as level 0.

---

## 2. Invariants

Every operation must leave the project satisfying all of these.

1. **One home.** A group is stored in exactly one file. A move removes it from
   the old home, never copies it.
2. **Level rule.** After a move, the group's new level is strictly above every
   dependency, and no file links a group stored above it.
3. **Every user follows.** After a move or rename, *every* file that references
   the group resolves it, whatever its level — a file below or beside the
   group can still link it. Filtering by level is the bug this rule exists to
   prevent.
4. **Load before remove.** The replacement is linked before the stale datablock
   is touched, and users are remapped while it is still alive. Removing first
   frees the tree under group nodes that still point at it, which loses the
   users and raises `StructRNA ... has been removed`.
5. **No silent duplicate.** Storing a group where it already lives is refused,
   not performed.
6. **No dragged dependencies.** Linking a group also pulls in the groups it
   uses. Only the named group ends up stored in the target.
7. **Unreadable is not skippable.** A `.blend` that BAT cannot parse is treated
   as a possible user and included in the rewrite, never silently dropped.
8. **Failures are reported, not printed and swallowed.** A subprocess reports
   success through a marker line; absence of the marker is a failure.

---

## 3. Features

| #    | Feature                                                                                                                         | Entry point                                                                    | Tests             |
| ---- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ----------------- |
| 3.1  | Preferences: `project_directory`, `file_prefix`, `file_suffix`, `blender_executable`                                            | Add-on preferences; `preferences.settings()` mirrors them as a plain dataclass | `test_levels`     |
| 3.2  | Level detection: `find_level_from_path`, `node_group_level` (required level), `get_level_from_ng` (current level, `-1` = local) | —                                                                              | `test_levels`     |
| 3.3  | Level file discovery: `level_files()`, `children_files(parent, lvl)`                                                            | —                                                                              | `test_levels`     |
| 3.4  | Move a group into a level file, creating it if missing                                                                          | `node.myn_move_node_group`                                                     | `test_move`       |
| 3.5  | Rename a group and propagate the name                                                                                           | `node.myn_rename_node_group`                                                   | `test_rename`     |
| 3.6  | Find socket users: per instantiating group, report node name, socket presence, connection and links                             | `nodes.myn_find_nodegroup_socket_users`                                        | `test_find_users` |
| 3.7  | Rename `NODES` modifiers to their group's name                                                                                  | `object.myn_rename_gn_modifiers_to_group_name`                                 | `test_modifiers`  |
| 3.8  | Node group report: per file, local vs linked and from where; flags duplicates, collisions, similar names                        | `node.myn_node_group_report`                                                   | `test_report`     |
| 3.9  | BAT helpers: `local_node_group_name`, `library_path`, `node_groups_in_blend`, `libraries_in_blend`                              | `bat_utils`                                                                    | `test_report`     |
| 3.10 | Add a group node for every local Geometry Nodes group, gridded from the cursor                                                  | `node.add_local_geometry_node_groups`                                          | none              |

`preferences.settings()` returns a `Settings` dataclass that mirrors the
registered `AddonPreferences` when the add-on is enabled and acts as the source
of truth when it is not. RNA structs cannot be instantiated outside the add-on
registry, so this indirection is what makes the path helpers testable.

`find_users` is pure analysis and must work in `--background`: it opens no
windows. `open_pinned_windows` is the separate GUI half, called only by the
operator.

The report scans level files and writes to the system console and to a
`BAT_NodeGroup_Report_<name>` text datablock.

---

## 4. Code map

```
src/move_yo_node/__init__.py       level logic, operators, subprocess scripts, reference index
src/move_yo_node/preferences.py    Settings dataclass + AddonPreferences
src/move_yo_node/bat_utils.py      thin wrappers over blender_asset_tracer
src/move_yo_node/node_report.py    per-file report and its operator
src/move_yo_node/wheels/           bundled BAT wheel, declared by blender_manifest.toml
run_tests.py                       launches the suite inside Blender
```

Moves and renames share one index: `group_references()` parses each `.blend` in
the project folder once and returns `group name -> files that reference it`.
Operations look their targets up there instead of re-reading files per check.

---

## 5. Testing

```
python run_tests.py              # everything
python run_tests.py test_move    # one module
python run_tests.py -v           # verbose
```

Tests import `bpy`, so they run inside Blender, launched with `--background
--factory-startup --python-exit-code 1`. Blender comes from `MYN_BLENDER`; the
runner must not search the filesystem for it. `MynTestCase` builds a fresh
four-level hierarchy in a temporary directory per test (fixtures from
`tests/build_fixtures.py`, no `.blend` committed) and points the preferences at
it. Assertions about results are made against the bytes on disk via BAT, not
against the session, because a move happens in another process.

This document asserts nothing about the current pass rate. Run the suite.

---

## 6. Known problems

1. **Move refuses its own home.** `move_ng_to_level_file` returns `False` when
   the target file already stores the group. Three tests in `test_move.py`
   (`test_move_local_group_to_level_zero`, `test_move_relinks_children`,
   `test_move_preserves_group_usage_in_children`) expect success for exactly
   that case, while `test_move_does_not_duplicate_when_target_already_has_it`
   expects refusal. Pick one: no-op success, or refusal with the tests fixed.
2. **The linked branch does not relink the old home.** Moving a group that is
   linked from elsewhere deletes it from the file that stored it
   (`_remove_group_from`) and then excludes that file from the remap pass. Any
   group in that file that used it is left with a dangling node. The local
   branch does relink (`_move_group_script`); the two branches disagree.
3. **`bat_utils` is used without being imported** in `__init__.py`. It resolves
   only because `node_report` imports the submodule first.
4. **`run_tests.py` searches `C:/Program Files/Blender Foundation`**, which the
   project rules forbid. It must rely on `MYN_BLENDER` alone.
5. **`wheels/*.whl` is gitignored but required** by the manifest and by the
   tests, so a fresh clone cannot build the add-on or run the suite until the
   wheel is fetched again.
6. **Dead and duplicated code.** `children_files` is now used only by tests;
   `_stored_groups` duplicates `bat_utils.node_groups_in_blend`;
   `remap_in_children_files` takes `lvl` and ignores it; `GREEN` is unused.
7. **Level files are linked by absolute path.** Moving or renaming the project
   folder breaks every link; storing `//SP Level 0.blend` would fix it.
8. **`make_local(type='ALL')` scope.** `_store_group_script` runs it under
   `temp_override(id=ng)`; whether it can also localize unrelated linked
   datablocks in the target is unverified.

---

## 7. Not implemented

Intended workflows, recorded from the project's history:

- Make a linked group local, edit it, push it back and relink.
- Append a group, edit it, replace the original.
- Copy a group to an arbitrary file.
- Move dependent groups automatically when a group is pushed up a level.
- Move by linking into the target instead of appending a copy.
