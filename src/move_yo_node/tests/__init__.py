"""Test harness for move_yo_node.

The addon imports bpy, so tests must run inside Blender. This module provides:

  * ``MynTestCase`` — a unittest.TestCase that builds a fresh level hierarchy in
    a temporary directory and points the addon preferences at it.
  * ``run_tests.py`` at the repo root — the entry point that launches Blender.

Every Blender process started here uses ``--factory-startup`` so the user's
preferences are never read or written.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import bpy

# This file lives at <repo>/src/move_yo_node/tests/__init__.py, so the package
# root is two levels up. Derived from __file__ — no absolute path is written.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PACKAGE_ROOT.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Make the bundled BAT wheel importable, mirroring what the addon manifest does.
WHEELS = sorted((PACKAGE_ROOT / "wheels").glob("*.whl"))
for wheel in WHEELS:
    if str(wheel) not in sys.path:
        sys.path.insert(0, str(wheel))

import move_yo_node  # noqa: E402
from move_yo_node import bat_utils, preferences  # noqa: E402
from move_yo_node.tests import build_fixtures  # noqa: E402


_registered = False


def ensure_registered():
    """Register the addon once per Blender process."""
    global _registered
    if _registered:
        return
    move_yo_node.register()
    _registered = True


class MynTestCase(unittest.TestCase):
    """Base class giving each test an isolated project directory."""

    prefix = "SP"
    suffix = "Level"

    def setUp(self):
        ensure_registered()
        self.tmpdir = Path(tempfile.mkdtemp(prefix="myn_test_"))
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

        self.fixtures = build_fixtures.build(self.tmpdir, self.prefix, self.suffix)
        self.paths = self.fixtures["paths"]

        cfg = preferences.settings()
        self._saved = {
            "project_directory": cfg.project_directory,
            "file_prefix": cfg.file_prefix,
            "file_suffix": cfg.file_suffix,
            "blender_executable": cfg.blender_executable,
        }
        cfg.project_directory = str(self.tmpdir)
        cfg.file_prefix = self.prefix
        cfg.file_suffix = self.suffix
        cfg.blender_executable = bpy.app.binary_path
        self.addCleanup(self._restore_prefs)

    def _restore_prefs(self):
        cfg = preferences.settings()
        for key, value in self._saved.items():
            setattr(cfg, key, value)

    # ── helpers ──────────────────────────────────────────────────────────

    def open_level(self, level: int):
        bpy.ops.wm.open_mainfile(filepath=str(self.paths[level]))

    def local_groups(self) -> set[str]:
        """Names of node groups stored locally in the open file."""
        return {ng.name for ng in bpy.data.node_groups if not ng.library}

    def linked_groups(self) -> dict[str, str]:
        """Map of linked group name -> absolute library path in the open file."""
        return {
            ng.name: bpy.path.abspath(ng.library.filepath)
            for ng in bpy.data.node_groups
            if ng.library
        }

    def group_node(self, tree_name: str, node_name: str):
        tree = bpy.data.node_groups[tree_name]
        return tree.nodes[node_name]

    def disk_groups(self, path) -> dict[str, str | None]:
        """Node groups actually stored in a .blend on disk.

        Returns name -> library path (None when the group is local to the file).
        Read with Blender Asset Tracer, so the answer comes from the bytes on
        disk rather than from whatever the current session happens to hold.
        """
        from blender_asset_tracer.blendfile import open_cached

        with open_cached(Path(path)) as bfile:
            return {g["name"]: g["library"] for g in bat_utils.node_groups_in_blend(bfile)}

    def disk_libraries(self, path) -> set[str]:
        """Library paths a .blend on disk links from."""
        from blender_asset_tracer.blendfile import open_cached

        with open_cached(Path(path)) as bfile:
            return set(bat_utils.libraries_in_blend(bfile))


def load_tests(loader, standard_tests, pattern):
    """Discover every test_*.py in this package."""
    suite = unittest.TestSuite()
    for test_file in sorted(Path(__file__).parent.glob("test_*.py")):
        module_name = f"move_yo_node.tests.{test_file.stem}"
        suite.addTests(loader.loadTestsFromName(module_name))
    return suite
