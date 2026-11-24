"""Tests for dependency-level detection and node group moving."""

import unittest

import bpy

from move_yo_node import (
    file_contains_node_group,
    get_level_from_ng,
    level_files,
    move_ng_to_level_file,
    node_group_level,
)
from tests import MynTestCase


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


class TestFileContainsNodeGroup(MynTestCase):
    def test_finds_local_group(self):
        self.assertTrue(file_contains_node_group(self.paths[0], "BaseGroup"))

    def test_missing_group_not_found_in_plain_file(self):
        """A file with no libraries and no matching NT block must report False."""
        self.assertFalse(file_contains_node_group(self.paths[0], "DoesNotExist"))

    def test_file_with_library_reference_is_kept(self):
        """Files that link from another file are never filtered out."""
        self.assertTrue(file_contains_node_group(self.paths[1], "BaseGroup"))


class TestMoveNodeGroup(MynTestCase):
    """Moving a node group into a level file.

    Every assertion about what was stored is made against the bytes on disk
    (``disk_groups``), not against the session, because the move happens in
    background Blender processes.
    """

    def test_move_into_the_home_is_refused(self):
        """A move whose target already stores the group changes nothing."""
        self.open_level(1)
        before = self.disk_groups(self.paths[0])

        self.assertFalse(
            move_ng_to_level_file("BaseGroup", 0),
            "a move into the group's own home must be refused",
        )

        self.assertEqual(self.disk_groups(self.paths[0]), before)
        self.assertEqual(self.disk_libraries(self.paths[0]), set())

    def test_move_local_group_creates_missing_level_file(self):
        """A level file that does not exist yet is created and filled."""
        self.open_level(3)
        extra = bpy.data.node_groups.new("ExtraGroup", "GeometryNodeTree")
        extra.use_fake_user = True
        target = self.tmpdir / "SP Level 4.blend"
        target.unlink(missing_ok=True)
        self.assertFalse(target.exists())

        self.assertTrue(move_ng_to_level_file("ExtraGroup", 4))

        self.assertTrue(target.exists())
        self.assertIn("ExtraGroup", self.disk_groups(target))

    def test_created_file_holds_the_group_locally(self):
        """The group must land as a local datablock, not a link to its source."""
        self.open_level(3)
        bpy.data.node_groups.new("ExtraGroup", "GeometryNodeTree").use_fake_user = True
        target = self.tmpdir / "SP Level 4.blend"
        target.unlink(missing_ok=True)

        self.assertTrue(move_ng_to_level_file("ExtraGroup", 4))

        self.assertIsNone(self.disk_groups(target)["ExtraGroup"])

    def test_move_reloads_the_open_file(self):
        """After the move the open file's group is a link to the new home."""
        self.open_level(1)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 2))

        ng = bpy.data.node_groups["BaseGroup"]
        self.assertIsNotNone(ng.library, "the session still holds the old copy")
        self.assertEqual(
            bpy.path.abspath(ng.library.filepath),
            str(self.paths[2].resolve()),
        )

    def test_move_makes_every_linking_file_follow(self):
        """Every file that linked the group points at its new home afterwards."""
        # BaseGroup is stored at level 0 and used by MidGroup at level 1.
        # Moving it to level 2 must repoint level 1 at level 2.
        self.open_level(1)
        self.assertEqual(self.disk_libraries(self.paths[1]), {str(self.paths[0].resolve())})

        self.assertTrue(move_ng_to_level_file("BaseGroup", 2))

        self.assertEqual(
            self.disk_libraries(self.paths[1]),
            {str(self.paths[2].resolve())},
            "level 1 still links the old location",
        )

    def test_move_keeps_group_usable_in_the_linking_file(self):
        """The group node in the follower file must still resolve its tree."""
        self.open_level(1)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 2))

        self.open_level(1)
        node = self.group_node("MidGroup", "BaseGroupNode")
        self.assertIsNotNone(node.node_tree, "the link did not follow")
        self.assertEqual(node.node_tree.name, "BaseGroup")
        self.assertEqual(
            bpy.path.abspath(node.node_tree.library.filepath),
            str(self.paths[2].resolve()),
        )

    def test_move_removes_the_group_from_its_previous_home(self):
        """A move takes the group out of the file that stored it."""
        self.open_level(1)
        self.assertIn("BaseGroup", self.disk_groups(self.paths[0]))

        self.assertTrue(move_ng_to_level_file("BaseGroup", 2))

        self.assertNotIn(
            "BaseGroup",
            self.disk_groups(self.paths[0]),
            "the group was duplicated instead of moved",
        )

    def test_move_makes_the_previous_home_link_the_new_one(self):
        """The old home keeps its group node, linked from the new location."""
        self.open_level(1)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 2))

        self.assertIn(str(self.paths[2].resolve()), self.disk_libraries(self.paths[1]))

    def test_move_does_not_duplicate_when_target_already_has_it(self):
        """Moving a group to the file that stores it is refused, not repeated."""
        self.open_level(2)
        self.assertIn("TopGroup", self.disk_groups(self.paths[2]))
        before = self.disk_groups(self.paths[2])

        self.assertFalse(
            move_ng_to_level_file("TopGroup", 2),
            "a move to the current home must be refused",
        )

        self.assertEqual(self.disk_groups(self.paths[2]), before)

    def test_move_twice_to_the_same_place_is_refused(self):
        """The second move finds the group already there and does nothing."""
        self.open_level(1)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 2))
        after_first = self.disk_groups(self.paths[2])

        self.assertFalse(
            move_ng_to_level_file("BaseGroup", 2),
            "the second move must be refused",
        )

        self.assertEqual(self.disk_groups(self.paths[2]), after_first)
        self.assertIn(str(self.paths[2].resolve()), self.disk_libraries(self.paths[1]))

    def test_move_does_not_drag_dependencies_into_the_target(self):
        """Only the named group is added; its dependencies stay where they are."""
        # MidGroup uses BaseGroup, which lives at level 0.
        self.open_level(1)
        before = set(self.disk_groups(self.paths[2]))

        self.assertTrue(move_ng_to_level_file("MidGroup", 2))

        stored = self.disk_groups(self.paths[2])
        self.assertEqual(set(stored), before | {"MidGroup"})
        self.assertNotIn("BaseGroup", stored, "the dependency was dragged along")
        self.assertIn(
            str(self.paths[0].resolve()),
            self.disk_libraries(self.paths[2]),
            "the dependency is not linked from its own home",
        )

    def test_move_unknown_group_fails(self):
        self.open_level(0)
        self.assertFalse(move_ng_to_level_file("NoSuchGroup", 0))

    def test_move_keeps_the_open_file_usable(self):
        """The group node in the open follower still resolves after the move."""
        self.open_level(1)
        self.assertTrue(move_ng_to_level_file("BaseGroup", 2))

        node = self.group_node("MidGroup", "BaseGroupNode")
        self.assertIsNotNone(node.node_tree)
        self.assertEqual(node.node_tree.name, "BaseGroup")
        self.assertEqual(
            bpy.path.abspath(node.node_tree.library.filepath),
            str(self.paths[2].resolve()),
        )

    def test_move_up_a_level_keeps_children_valid(self):
        """Moving a group into a file above it leaves every user intact."""
        # TopGroup is stored at level 2 and used by SceneGroup at level 3.
        # Pushing it to level 3 puts it beside its only user.
        self.open_level(2)
        self.assertTrue(move_ng_to_level_file("TopGroup", 3))
        self.assertIn("TopGroup", self.disk_groups(self.paths[3]))
        self.assertIsNone(self.disk_groups(self.paths[3])["TopGroup"])

        self.open_level(3)
        node = self.group_node("SceneGroup", "TopGroupNode")
        self.assertIsNotNone(node.node_tree)
        self.assertEqual(node.node_tree.name, "TopGroup")

    def test_move_keeps_existing_contents_of_target(self):
        """Storing a group must not wipe what the target file already holds."""
        self.open_level(2)
        self.assertTrue(move_ng_to_level_file("TopGroup", 3))

        groups = self.disk_groups(self.paths[3])
        self.assertIn("TopGroup", groups)
        self.assertIn("SceneGroup", groups, "level 3 lost its own group")
        self.assertIsNone(groups["SceneGroup"])

    def test_move_leaves_source_file_readable(self):
        """The file a group was moved out of keeps no copy and stays valid."""
        self.open_level(2)
        self.assertTrue(move_ng_to_level_file("TopGroup", 3))

        self.assertIn("TopGroup", self.disk_groups(self.paths[3]))
        self.assertNotIn("TopGroup", self.disk_groups(self.paths[2]))
        # Level 2 stored nothing else and used nothing else, so it references
        # the group no more; the file is still a readable .blend.
        self.assertEqual(self.disk_libraries(self.paths[2]), set())

    def test_move_into_the_open_file_keeps_its_group_node_alive(self):
        """Moving a group into the open file repoints the nodes that used it."""
        self.open_level(3)
        self.assertIn(str(self.paths[2].resolve()), self.disk_libraries(self.paths[3]))

        self.assertTrue(move_ng_to_level_file("TopGroup", 3))

        self.assertIn("TopGroup", self.disk_groups(self.paths[3]))
        self.assertNotIn("TopGroup", self.disk_groups(self.paths[2]))
        node = self.group_node("SceneGroup", "TopGroupNode")
        self.assertIsNotNone(node.node_tree, "the group node lost its node tree")
        self.assertIsNone(node.node_tree.library, "the node still points at the old copy")
        self.assertEqual(node.node_tree.name, "TopGroup")

    def test_move_does_not_touch_lower_level_files(self):
        """Only the target and the files above it are rewritten."""
        self.open_level(2)
        before = self.disk_groups(self.paths[0])
        self.assertTrue(move_ng_to_level_file("TopGroup", 3))
        self.assertEqual(self.disk_groups(self.paths[0]), before)


if __name__ == "__main__":
    unittest.main()
