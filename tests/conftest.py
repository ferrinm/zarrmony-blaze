"""Synthetic Blaze processed-export fixtures.

The default fixture is the v0.1 tracer-bullet case: one ``_Blaze_C00_Z0000.ome.tif``
master in a directory, T=C=Z=1, no companion files. Built with real
``tifffile.imwrite(..., ome=True)`` so the OME-XML in the master's
ImageDescription is genuine — exactly what ``BlazeReader`` will parse.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile


def write_synthetic_blaze(
    root: Path,
    *,
    sample: str = "SYN",
    size_y: int = 4,
    size_x: int = 4,
    dtype: str = "uint16",
    pixel_size_um: float = 1.5,
    z_step_um: float = 5.0,
) -> Path:
    """Write a minimal 1-channel 1-Z Blaze processed directory under ``root``.

    Filename pattern mirrors a real MACS iQ export
    (``<sample>_Blaze_C00_Z0000.ome.tif``) so the matcher fires.
    """
    root.mkdir(parents=True, exist_ok=True)
    master = root / f"{sample}_Blaze_C00_Z0000.ome.tif"
    np_dtype = np.dtype(dtype)
    rng = np.random.default_rng(0)
    frame = rng.integers(0, np.iinfo(np_dtype).max, size=(size_y, size_x), dtype=np_dtype)
    tifffile.imwrite(
        master,
        frame,
        ome=True,
        metadata={
            "axes": "YX",
            "PhysicalSizeX": pixel_size_um,
            "PhysicalSizeXUnit": "µm",
            "PhysicalSizeY": pixel_size_um,
            "PhysicalSizeYUnit": "µm",
            "PhysicalSizeZ": z_step_um,
            "PhysicalSizeZUnit": "µm",
        },
    )
    return root


@pytest.fixture
def synthetic_blaze_dir(tmp_path: Path) -> Path:
    return write_synthetic_blaze(tmp_path / "experiment")
