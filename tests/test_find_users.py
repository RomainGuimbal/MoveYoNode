"""Tests for find_users() — the socket-usage analysis.

find_users() must stay pure analysis so it works in --background. Opening
windows is the caller's job (open_pinned_windows).
"""

import bpy

from move_yo_node import find_users, report_users
from tests import MynTestCase


def _add_group_node(parent, child, name):
    node = parent.nodes.new("GeometryNodeGroup")
    node.node_tree = child
    node.name = name
    return node


class TestFindUsers(MynTestCase):
    def setUp(self):
        super().setUp()
        self.open_level(0)
        # A consumer group that uses BaseGroup and wires its output onward.
        self.consumer = bpy.data.node_groups.new("Consumer", "GeometryNodeTree")
        self.consumer.interface.new_socket(
            "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
        )
        self.consumer.interface.new_socket(
            "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
        )
        self.group_node = _add_group_node(
            self.consumer, bpy.data.node_groups["BaseGroup"], "BaseNode"
        )
        out = self.consumer.nodes.new("NodeGroupOutput")
        self.consumer.links.new(self.group_node.outputs[0], out.inputs[0])

    def test_finds_direct_user(self):
        users = find_users("BaseGroup", 0, "OUTPUT")
        self.assertIn("Consumer", users)
        self.assertEqual(len(users["Consumer"]["nodes"]), 1)

    def test_reports_connected_socket(self):
        users = find_users("BaseGroup", 0, "OUTPUT")
        info = users["Consumer"]["nodes"][0]
        self.assertTrue(info["socket_found"])
        self.assertTrue(info["connected"])
        self.assertEqual(len(info["links"]), 1)

    def test_unconnected_socket_reported_as_not_connected(self):
        users = find_users("BaseGroup", 0, "INPUT")
        info = users["Consumer"]["nodes"][0]
        self.assertTrue(info["socket_found"])
        self.assertFalse(info["connected"])

    def test_socket_by_name(self):
        users = find_users("BaseGroup", "Geometry", "OUTPUT")
        info = users["Consumer"]["nodes"][0]
        self.assertEqual(info["socket_name"], "Geometry")

    def test_missing_socket_index_is_not_found(self):
        users = find_users("BaseGroup", 99, "OUTPUT")
        info = users["Consumer"]["nodes"][0]
        self.assertFalse(info["socket_found"])

    def test_unknown_group_raises(self):
        with self.assertRaises(ValueError):
            find_users("NoSuchGroup", 0, "OUTPUT")

    def test_bad_socket_side_raises(self):
        with self.assertRaises(ValueError):
            find_users("BaseGroup", 0, "SIDEWAYS")

    def test_group_does_not_report_itself(self):
        users = find_users("BaseGroup", 0, "OUTPUT")
        self.assertNotIn("BaseGroup", users)

    def test_works_in_background(self):
        """The whole point of the split: no window is opened."""
        self.assertTrue(bpy.app.background)
        windows_before = len(bpy.context.window_manager.windows)
        find_users("BaseGroup", 0, "OUTPUT")
        self.assertEqual(len(bpy.context.window_manager.windows), windows_before)


class TestReportUsers(MynTestCase):
    def test_report_runs_without_error(self):
        self.open_level(0)
        consumer = bpy.data.node_groups.new("Consumer", "GeometryNodeTree")
        _add_group_node(consumer, bpy.data.node_groups["BaseGroup"], "BaseNode")
        users = find_users("BaseGroup", 0, "OUTPUT")
        report_users(users, "BaseGroup", 0, "OUTPUT")

    def test_report_handles_empty_users(self):
        self.open_level(0)
        report_users({}, "BaseGroup", 0, "OUTPUT")
