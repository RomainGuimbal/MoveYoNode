import bpy
from pathlib import Path
from .bat_utils import node_groups_in_blend

REPORT_TEXT_PREFIX = "BAT_NodeGroup_Report"


# ---------------------------------------------------------------------------
# Report analysis
# ---------------------------------------------------------------------------


def _analyze_blend_file(path, target_name):
    from blender_asset_tracer import blendfile

    path = path.resolve()

    try:
        with blendfile.BlendFile(path) as bfile:
            infos = node_groups_in_blend(bfile)
    except Exception as exc:
        return {
            "path": path,
            "filename": path.name,
            "error": f"{type(exc).__name__}: {exc}",
            "infos": [],
            "linked_target": False,
            "local_target": False,
            "sources": [],
            "variants": [],
            "warnings": [],
        }

    target_lower = target_name.lower()

    target_entries = [i for i in infos if i["name"] == target_name]
    linked_targets = [i for i in target_entries if i["linked"]]
    local_targets = [i for i in target_entries if not i["linked"]]

    # Any other group whose name contains the target name.
    variant_entries = [
        i
        for i in infos
        if i["name"] != target_name and target_lower in i["name"].lower()
    ]

    variant_names = sorted({i["name"] for i in variant_entries})

    # Build human-readable variant descriptions.
    variant_descriptions = []
    for variant_name in variant_names:
        entries = [i for i in variant_entries if i["name"] == variant_name]
        flags = []

        if any(not i["linked"] for i in entries):
            flags.append("local")

        linked_libs = sorted(
            {i["library"] for i in entries if i["linked"] and i["library"]}
        )
        if linked_libs:
            flags.append("linked: " + ", ".join(linked_libs))

        variant_descriptions.append(
            f"{variant_name} ({'; '.join(flags) if flags else 'unknown'})"
        )

    warnings = []

    if len(target_entries) > 1:
        warnings.append(
            f"target name appears {len(target_entries)} times "
            f"(possible duplicate node groups)"
        )

    if local_targets and linked_targets:
        warnings.append("both a local and a linked node group use the target name")
    elif local_targets:
        warnings.append(
            "contains a local node group with the target name " "(not a linked copy)"
        )

    if len(linked_targets) > 1:
        warnings.append(
            f"target is linked {len(linked_targets)} times "
            f"(possible duplicate links)"
        )

    if linked_targets and any(not i["library"] for i in linked_targets):
        warnings.append(
            "linked target found but its source library could not be resolved"
        )

    if variant_descriptions:
        warnings.append(
            "similar node group name(s): " + "; ".join(variant_descriptions)
        )

    sources = sorted({i["library"] or "<unresolved>" for i in linked_targets})

    return {
        "path": path,
        "filename": path.name,
        "error": None,
        "infos": infos,
        "linked_target": bool(linked_targets),
        "local_target": bool(local_targets),
        "sources": sources,
        "variants": variant_names,
        "variant_descriptions": variant_descriptions,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------


class MYN_OT_node_group_report(bpy.types.Operator):
    """Scan every .blend file in the current folder for a node group"""

    bl_idname = "node.myn_node_group_report"
    bl_label = "MYN - Node Group Report"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath) and context.area.type == "NODE_EDITOR"

    def execute(self, context):
        node_group_name = context.space_data.edit_tree.nodes.active.node_tree.name

        try:
            from blender_asset_tracer import blendfile  # noqa: F401
        except ImportError:
            self.report(
                {"ERROR"},
                "Blender Asset Tracer is not installed. Install it in Blender's "
                "Python with: pip install blender-asset-tracer",
            )
            return {"CANCELLED"}

        target_name = node_group_name.strip()
        if not target_name:
            return {"CANCELLED"}

        current_path = Path(bpy.data.filepath).resolve()
        folder = current_path.parent

        blend_files = sorted(folder.glob("SP*.blend"))
        results = [_analyze_blend_file(path, target_name) for path in blend_files]

        linked_files = [r for r in results if r.get("linked_target")]
        local_files = [r for r in results if r.get("local_target")]
        warning_files = [r for r in results if r.get("warnings")]
        error_files = [r for r in results if r.get("error")]

        current_result = next(
            (r for r in results if r["path"] == current_path),
            None,
        )
        current_links_target = bool(
            current_result and current_result.get("linked_target")
        )

        # Current Blender session info
        current_ng = bpy.data.node_groups.get(target_name)
        session_lines = []
        if current_ng is None:
            session_lines.append("  node group not found in current session")
        else:
            if current_ng.library:
                session_lines.append(f"  linked from: {current_ng.library.filepath}")
            else:
                session_lines.append("  local node group (not linked)")

        # ------------------------------------------------------------------
        # Build report
        # ------------------------------------------------------------------
        lines = [
            "=" * 72,
            "Blender Asset Tracer - Node Group Report",
            "=" * 72,
            f"Target node group : {target_name}",
            f"Folder            : {folder}",
            f"Scanned           : {len(results)} .blend file(s)",
            "",
            "Current .blend session:",
            *session_lines,
            "",
            "=" * 72,
            "PER-FILE REPORT",
            "=" * 72,
        ]

        for result in results:
            lines.append("")
            lines.append(f"[{result['filename']}]")

            if result["error"]:
                lines.append(f"  ERROR: {result['error']}")
                continue

            if result["linked_target"]:
                lines.append("              links : YES")
                if result["sources"]:
                    for source in result["sources"]:
                        lines.append(f"    source library  : {source}")
                else:
                    lines.append("    source library  : <unresolved>")

            if result["local_target"]:
                lines.append("  local target copy : YES")

            if result["variant_descriptions"]:
                lines.append(
                    "  similar groups    : " + "; ".join(result["variant_descriptions"])
                )

            if result["warnings"]:
                for warning in result["warnings"]:
                    lines.append(f"  WARNING: {warning}")

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        lines.extend(
            [
                "",
                "=" * 72,
                "SUMMARY",
                "=" * 72,
                f"Files linking target        : {len(linked_files)}",
                f"Files with local target copy: {len(local_files)}",
                f"Files with warnings         : {len(warning_files)}",
                f"Files with errors           : {len(error_files)}",
                "",
                "Current file links target   : ",
                f"{'YES' if current_links_target else 'no'}",
            ]
        )

        # Explicitly answer: if another file links it but current does not,
        # where does that linked copy come from?
        other_linked = [r for r in linked_files if r["path"] != current_path]

        if other_linked and not current_links_target:
            lines.extend(
                [
                    "",
                    "Target is linked by other file(s), but not by the current file:",
                ]
            )
            for result in other_linked:
                if result["sources"]:
                    for source in result["sources"]:
                        lines.append(f"  {result['filename']} -> {source}")
                else:
                    lines.append(f"  {result['filename']} -> <unresolved library>")

        report = "\n".join(lines)

        # Print to system console.
        print(report)

        # Write to a Blender Text datablock.
        safe_target = "".join(
            c if (c.isalnum() or c in "._- ") else "_" for c in target_name
        )
        text_name = f"{REPORT_TEXT_PREFIX}_{safe_target}"

        text = bpy.data.texts.get(text_name)
        if text is None:
            text = bpy.data.texts.new(text_name)
        else:
            text.clear()

        text.write(report)

        self.report(
            {"INFO"},
            f"Scanned {len(results)} file(s). "
            f"Report written to Text '{text_name}'.",
        )
        return {"FINISHED"}


classes = [MYN_OT_node_group_report]


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in classes[::-1]:
        bpy.utils.unregister_class(c)
