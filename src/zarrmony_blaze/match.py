"""Cheap predicate that identifies a Blaze (MACS iQ-processed) experiment dir.

Requires *both* the ``_Blaze_`` vendor token AND a ``_Z0000.ome.tif`` master
filename in the directory. The ``_Blaze_`` literal prevents accidental hijack
of unrelated OME multi-file directories. Side-effect-free and never opens a
file: single ``iterdir()``, early return on first hit.
"""

from pathlib import Path


def match(path: Path) -> int | None:
    if not path.is_dir():
        return None
    for entry in path.iterdir():
        name = entry.name
        if entry.is_file() and "_Blaze_" in name and name.endswith("_Z0000.ome.tif"):
            return 100
    return None
