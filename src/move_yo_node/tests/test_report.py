"""Tests for the BAT-backed file inspection helpers and the node group report."""

from pathlib import Path

from blender_asset_tracer.blendfile import open_cached

from move_yo_node import bat_utils, node_report
from move_yo_node.tests import MynTestCase


class TestBatUtils(MynTestCase):
    def test_local_node_group_name_strips_nt_prefix(self):
        with open_cached(self.paths[0]) as bfile:
            names = {bat_utils.local_node_group_name(b) for b in bfile.find_blocks_from_code(b"NT")}
        self.assertIn("BaseGroup", names)
        self.assertIn("LeafGroup", names)

    def test_local_groups_are_not_linked(self):
        with open_cached(self.paths[0]) as bfile:
            infos = bat_utils.node_groups_in_blend(bfile)
        by_name = {i["name"]: i for i in infos}
        self.assertFalse(by_name["BaseGroup"]["linked"])
        self.assertIsNone(by_name["BaseGroup"]["library"])

    def test_level_zero_has_no_libraries(self):
        with open_cached(self.paths[0]) as bfile:
            self.assertEqual(bat_utils.libraries_in_blend(bfile), [])

    def test_level_one_links_level_zero(self):
        with open_cached(self.paths[1]) as bfile:
            libs = bat_utils.libraries_in_blend(bfile)
        self.assertEqual(len(libs), 1)
        self.assertEqual(Path(libs[0]).name, "SP Level 0.blend")

    def test_level_one_stores_only_its_own_group(self):
        """Linked groups are not NT blocks, so only MidGroup is listed."""
        with open_cached(self.paths[1]) as bfile:
            names = {i["name"] for i in bat_utils.node_groups_in_blend(bfile)}
        self.assertIn("MidGroup", names)
        self.assertNotIn("BaseGroup", names)

    def test_safe_get_returns_default_on_missing_field(self):
        with open_cached(self.paths[0]) as bfile:
            block = next(iter(bfile.find_blocks_from_code(b"NT")))
            self.assertIsNone(bat_utils.safe_get(block, b"no_such_field"))
            self.assertEqual(bat_utils.safe_get(block, b"no_such_field", 7), 7)

    def test_decode_handles_bytes_and_none(self):
        self.assertEqual(bat_utils.decode(b"abc"), "abc")
        self.assertIsNone(bat_utils.decode(None))
        self.assertEqual(bat_utils.decode(5), "5")


class TestNodeReportAnalysis(MynTestCase):
    def test_finds_local_target(self):
        result = node_report._analyze_blend_file(self.paths[0], "BaseGroup")
        self.assertIsNone(result["error"])
        self.assertTrue(result["local_target"])
        self.assertFalse(result["linked_target"])

    def test_missing_target_reports_nothing(self):
        result = node_report._analyze_blend_file(self.paths[0], "NoSuchGroup")
        self.assertFalse(result["local_target"])
        self.assertFalse(result["linked_target"])

    def test_variant_names_are_detected(self):
        result = node_report._analyze_blend_file(self.paths[0], "Base")
        self.assertIn("BaseGroup", result["variants"])

    def test_local_target_produces_warning(self):
        result = node_report._analyze_blend_file(self.paths[0], "BaseGroup")
        self.assertTrue(any("local node group" in w for w in result["warnings"]))

    def test_unreadable_file_reports_error(self):
        bogus = self.tmpdir / "SP Level 9.blend"
        bogus.write_bytes(b"not a blend file")
        result = node_report._analyze_blend_file(bogus, "BaseGroup")
        self.assertIsNotNone(result["error"])

    def test_report_operator_is_registered(self):
        import bpy

        self.assertTrue(hasattr(bpy.types, "NODE_OT_myn_node_group_report"))
