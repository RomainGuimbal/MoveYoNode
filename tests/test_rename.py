"""Tests for renaming a node group across the level hierarchy."""

import bpy

from move_yo_node import (
    file_contains_node_group,
    get_level_from_ng,
    remap_name_in_files,
    rename_node_group,
)
from move_yo_node.tests import MynTestCase


class TestRenameNodeGroup(MynTestCase):
    def test_rename_local_group(self):
        self.open_level(0)
        self.assertTrue(rename_node_group("BaseGroup", "RenamedBase", -1, bpy.data.filepath))
        self.assertIsNone(bpy.data.node_groups.get("BaseGroup"))
        self.assertIsNotNone(bpy.data.node_groups.get("RenamedBase"))

    def test_rename_rejects_empty_name(self):
        self.open_level(0)
        self.assertFalse(rename_node_group("BaseGroup", "", -1, bpy.data.filepath))
        self.assertIsNotNone(bpy.data.node_groups.get("BaseGroup"))

    def test_rename_rejects_same_name(self):
        self.open_level(0)
        self.assertFalse(rename_node_group("BaseGroup", "BaseGroup", -1, bpy.data.filepath))

    def test_rename_unknown_group_fails(self):
        self.open_level(0)
        self.assertFalse(rename_node_group("NoSuchGroup", "Whatever", -1, bpy.data.filepath))

    def test_rename_updates_children_files(self):
        """Renaming a group stored at level 0 must rename it in level 1 too."""
        self.open_level(0)
        self.assertTrue(rename_node_group("BaseGroup", "RenamedBase", 0, str(self.paths[0])))

        self.open_level(1)
        self.assertIsNotNone(bpy.data.node_groups.get("RenamedBase"))
        self.assertIsNone(bpy.data.node_groups.get("BaseGroup"))

    def test_rename_keeps_group_node_connection(self):
        """The group node in the child must still point at a valid tree."""
        self.open_level(0)
        self.assertTrue(rename_node_group("BaseGroup", "RenamedBase", 0, str(self.paths[0])))

        self.open_level(1)
        node = self.group_node("MidGroup", "BaseGroupNode")
        self.assertIsNotNone(node.node_tree)
        self.assertEqual(node.node_tree.name, "RenamedBase")


class TestRemapNameInFiles(MynTestCase):
    def test_remap_skips_current_file(self):
        """The current file is renamed by the caller, not by remap_name_in_files."""
        self.open_level(0)
        remap_name_in_files("BaseGroup", "RenamedBase", 0, str(self.paths[0]))
        # Level 0 is the current file, so it is untouched by the remap pass.
        self.assertIsNotNone(bpy.data.node_groups.get("BaseGroup"))

    def test_remap_does_not_touch_lower_levels(self):
        self.open_level(2)
        remap_name_in_files("BaseGroup", "RenamedBase", 2, str(self.paths[2]))
        self.assertTrue(file_contains_node_group(self.paths[0], "BaseGroup"))


class TestRenameOperator(MynTestCase):
    def test_operator_is_registered(self):
        self.assertTrue(hasattr(bpy.types, "NODE_OT_myn_rename_node_group"))

    def test_operator_poll_requires_node_editor(self):
        op = bpy.types.NODE_OT_myn_rename_node_group
        self.assertFalse(op.poll(bpy.context))
