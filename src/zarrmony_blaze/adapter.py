"""Reader Protocol adapter for the simplest Blaze processed export.

This is the v0.1 *tracer-bullet* implementation: it handles only the trivial
shape where the directory contains exactly one ``_Z0000.ome.tif`` master file
and that master IS the entire dataset (T=C=Z=1). Multi-channel / multi-Z
exports — which reference companion ``_C<NN>_Z<NNNN>.ome.tif`` files from the
master's ``<TiffData>`` elements — are deferred to a later slice; see
``docs/v0.1-design.md``.

XML parsing uses stdlib ``xml.etree.ElementTree`` rather than ``ome-types``
because the 2008→2016 schema upgrade in ``ome-types`` rejects real MACS iQ
exports outright (see ADR-0001).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import dask
import dask.array as da
import numpy as np
import tifffile
import xarray as xr


class BlazeError(Exception):
    """Base class for zarrmony-blaze errors."""


class BlazeMasterNotFoundError(BlazeError):
    """Directory has no ``_Z0000.ome.tif`` master."""


class BlazeMetadataError(BlazeError):
    """Master OME-XML is missing required fields or self-inconsistent."""


_PIXEL_TYPE_TO_DTYPE: dict[str, np.dtype] = {
    "uint8": np.dtype("uint8"),
    "uint16": np.dtype("uint16"),
    "uint32": np.dtype("uint32"),
    "int8": np.dtype("int8"),
    "int16": np.dtype("int16"),
    "int32": np.dtype("int32"),
    "float": np.dtype("float32"),
    "double": np.dtype("float64"),
}


@dataclass(frozen=True)
class _PixelSizes:
    X: float | None
    Y: float | None
    Z: float | None


@dataclass(frozen=True)
class _BlazePixels:
    size_t: int
    size_c: int
    size_z: int
    size_y: int
    size_x: int
    dtype: np.dtype
    pixel_size_x_um: float | None
    pixel_size_y_um: float | None
    pixel_size_z_um: float | None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_first(root: ET.Element, name: str) -> ET.Element | None:
    for el in root.iter():
        if _local_name(el.tag) == name:
            return el
    return None


def _parse_pixels(xml: str) -> _BlazePixels:
    root = ET.fromstring(xml)
    pixels = _find_first(root, "Pixels")
    if pixels is None:
        raise BlazeMetadataError("master OME-XML has no <Pixels> element")
    try:
        size_t = int(pixels.attrib.get("SizeT", "1"))
        size_c = int(pixels.attrib.get("SizeC", "1"))
        size_z = int(pixels.attrib.get("SizeZ", "1"))
        size_y = int(pixels.attrib["SizeY"])
        size_x = int(pixels.attrib["SizeX"])
    except KeyError as e:
        raise BlazeMetadataError(f"<Pixels> missing required attribute {e}") from e
    pixel_type = pixels.attrib.get("Type") or pixels.attrib.get("PixelType")
    if pixel_type is None:
        raise BlazeMetadataError("<Pixels> missing Type/PixelType attribute")
    try:
        dtype = _PIXEL_TYPE_TO_DTYPE[pixel_type]
    except KeyError as e:
        raise BlazeMetadataError(f"unsupported OME PixelType: {pixel_type!r}") from e

    def _maybe_float(attr: str) -> float | None:
        v = pixels.attrib.get(attr)
        return float(v) if v is not None else None

    return _BlazePixels(
        size_t=size_t,
        size_c=size_c,
        size_z=size_z,
        size_y=size_y,
        size_x=size_x,
        dtype=dtype,
        pixel_size_x_um=_maybe_float("PhysicalSizeX"),
        pixel_size_y_um=_maybe_float("PhysicalSizeY"),
        pixel_size_z_um=_maybe_float("PhysicalSizeZ"),
    )


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
        self._pixels = _parse_pixels(xml)

        if self._pixels.size_t != 1 or self._pixels.size_c != 1 or self._pixels.size_z != 1:
            # Tracer-bullet scope: only the trivial single-file case is wired up.
            # Multi-channel / multi-Z support lands in a later slice.
            raise NotImplementedError(
                "zarrmony-blaze v0.1 tracer supports only T=C=Z=1 "
                f"(got T={self._pixels.size_t}, C={self._pixels.size_c}, "
                f"Z={self._pixels.size_z})"
            )

        self.scenes: list[str] = [self._dir.name]
        self._active = 0

    def set_scene(self, index: int) -> None:
        if index != 0:
            raise IndexError(f"scene index {index} out of range; only scene 0 exists")
        self._active = 0

    @property
    def xarray_dask_data(self) -> xr.DataArray:
        p = self._pixels
        delayed = dask.delayed(tifffile.imread)(str(self._master))
        plane = da.from_delayed(delayed, shape=(p.size_y, p.size_x), dtype=p.dtype)
        darr = plane[None, None, None, :, :]
        return xr.DataArray(
            darr,
            dims=("T", "C", "Z", "Y", "X"),
            coords={"C": self.channel_names},
        )

    @property
    def physical_pixel_sizes(self) -> _PixelSizes:
        p = self._pixels
        return _PixelSizes(X=p.pixel_size_x_um, Y=p.pixel_size_y_um, Z=p.pixel_size_z_um)

    @property
    def channel_names(self) -> list[str]:
        return ["C:0"]

    @property
    def metadata(self) -> str:
        return self._xml

    def close(self) -> None:
        pass
