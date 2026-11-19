"""Tests for level detection and the preferences-backed path helpers."""

import bpy

from move_yo_node import preferences
from move_yo_node.tests import MynTestCase


class TestFindLevelFromPath(MynTestCase):
    def test_absolute_path(self):
        from move_yo_node import find_level_from_path

        self.assertEqual(find_level_from_path("C:/proj/SP Level 0.blend"), 0)
        self.assertEqual(find_level_from_path("C:/proj/SP Level 12.blend"), 12)

    def test_relative_path(self):
        from move_yo_node import find_level_from_path

        self.assertEqual(find_level_from_path("//SP Level 3.blend"), 3)

    def test_backslashes(self):
        from move_yo_node import find_level_from_path

        self.assertEqual(find_level_from_path("C:\\proj\\SP Level 2.blend"), 2)

    def test_non_level_file(self):
        from move_yo_node import find_level_from_path

        self.assertEqual(find_level_from_path("C:/proj/Other.blend"), -1)
        self.assertEqual(find_level_from_path(""), -1)
        self.assertEqual(find_level_from_path(None), -1)

    def test_respects_prefix_preference(self):
        from move_yo_node import find_level_from_path

        cfg = preferences.settings()
        cfg.file_prefix = "ASSET"
        self.assertEqual(find_level_from_path("C:/proj/ASSET Level 4.blend"), 4)
        self.assertEqual(find_level_from_path("C:/proj/SP Level 4.blend"), -1)


class TestPreferencesPaths(MynTestCase):
    def test_project_directory_from_preference(self):
        self.assertEqual(preferences.project_directory(), self.tmpdir)

    def test_level_file_path(self):
        path = preferences.level_file_path(2)
        self.assertEqual(path, self.tmpdir / "SP Level 2.blend")
        self.assertTrue(path.is_file())

    def test_level_file_glob(self):
        self.assertEqual(preferences.level_file_glob(), "SP Level *.blend")

    def test_blender_executable_defaults_to_running_binary(self):
        cfg = preferences.settings()
        cfg.blender_executable = ""
        self.assertEqual(preferences.blender_executable(), bpy.app.binary_path)

    def test_blender_executable_from_preference(self):
        cfg = preferences.settings()
        cfg.blender_executable = "C:/custom/blender.exe"
        self.assertEqual(preferences.blender_executable(), "C:/custom/blender.exe")


class TestLevelFiles(MynTestCase):
    def test_lists_all_level_files_sorted(self):
        from move_yo_node import level_files

        files = level_files()
        self.assertEqual(len(files), 4)
        self.assertEqual([f.name for f in files], [f"SP Level {i}.blend" for i in range(4)])

    def test_ignores_non_level_files(self):
        from move_yo_node import level_files

        (self.tmpdir / "unrelated.blend").write_bytes(b"")
        self.assertEqual(len(level_files()), 4)
