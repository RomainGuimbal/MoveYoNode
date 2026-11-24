"""Tests for the modifier-renaming operator."""

import bpy

from move_yo_node.tests import MynTestCase


class TestRenameModifiers(MynTestCase):
    def setUp(self):
        super().setUp()
        self.open_level(0)
        self.ng = bpy.data.node_groups["BaseGroup"]

    def _object_with_modifier(self, name, ng, mod_name="GeometryNodes"):
        mesh = bpy.data.meshes.new(f"{name}Mesh")
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        mod = obj.modifiers.new(mod_name, "NODES")
        mod.node_group = ng
        return obj, mod

    def test_renames_modifier_to_group_name(self):
        obj, mod = self._object_with_modifier("Obj", self.ng)
        bpy.ops.object.myn_rename_gn_modifiers_to_group_name()
        self.assertEqual(mod.name, "BaseGroup")

    def test_ignores_non_nodes_modifiers(self):
        mesh = bpy.data.meshes.new("PlainMesh")
        obj = bpy.data.objects.new("Plain", mesh)
        bpy.context.scene.collection.objects.link(obj)
        mod = obj.modifiers.new("Subdiv", "SUBSURF")
        bpy.ops.object.myn_rename_gn_modifiers_to_group_name()
        self.assertEqual(mod.name, "Subdiv")

    def test_ignores_nodes_modifier_without_group(self):
        mesh = bpy.data.meshes.new("EmptyMesh")
        obj = bpy.data.objects.new("Empty", mesh)
        bpy.context.scene.collection.objects.link(obj)
        mod = obj.modifiers.new("EmptyGN", "NODES")
        bpy.ops.object.myn_rename_gn_modifiers_to_group_name()
        self.assertEqual(mod.name, "EmptyGN")

    def test_renames_across_multiple_objects(self):
        obj_a, mod_a = self._object_with_modifier("A", self.ng)
        obj_b, mod_b = self._object_with_modifier("B", self.ng)
        bpy.ops.object.myn_rename_gn_modifiers_to_group_name()
        self.assertEqual(mod_a.name, "BaseGroup")
        self.assertEqual(mod_b.name, "BaseGroup")

    def test_operator_is_registered(self):
        self.assertTrue(hasattr(bpy.types, "OBJECT_OT_myn_rename_gn_modifiers_to_group_name"))
