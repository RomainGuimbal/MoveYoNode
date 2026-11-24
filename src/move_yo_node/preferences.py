"""Addon preferences for move_yo_node.

All user-chosen locations the addon touches are preferences, never module
globals. This keeps the addon usable on any machine and lets the test harness
point it at a temporary directory. The Blender binary is not one of them: the
running binary is always the right one (see ``blender_binary``).

The path helpers read from a plain ``Settings`` object. When the addon is
installed, ``Settings`` mirrors the registered ``AddonPreferences``; when it is
not (Text Editor, test harness), ``Settings`` is the source of truth. RNA
structs cannot be instantiated outside the addon registry, so this indirection
is what makes the helpers testable.
"""

from dataclasses import dataclass

import bpy

ADDON_ID = __package__ or "move_yo_node"

# Default file naming convention: "<prefix> Level <n>.blend"
DEFAULT_FILE_PREFIX = "SP"
DEFAULT_FILE_SUFFIX = "Level"


@dataclass
class Settings:
    """Plain, instantiable mirror of the addon preferences."""

    project_directory: str = ""
    file_prefix: str = DEFAULT_FILE_PREFIX
    file_suffix: str = DEFAULT_FILE_SUFFIX


_settings = Settings()


def settings() -> Settings:
    """Current settings, synced from the registered preferences when available."""
    prefs = registered_preferences()
    if prefs is not None:
        _settings.project_directory = prefs.project_directory
        _settings.file_prefix = prefs.file_prefix
        _settings.file_suffix = prefs.file_suffix
    return _settings


def registered_preferences(context=None):
    """The live AddonPreferences, or None when the addon is not installed."""
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon is not None else None


class MYN_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    project_directory: bpy.props.StringProperty(
        name="Project Directory",
        description=(
            "Folder containing the level .blend files. "
            "Leave empty to use the folder of the current .blend file"
        ),
        default="",
        subtype="DIR_PATH",
    )

    file_prefix: bpy.props.StringProperty(
        name="File Prefix",
        description="Prefix of the level files, e.g. 'SP' for 'SP Level 0.blend'",
        default=DEFAULT_FILE_PREFIX,
    )

    file_suffix: bpy.props.StringProperty(
        name="Level Word",
        description="Word between the prefix and the level number",
        default=DEFAULT_FILE_SUFFIX,
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.prop(self, "project_directory")
        row = col.row(align=True)
        row.prop(self, "file_prefix")
        row.prop(self, "file_suffix")


def project_directory(context=None):
    """Resolve the folder holding the level files.

    Falls back to the current .blend file's folder when the preference is empty,
    which is the common case for a project opened from its own directory.
    """
    from pathlib import Path

    cfg = settings()
    if cfg.project_directory.strip():
        return Path(bpy.path.abspath(cfg.project_directory)).resolve()

    if bpy.data.filepath:
        return Path(bpy.data.filepath).resolve().parent

    return Path.cwd()


def file_prefix(context=None) -> str:
    return settings().file_prefix


def file_suffix(context=None) -> str:
    return settings().file_suffix


def blender_binary() -> str:
    """Blender used for background work: the one this session already runs on.

    Not a preference. A subprocess from another build would rewrite files with
    a version the session cannot read back, so the running binary is the only
    correct choice.
    """
    return bpy.app.binary_path


def level_file_path(level: int, context=None):
    """Path of the .blend file that stores node groups of the given level."""
    name = f"{file_prefix(context)} {file_suffix(context)} {level}.blend"
    return project_directory(context) / name


def level_file_glob(context=None) -> str:
    """Glob pattern matching every level file in the project directory."""
    return f"{file_prefix(context)} {file_suffix(context)} *.blend"


classes = [MYN_AddonPreferences]


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in classes[::-1]:
        bpy.utils.unregister_class(c)
