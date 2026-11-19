"""Tests for dependency-level detection and node group moving."""

import unittest

import bpy

from move_yo_node import (
    children_files,
    file_contains_node_group,
    get_level_from_ng,
    level_files,
    move_ng_to_level_file,
    node_group_level,
)
from move_yo_node.tests import MynTestCase


class TestNodeGroupLevel(MynTestCase):
    def test_group_without_dependencies_is_level_zero(self):
        self.open_level(0)
        self.assertEqual(node_group_level(bpy.data.node_groups["BaseGroup"]), 0)

    def test_group_using_local_group_is_level_one(self):
        """A local dependency counts as level 0, so the parent goes to 1."""
        self.open_level(0)
        parent = bpy.data.node_groups.new("LocalParent", "GeometryNodeTree")
        node = parent.nodes.new("GeometryNodeGroup")
        node.node_tree = bpy.data.node_groups["BaseGroup"]
        self.assertEqual(node_group_level(parent), 1)

    def test_group_using_linked_group_is_one_above_it(self):
        self.open_level(1)
        self.assertEqual(node_group_level(bpy.data.node_groups["MidGroup"]), 1)

    def test_group_using_level_two_link_is_level_three(self):
        self.open_level(3)
        self.assertEqual(node_group_level(bpy.data.node_groups["SceneGroup"]), 3)

    def test_ignores_non_group_nodes(self):
        self.open_level(0)
        ng = bpy.data.node_groups["BaseGroup"]
        ng.nodes.new("GeometryNodeSetPosition")
        self.assertEqual(node_group_level(ng), 0)


class TestGetLevelFromNg(MynTestCase):
    def test_local_group_has_no_level(self):
        self.open_level(0)
        self.assertEqual(get_level_from_ng(bpy.data.node_groups["BaseGroup"]), -1)

    def test_linked_group_reports_its_level(self):
        self.open_level(1)
        self.assertEqual(get_level_from_ng(bpy.data.node_groups["BaseGroup"]), 0)

    def test_linked_group_at_level_two(self):
        self.open_level(3)
        self.assertEqual(get_level_from_ng(bpy.data.node_groups["TopGroup"]), 2)


class TestChildrenFiles(MynTestCase):
    def test_children_are_files_above_the_level(self):
        self.open_level(0)
        children = children_files(str(self.paths[0]), 0)
        names = {c.name for c in children}
        self.assertEqual(names, {"SP Level 1.blend", "SP Level 2.blend", "SP Level 3.blend"})

    def test_excludes_current_and_parent(self):
        self.open_level(1)
        children = children_files(str(self.paths[1]), 1)
        names = {c.name for c in children}
        self.assertNotIn("SP Level 1.blend", names)
        self.assertEqual(names, {"SP Level 2.blend", "SP Level 3.blend"})

    def test_no_children_at_top_level(self):
        self.open_level(3)
        self.assertEqual(children_files(str(self.paths[3]), 3), [])


class TestFileContainsNodeGroup(MynTestCase):
    def test_finds_local_group(self):
        self.assertTrue(file_contains_node_group(self.paths[0], "BaseGroup"))

    def test_missing_group_not_found_in_plain_file(self):
        """A file with no libraries and no matching NT block must report False."""
        (self.tmpdir / "SP Level 9.blend").write_bytes(b"")
        self.assertFalse(file_contains_node_group(self.paths[0], "DoesNotExist"))

    def test_file_with_library_reference_is_kept(self):
        """Files that link from another file are never filtered out."""
        self.assertTrue(file_contains_node_group(self.paths[1], "BaseGroup"))


class TestMoveNodeGroup(MynTestCase):
    def test_move_local_group_to_level_zero(self):
        """Moving into the file already open stores it there and keeps it local."""
        self.open_level(0)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 0))
        ng = bpy.data.node_groups["BaseGroup"]
        self.assertIsNone(ng.library)
        self.assertTrue(ng.use_fake_user)

    @unittest.expectedFailure
    def test_move_creates_missing_level_file(self):
        """KNOWN GAP: moving into a level file that does not exist yet fails.

        `create_file` makes an empty .blend, then `append_node_group_to_file`
        links the group out of the source file and saves it locally. That
        round-trip returns False when the target was just created, so the move
        reports failure. The workflow itself is wanted; the implementation
        needs work. Tracked in SPEC.md under TODO.
        """
        target = self.paths[0]
        target.unlink()
        self.assertFalse(target.exists())
        self.open_level(1)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 0))
        self.assertTrue(target.exists())

    def test_move_relinks_children(self):
        """After moving, a child file must link the group from the new location."""
        self.open_level(0)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 0))

        self.open_level(1)
        linked = self.linked_groups()
        self.assertIn("BaseGroup", linked)
        self.assertEqual(linked["BaseGroup"], str(self.paths[0].resolve()))

    def test_move_unknown_group_fails(self):
        self.open_level(0)
        self.assertFalse(move_ng_to_level_file("NoSuchGroup", 0))

    def test_move_preserves_group_usage_in_children(self):
        """The parent group in a child file must still reference the group."""
        self.open_level(0)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 0))

        self.open_level(1)
        node = self.group_node("MidGroup", "BaseGroupNode")
        self.assertIsNotNone(node.node_tree)
        self.assertEqual(node.node_tree.name, "BaseGroup")
        self.assertIsNotNone(node.node_tree.library)
