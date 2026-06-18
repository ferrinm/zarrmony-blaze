"""Reader Protocol adapter for Blaze processed exports (MACS iQ output).

The adapter reads exactly one master ``_Z0000.ome.tif`` for its OME-XML,
parses the XML into a :class:`BlazeOme` view, and builds a dask graph where
each ``(t, c, z)`` plane is a single ``tifffile.imread`` of one companion
file. The master's own pixel plane is read the same way — with
``is_ome=False`` so tifffile does NOT expand the multi-file series itself
(which would stat all companions at construction; see ADR-0001).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import dask
import dask.array as da
import tifffile
import xarray as xr

from ._ome_xml import (
    BlazeMetadataError,
    BlazeMultipositionUnsupportedError,
    BlazeOme,
    parse_master_xml,
)


class BlazeError(Exception):
    """Base class for zarrmony-blaze errors."""


class BlazeMasterNotFoundError(BlazeError):
    """Directory has no ``_Z0000.ome.tif`` master."""


# Re-export so callers can catch a single error namespace.
__all__ = [
    "BlazeError",
    "BlazeMasterNotFoundError",
    "BlazeMetadataError",
    "BlazeMultipositionUnsupportedError",
    "BlazeReader",
]


@dataclass(frozen=True)
class _PixelSizes:
    X: float | None
    Y: float | None
    Z: float | None


def _read_plane(path: str):
    # Wrapper so we can pass is_ome=False through dask.delayed without bouncing
    # tifffile through its multi-file OME expansion (ADR-0001).
    return tifffile.imread(path, is_ome=False)


class BlazeReader:
    layout_hint = "flat"
    plate_layout = None

    def __init__(self, path: Path) -> None:
        self._dir = Path(path)
        masters = sorted(self._dir.glob("*_C00_Z0000.ome.tif")) or sorted(
            self._dir.glob("*_Z0000.ome.tif")
        )
        if not masters:
            raise BlazeMasterNotFoundError(f"no *_Z0000.ome.tif master found in {self._dir}")
        self._master = masters[0]
        with tifffile.TiffFile(self._master) as t:
            xml = t.ome_metadata
        if xml is None:
            raise BlazeMetadataError(
                f"master {self._master.name} has no OME-XML in ImageDescription"
            )
        self._xml = xml
        self._ome: BlazeOme = parse_master_xml(xml)

        for (t, c, z), fname in self._ome.file_map.items():
            if not (self._dir / fname).is_file():
                raise BlazeMetadataError(
                    f"<TiffData> references missing companion file {fname!r} "
                    f"for (t={t}, c={c}, z={z})"
                )

        self.scenes: list[str] = [self._dir.name]
        self._active = 0

    def set_scene(self, index: int) -> None:
        if index != 0:
            raise IndexError(f"scene index {index} out of range; only scene 0 exists")
        self._active = 0

    @property
    def xarray_dask_data(self) -> xr.DataArray:
        o = self._ome
        t_arrs = []
        for t in range(o.size_t):
            c_arrs = []
            for c in range(o.size_c):
                z_arrs = []
                for z in range(o.size_z):
                    fname = o.file_map[(t, c, z)]
                    fpath = self._dir / fname
                    delayed = dask.delayed(_read_plane)(str(fpath))
                    plane = da.from_delayed(delayed, shape=(o.size_y, o.size_x), dtype=o.dtype)
                    z_arrs.append(plane[None, None, None, :, :])
                c_arrs.append(da.concatenate(z_arrs, axis=2))
            t_arrs.append(da.concatenate(c_arrs, axis=1))
        darr = da.concatenate(t_arrs, axis=0)
        return xr.DataArray(
            darr,
            dims=("T", "C", "Z", "Y", "X"),
            coords={"C": o.channel_names},
        )

    @property
    def physical_pixel_sizes(self) -> _PixelSizes:
        o = self._ome
        return _PixelSizes(X=o.pixel_size_x_um, Y=o.pixel_size_y_um, Z=o.pixel_size_z_um)

    @property
    def channel_names(self) -> list[str]:
        return list(self._ome.channel_names)

    @property
    def metadata(self) -> str:
        return self._xml

    def close(self) -> None:
        pass
