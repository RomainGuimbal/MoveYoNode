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
    """Name of a local bNodeTree / NT block, without the 'NT' ID code prefix."""
    raw = safe_get(block, b"id_name")
    if not raw:
        raw = safe_get(block, (b"id", b"name"))
    name = decode(raw)
    if name and name.startswith("NT"):
        return name[2:]
    return name


def library_path(block):
    """
    Return the source library path for a linked datablock, or None if local.

    bNodeTree has no top-level 'lib' field; the library pointer lives in the
    embedded ID struct, so it must be read as (b"id", b"lib").
    """
    lib = safe_pointer(block, (b"id", b"lib"))
    if lib is None:
        return None

    lib_name = decode(safe_get(lib, b"name"))
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

    Linked node groups are not stored as NT blocks in the referencing file, so
    the libraries they come from are reported separately under the name of the
    library file. Callers that need "does this file reference group X" should
    check the library list rather than expecting an NT block.
    """
    infos = []

    for block in bfile.find_blocks_from_code(b"NT"):
        name = local_node_group_name(block)
        if not name:
            continue

        lib = library_path(block)
        infos.append(
            {
                "name": name,
                "linked": bool(lib),
                "library": lib,
            }
        )

    seen = set()
    unique = []
    for info in infos:
        key = (info["name"], info["linked"], info["library"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(info)

    return unique


def libraries_in_blend(bfile):
    """Paths of every library a .blend file links from."""
    paths = []
    for block in bfile.find_blocks_from_code(b"LI"):
        name = decode(safe_get(block, b"name"))
        if not name:
            continue
        try:
            if name.startswith("//"):
                paths.append(str((bfile.filepath.parent / name[2:]).resolve()))
            else:
                p = Path(name)
                if not p.is_absolute():
                    p = (bfile.filepath.parent / p).resolve()
                paths.append(str(p))
        except Exception:
            paths.append(name)
    return paths