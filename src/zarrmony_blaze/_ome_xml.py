"""Parse a MACS iQ Blaze master OME-XML string into a typed view.

Pure stdlib (``xml.etree.ElementTree``); no file I/O. The whole point of this
module is to be unit-testable against fixture XML strings without touching
disk.

Why stdlib instead of ``ome-types``: see ADR-0001. Real MACS iQ exports use
the **2008-02** OME schema, and ``ome-types`` strict-upgrades them to 2016-06
and dies on placement of ``<AnnotationRef>``. We only extract the fields the
adapter needs (``<Pixels>``, ``<Channel>``, ``<TiffData>``); the rest of the
XML is preserved verbatim via ``BlazeReader.metadata`` for the audit's
``OME/source/raw.ome.xml``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np

OME_NS_2008_02 = "http://www.openmicroscopy.org/Schemas/OME/2008-02"

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


class BlazeMetadataError(Exception):
    """Master OME-XML is malformed, uses an unsupported schema, or self-inconsistent."""


class BlazeMultipositionUnsupportedError(NotImplementedError):
    """Master OME-XML describes more than one ``<Image>`` (multiposition export).

    v0.1 emits one scene per directory and is not equipped to split a single
    master across multiple positions. Subclass of :class:`NotImplementedError`
    so generic ``except NotImplementedError`` handlers see it as a "feature
    not yet built" rather than a corrupt-data signal.
    """


@dataclass(frozen=True)
class BlazeOme:
    size_t: int
    size_c: int
    size_z: int
    size_y: int
    size_x: int
    dtype: np.dtype
    pixel_size_x_um: float | None
    pixel_size_y_um: float | None
    pixel_size_z_um: float | None
    channel_names: list[str]
    file_map: dict[tuple[int, int, int], str]


def _q(name: str) -> str:
    return f"{{{OME_NS_2008_02}}}{name}"


def _root_ns(root: ET.Element) -> str:
    tag = root.tag
    if tag.startswith("{"):
        return tag[1 : tag.index("}")]
    return ""


def parse_master_xml(xml: str) -> BlazeOme:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise BlazeMetadataError(f"failed to parse OME-XML: {e}") from e

    ns = _root_ns(root)
    if ns != OME_NS_2008_02:
        raise BlazeMetadataError(
            f"unsupported OME schema {ns!r}; zarrmony-blaze only handles "
            f"{OME_NS_2008_02!r} (2008-02). If MACS iQ has upgraded its export "
            "schema, _ome_xml.py needs an update."
        )

    images = root.findall(_q("Image"))
    if len(images) > 1:
        raise BlazeMultipositionUnsupportedError(
            f"master OME-XML contains {len(images)} <Image> elements — this is a "
            "multiposition export, which zarrmony-blaze v0.1 does not support. "
            "Workaround: convert one position at a time (split the export into "
            "single-position directories before running `zarrmony convert`). "
            "Raw multiposition reads are tracked for v0.2: "
            "https://github.com/ferrinm/zarrmony-blaze/issues/5"
        )
    if not images:
        raise BlazeMetadataError("master OME-XML has no <Image> element")
    image = images[0]
    pixels = image.find(_q("Pixels"))
    if pixels is None:
        raise BlazeMetadataError("<Image> has no <Pixels> element")

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

    # OME 2008-02 (real MACS iQ) puts channels as <LogicalChannel> directly
    # under <Image>; <Channel> under <Pixels> is a 2011-06+ convention. Try
    # the newer placement first (matches synthesised fixtures), fall back to
    # the legacy one.
    channel_elements = pixels.findall(_q("Channel")) or image.findall(_q("LogicalChannel"))
    channel_names: list[str] = []
    for idx, ch in enumerate(channel_elements):
        name = (
            ch.attrib.get("Name")
            or ch.attrib.get("Fluor")
            or ch.attrib.get("ID")
            or f"Channel:{idx}"
        )
        channel_names.append(name)
    if len(channel_names) != size_c:
        raise BlazeMetadataError(
            f"channel element count ({len(channel_names)}) does not match SizeC ({size_c}) — "
            f"looked under <Pixels>/<Channel> and <Image>/<LogicalChannel>"
        )

    file_map: dict[tuple[int, int, int], str] = {}
    for td in pixels.findall(_q("TiffData")):
        t = int(td.attrib.get("FirstT", "0"))
        c = int(td.attrib.get("FirstC", "0"))
        z = int(td.attrib.get("FirstZ", "0"))
        uuid_el = td.find(_q("UUID"))
        if uuid_el is None or "FileName" not in uuid_el.attrib:
            raise BlazeMetadataError(
                f"<TiffData FirstT={t} FirstC={c} FirstZ={z}> missing <UUID FileName=...>"
            )
        key = (t, c, z)
        if key in file_map:
            raise BlazeMetadataError(f"duplicate <TiffData> for (t={t}, c={c}, z={z})")
        if not (0 <= t < size_t and 0 <= c < size_c and 0 <= z < size_z):
            raise BlazeMetadataError(
                f"<TiffData> key (t={t}, c={c}, z={z}) out of range for "
                f"SizeT={size_t}, SizeC={size_c}, SizeZ={size_z}"
            )
        file_map[key] = uuid_el.attrib["FileName"]

    expected = size_t * size_c * size_z
    if len(file_map) != expected:
        raise BlazeMetadataError(
            f"<TiffData> count ({len(file_map)}) != SizeT*SizeC*SizeZ ({expected})"
        )

    return BlazeOme(
        size_t=size_t,
        size_c=size_c,
        size_z=size_z,
        size_y=size_y,
        size_x=size_x,
        dtype=dtype,
        pixel_size_x_um=_maybe_float("PhysicalSizeX"),
        pixel_size_y_um=_maybe_float("PhysicalSizeY"),
        pixel_size_z_um=_maybe_float("PhysicalSizeZ"),
        channel_names=channel_names,
        file_map=file_map,
    )
