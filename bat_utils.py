from pathlib import Path

# ---------------------------------------------------------------------------
# Low-level BAT helpers
# ---------------------------------------------------------------------------

def safe_get(block, path, default=None):
    """Read a field from a BAT BlendFileBlock without raising on missing fields."""
    try:
        return block.get(path, default)
    except Exception:
        return default


def safe_pointer(block, path):
    """Dereference a pointer without raising."""
    try:
        return block.get_pointer(path, None)
    except Exception:
        return None


def decode(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def local_node_group_name(block):
    """Name of a local bNodeTree / NT block."""
    for path in ((b"id", b"name"), b"name"):
        raw = safe_get(block, path)
        if raw:
            return decode(raw)
    return None


def linked_id_node_group_name(block):
    """
    Name of a linked ID block.

    Linked datablocks in a .blend are stored as ID blocks whose names are
    prefixed with the two-character ID code, e.g. b'NTMyNodeGroup'.
    """
    raw = safe_get(block, b"name")
    if not raw:
        raw = safe_get(block, (b"id", b"name"))

    name = decode(raw)
    if name and name.startswith("NT"):
        return name[2:]
    return None


def library_path(block, is_id_block):
    """
    Return the source library path for a linked datablock, or None if local.
    """
    if is_id_block:
        lib = safe_pointer(block, b"lib")
    else:
        lib = safe_pointer(block, (b"id", b"lib"))
        # Fallback in case BAT stored the block differently.
        if lib is None:
            lib = safe_pointer(block, b"lib")

    if lib is None:
        return None

    raw_name = safe_get(lib, b"name")
    lib_name = decode(raw_name)

    if not lib_name:
        return "<library block without filepath>"

    try:
        if lib_name.startswith("//"):
            return str((block.bfile.filepath.parent / lib_name[2:]).resolve())

        p = Path(lib_name)
        if not p.is_absolute():
            p = (block.bfile.filepath.parent / p).resolve()
        return str(p)
    except Exception:
        return lib_name


def node_groups_in_blend(bfile):
    """
    Collect all node group datablocks in one .blend file.

    Returns a list of dicts:
        name, linked, library
    """
    infos = []

    # Local node trees (bNodeTree / NT blocks)
    for block in bfile.find_blocks_from_code(b"NT"):
        name = local_node_group_name(block)
        if not name:
            continue

        lib = library_path(block, is_id_block=False)
        infos.append({
            "name": name,
            "linked": bool(lib),
            "library": lib,
        })

    # Linked ID blocks. Linked node groups are stored as ID blocks
    # named b'NTNodeGroupName'.
    for block in bfile.find_blocks_from_code(b"ID"):
        name = linked_id_node_group_name(block)
        if not name:
            continue

        lib = library_path(block, is_id_block=True)
        infos.append({
            "name": name,
            "linked": True,
            "library": lib,
        })

    # Deduplicate the same linked entry if it appears both as NT and ID.
    seen = set()
    unique = []
    for info in infos:
        key = (info["name"], info["linked"], info["library"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(info)

    return unique