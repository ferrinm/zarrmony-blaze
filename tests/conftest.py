"""Synthetic Blaze processed-export fixtures.

XML is hand-crafted in the 2008-02 OME schema to mirror what MACS iQ View
actually writes (see CONTEXT.md). ``tifffile.imwrite(..., ome=True)`` would
emit 2016-06 instead, which the adapter explicitly rejects — we don't want
green tests against a schema real exports never use.

Two fixtures:

- ``synthetic_blaze_dir`` — the tracer case: 1 channel × 1 Z, single master.
- ``synthetic_blaze_multi`` — 2 channels × 5 Z, 2 masters + 8 binary-only
  companions. Each plane is a uniform fill of a distinct value so per-chunk
  asserts can check both shape and content.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import tifffile


def _build_master_xml(
    *,
    sample: str,
    size_t: int,
    size_c: int,
    size_z: int,
    size_y: int,
    size_x: int,
    pixel_size_x_um: float,
    pixel_size_y_um: float,
    pixel_size_z_um: float,
    channel_names: list[str],
) -> str:
    """Render a 2008-02 OME master XML referencing every (t,c,z) companion by name."""
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02"',
        '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        f'     UUID="urn:uuid:{uuid.uuid4()}">',
        '  <Image ID="Image:0" Name="synthetic">',
        '    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"'
        f' SizeX="{size_x}" SizeY="{size_y}" SizeZ="{size_z}"'
        f' SizeC="{size_c}" SizeT="{size_t}"'
        f' PhysicalSizeX="{pixel_size_x_um}" PhysicalSizeY="{pixel_size_y_um}"'
        f' PhysicalSizeZ="{pixel_size_z_um}">',
    ]
    for i, name in enumerate(channel_names):
        parts.append(f'      <Channel ID="Channel:{i}" Name="{name}" SamplesPerPixel="1"/>')
    for t in range(size_t):
        for c in range(size_c):
            for z in range(size_z):
                fname = f"{sample}_Blaze_C{c:02d}_Z{z:04d}.ome.tif"
                parts.extend(
                    [
                        f'      <TiffData FirstT="{t}" FirstC="{c}" FirstZ="{z}"'
                        ' IFD="0" PlaneCount="1">',
                        f'        <UUID FileName="{fname}">urn:uuid:{uuid.uuid4()}</UUID>',
                        "      </TiffData>",
                    ]
                )
    parts.extend(["    </Pixels>", "  </Image>", "</OME>"])
    return "\n".join(parts)


def write_synthetic_blaze(
    root: Path,
    *,
    sample: str = "SYN",
    channel_names: tuple[str, ...] = ("C:0",),
    size_z: int = 1,
    size_y: int = 4,
    size_x: int = 4,
    pixel_size_um: float = 1.5,
    z_step_um: float = 5.0,
    plane_value: int | None = None,
) -> Path:
    """Write a synthetic Blaze processed directory under ``root``.

    The C0_Z0000 (and per additional channel, C<i>_Z0000) files are written as
    OME masters carrying the full multi-file XML. All other planes are
    ``BinaryOnly`` companions — plain TIFFs with no OME-XML, which is exactly
    how MACS iQ writes them.
    """
    root.mkdir(parents=True, exist_ok=True)
    size_c = len(channel_names)
    xml = _build_master_xml(
        sample=sample,
        size_t=1,
        size_c=size_c,
        size_z=size_z,
        size_y=size_y,
        size_x=size_x,
        pixel_size_x_um=pixel_size_um,
        pixel_size_y_um=pixel_size_um,
        pixel_size_z_um=z_step_um,
        channel_names=list(channel_names),
    )
    for c in range(size_c):
        for z in range(size_z):
            fname = f"{sample}_Blaze_C{c:02d}_Z{z:04d}.ome.tif"
            value = plane_value if plane_value is not None else (c * 1000 + z + 1)
            data = np.full((size_y, size_x), value, dtype=np.uint16)
            if z == 0:
                tifffile.imwrite(root / fname, data, description=xml, metadata=None)
            else:
                tifffile.imwrite(root / fname, data)
    return root


@dataclass(frozen=True)
class MultiFileFixture:
    dir: Path
    channel_names: tuple[str, ...]
    size_z: int
    size_y: int
    size_x: int
    pixel_size_um: float
    z_step_um: float

    def value_for(self, c: int, z: int) -> int:
        return c * 1000 + z + 1


@pytest.fixture
def synthetic_blaze_dir(tmp_path: Path) -> Path:
    """Tracer case: 1 channel × 1 Z, single master file."""
    return write_synthetic_blaze(tmp_path / "experiment", plane_value=42)


@pytest.fixture
def synthetic_blaze_multi(tmp_path: Path) -> MultiFileFixture:
    """2-channel × 5-Z fixture: 2 masters + 8 binary-only companions."""
    channel_names = ("DAPI", "GFP")
    size_z, size_y, size_x = 5, 4, 4
    pixel_size_um, z_step_um = 1.5, 5.0
    write_synthetic_blaze(
        tmp_path / "experiment_multi",
        sample="MULTI",
        channel_names=channel_names,
        size_z=size_z,
        size_y=size_y,
        size_x=size_x,
        pixel_size_um=pixel_size_um,
        z_step_um=z_step_um,
    )
    return MultiFileFixture(
        dir=tmp_path / "experiment_multi",
        channel_names=channel_names,
        size_z=size_z,
        size_y=size_y,
        size_x=size_x,
        pixel_size_um=pixel_size_um,
        z_step_um=z_step_um,
    )
