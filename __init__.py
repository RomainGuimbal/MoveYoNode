import bpy
from os.path import isfile
import subprocess
import glob
from pathlib import Path

###############################
DIRECTORY = "C:/Users/romai/Documents/Projets/26 - Bezier Quest/"
PREFIX = DIRECTORY + "SP Assets"

BLUE = "\033[94m"
RED = "\033[91m"
RESET = "\033[0m"
# To move as a preference
###############################


def append_node_group_to_file(target_filepath, node_group_name):
    source_path = bpy.data.filepath.replace("\\", "/")

    script = (
        f"import bpy"
        + f"\nwith bpy.data.libraries.load('{source_path}', link=True, recursive=False) as (_, data_to):"
        + f"\n  data_to.node_groups = ['{node_group_name}']"
        + "\nng = data_to.node_groups[0]"
        + "\nif ng is not None:"
        + "\n    ng.make_local()"
        + "\n    ng.use_fake_user = True"
        + "\n    bpy.ops.wm.save_mainfile()"
        + f"\nelse: print(f'{'RED'}Node group not found{'RESET'}')"
    )

    command = ["blender", "--background", target_filepath, "--python-expr", script]

    # Run the command
    subprocess.run(command, check=True)


def link_node_group(target_filepath, ng_name: str) -> list[bpy.types.NodeGroup]:
    with bpy.data.libraries.load(target_filepath, link=True, recursive=False) as (
        _,
        data_to,
    ):
        data_to.node_groups = [ng_name]

    linked_ng = data_to.node_groups[0]
    return linked_ng


def create_file(filepath):
    """Create an empty .blend file at the specified path without affecting the current session or leaving temporary files."""
    # Command to run Blender in the background and execute a Python command directly
    command = [
        "blender",
        "--background",
        "--python-expr",
        f"import bpy; bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.wm.save_as_mainfile(filepath='{filepath}')",
    ]

    # Run the command
    subprocess.run(command, check=True)


def remap_in_children_files(new_file, ng_name):
    """
    Remap in every file of the current folder
    """
    files = glob.glob(DIRECTORY + "SP*.blend")

    script = (
        "import bpy"
        + f"\nif '{ng_name}' in bpy.data.node_groups.keys():"
        + f"\n  existing=bpy.data.node_groups['{ng_name}']"
        + f"\n  with bpy.data.libraries.load('{new_file}', link=True, recursive = False) as (_, data_to):"
        + f"\n      data_to.node_groups = ['{ng_name}']"
        + "\nng = data_to.node_groups[0]"
        + "\nif ng is not None:"
        + f"\n  existing.user_remap(data_to.node_groups[0]);bpy.ops.wm.save_mainfile()"
        + "\nelse:"
        + f"\n  print(f'{'RED'}Node group not found{'RESET'}')"
    )

    for f in files:
        if Path(f) != Path(bpy.data.filepath) and Path(f) != Path(
            new_file
        ):  # TODO filter lower levels too
            command = [
                "blender",
                "--background",
                "--factory-startup",  # Not sure it's faster
                f,
                "--python-expr",
                script,
            ]

        # Run the command
        subprocess.run(command, check=True)


def move_ng_to_level_file(ng_name: str, level):
    target_filepath = f"{PREFIX} Level {level}.blend"

    # Create file
    if not isfile(target_filepath):
        create_file(target_filepath)

    replaced_ng = bpy.data.node_groups[ng_name]

    append_node_group_to_file(target_filepath, ng_name)
    linked_ng = link_node_group(target_filepath, ng_name)
    if linked_ng is not None:
        replaced_ng.user_remap(linked_ng)
        remap_in_children_files(target_filepath, ng_name)
        return True
    return False


class MYN_OT_move_node_group(bpy.types.Operator):
    bl_idname = "wm.myn_move_node_group"
    bl_label = "MYN - Move Node Group"
    bl_options = {"REGISTER", "UNDO"}

    level: bpy.props.IntProperty(
        name="Dependency Level", description="", default=0, min=0
    )

    @classmethod
    def poll(cls, context):
        return context.area.type == "NODE_EDITOR"

    def execute(self, context):
        ng_name = context.space_data.edit_tree.nodes.active.node_tree.name
        print(ng_name)
        if move_ng_to_level_file(ng_name, self.level):
            self.report({"INFO"}, f"Node group moved successfully")
        else:
            self.report({"ERROR"}, f"Node group move failed")
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "level")

    def invoke(self, context, event):
        # call itself and run
        wm = context.window_manager
        return wm.invoke_props_dialog(self)


classes = [
    MYN_OT_move_node_group,
]


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in classes[::-1]:
        bpy.utils.unregister_class(c)


if __package__ == "__main__":
    register()

# TODO auto find which level : - all contained ng must be at lower levels
# TODO move between level : Must use linking and not append somehow
# TODO auto move all children when a group is upgraded
# TODO de-duplicate, rename and other utils
# TODO append>edit>replace workflow


# Level 0 : small utils ----> Level n : end user tools
# SPO "SurfacePsycho Organizer"
