"""Unit tests for `_ome_xml.parse_master_xml`.

Three XML inputs:
1. A real-shaped MACS iQ master with the bulk of `<TiffData>` trimmed (still
   covers SizeC * SizeZ entries so post-parse validation passes).
2. A minimal synthesised master — barely enough for the parser to succeed.
3. Malformed XML, asserts the typed error.
"""

from __future__ import annotations

import numpy as np
import pytest

from zarrmony_blaze._ome_xml import (
    BlazeMetadataError,
    BlazeMultipositionUnsupportedError,
    parse_master_xml,
)

# 2 channels x 2 Z; matches CONTEXT.md note about DimensionOrder XYZCT.
_MACS_IQ_LIKE = """<?xml version="1.0" encoding="UTF-8"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     UUID="urn:uuid:11111111-1111-1111-1111-111111111111">
  <Image ID="Image:0" Name="sample">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="2048" SizeY="2048" SizeZ="2" SizeC="2" SizeT="1"
            PhysicalSizeX="0.65" PhysicalSizeY="0.65" PhysicalSizeZ="5.0">
      <Channel ID="Channel:0" Name="Ch1_488" Fluor="GFP" SamplesPerPixel="1"/>
      <Channel ID="Channel:1" Name="Ch2_561" Fluor="mCherry" SamplesPerPixel="1"/>
      <TiffData FirstT="0" FirstC="0" FirstZ="0" IFD="0" PlaneCount="1">
        <UUID FileName="sample_Blaze_C00_Z0000.ome.tif">urn:uuid:a0</UUID>
      </TiffData>
      <TiffData FirstT="0" FirstC="0" FirstZ="1" IFD="0" PlaneCount="1">
        <UUID FileName="sample_Blaze_C00_Z0001.ome.tif">urn:uuid:a1</UUID>
      </TiffData>
      <TiffData FirstT="0" FirstC="1" FirstZ="0" IFD="0" PlaneCount="1">
        <UUID FileName="sample_Blaze_C01_Z0000.ome.tif">urn:uuid:b0</UUID>
      </TiffData>
      <TiffData FirstT="0" FirstC="1" FirstZ="1" IFD="0" PlaneCount="1">
        <UUID FileName="sample_Blaze_C01_Z0001.ome.tif">urn:uuid:b1</UUID>
      </TiffData>
    </Pixels>
  </Image>
</OME>"""

# Minimal: 1×1×1, only the attributes the parser strictly needs.
_MINIMAL = """<?xml version="1.0"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint8"
            SizeX="1" SizeY="1" SizeZ="1" SizeC="1" SizeT="1">
      <Channel ID="Channel:0"/>
      <TiffData>
        <UUID FileName="only.ome.tif">urn:uuid:0</UUID>
      </TiffData>
    </Pixels>
  </Image>
</OME>"""


def test_parses_macs_iq_like_master() -> None:
    ome = parse_master_xml(_MACS_IQ_LIKE)
    assert (ome.size_t, ome.size_c, ome.size_z) == (1, 2, 2)
    assert (ome.size_y, ome.size_x) == (2048, 2048)
    assert ome.dtype == np.dtype("uint16")
    assert ome.pixel_size_x_um == pytest.approx(0.65)
    assert ome.pixel_size_y_um == pytest.approx(0.65)
    assert ome.pixel_size_z_um == pytest.approx(5.0)
    assert ome.channel_names == ["Ch1_488", "Ch2_561"]
    # Spot-check a couple file_map entries.
    assert ome.file_map[(0, 0, 0)] == "sample_Blaze_C00_Z0000.ome.tif"
    assert ome.file_map[(0, 1, 1)] == "sample_Blaze_C01_Z0001.ome.tif"
    assert len(ome.file_map) == 4


def test_channel_name_fallback_to_fluor_then_id() -> None:
    xml = _MACS_IQ_LIKE.replace(
        '<Channel ID="Channel:0" Name="Ch1_488" Fluor="GFP" SamplesPerPixel="1"/>',
        '<Channel ID="Channel:0" Fluor="GFP" SamplesPerPixel="1"/>',
    ).replace(
        '<Channel ID="Channel:1" Name="Ch2_561" Fluor="mCherry" SamplesPerPixel="1"/>',
        '<Channel ID="Channel:1" SamplesPerPixel="1"/>',
    )
    ome = parse_master_xml(xml)
    assert ome.channel_names == ["GFP", "Channel:1"]


_CHANNEL_FALLBACK_TIERS = """<?xml version="1.0" encoding="UTF-8"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="1" SizeY="1" SizeZ="1" SizeC="3" SizeT="1">
      <Channel ID="Channel:0" Name="DAPI_405" Fluor="DAPI" SamplesPerPixel="1"/>
      <Channel ID="Channel:1" Fluor="GFP" SamplesPerPixel="1"/>
      <Channel ID="Channel:2" SamplesPerPixel="1"/>
      <TiffData FirstC="0">
        <UUID FileName="c0.ome.tif">urn:uuid:0</UUID>
      </TiffData>
      <TiffData FirstC="1">
        <UUID FileName="c1.ome.tif">urn:uuid:1</UUID>
      </TiffData>
      <TiffData FirstC="2">
        <UUID FileName="c2.ome.tif">urn:uuid:2</UUID>
      </TiffData>
    </Pixels>
  </Image>
</OME>"""


def test_channel_name_fallback_chain_all_three_tiers() -> None:
    """Name wins when present; Fluor next; ID last."""
    ome = parse_master_xml(_CHANNEL_FALLBACK_TIERS)
    assert ome.channel_names == ["DAPI_405", "GFP", "Channel:2"]


# Real MACS iQ uses true OME 2008-02: <LogicalChannel> under <Image>,
# not <Channel> under <Pixels>. The vendor-observed shape — drives the
# parser's fallback that <Channel> tests don't exercise.
_LOGICAL_CHANNEL_LEGACY = """<?xml version="1.0" encoding="UTF-8"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0" Name="legacy">
    <LogicalChannel ID="LogicalChannel:0" Name="Ex: 785nm Em: 845nm"
                    EmWave="845" ExWave="785"/>
    <LogicalChannel ID="LogicalChannel:1" Name="Ex: 488nm Em: 525nm"
                    EmWave="525" ExWave="488"/>
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" PixelType="uint16"
            SizeX="1" SizeY="1" SizeZ="1" SizeC="2" SizeT="1">
      <TiffData FirstC="0"><UUID FileName="c0.ome.tif">u0</UUID></TiffData>
      <TiffData FirstC="1"><UUID FileName="c1.ome.tif">u1</UUID></TiffData>
    </Pixels>
  </Image>
</OME>"""


def test_logical_channel_under_image_legacy_2008_02_placement() -> None:
    """Real MACS iQ exports use <Image>/<LogicalChannel>; parser must fall back."""
    ome = parse_master_xml(_LOGICAL_CHANNEL_LEGACY)
    assert ome.channel_names == ["Ex: 785nm Em: 845nm", "Ex: 488nm Em: 525nm"]
    assert ome.dtype == np.dtype("uint16")


_MULTIPOSITION = """<?xml version="1.0" encoding="UTF-8"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="1" SizeY="1" SizeZ="1" SizeC="1" SizeT="1">
      <Channel ID="Channel:0"/>
      <TiffData>
        <UUID FileName="pos0.ome.tif">urn:uuid:p0</UUID>
      </TiffData>
    </Pixels>
  </Image>
  <Image ID="Image:1">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="1" SizeY="1" SizeZ="1" SizeC="1" SizeT="1">
      <Channel ID="Channel:0"/>
      <TiffData>
        <UUID FileName="pos1.ome.tif">urn:uuid:p1</UUID>
      </TiffData>
    </Pixels>
  </Image>
</OME>"""


def test_multiposition_master_raises_unsupported() -> None:
    """Multi-<Image> master → typed NotImplementedError with workaround text."""
    with pytest.raises(BlazeMultipositionUnsupportedError) as excinfo:
        parse_master_xml(_MULTIPOSITION)
    # Subclass of NotImplementedError so generic handlers see it as "not built yet".
    assert isinstance(excinfo.value, NotImplementedError)
    msg = str(excinfo.value)
    assert "convert one position at a time" in msg
    assert "v0.2" in msg
    # v0.2 raw-mode tracker link.
    assert "issues/5" in msg


def test_parses_minimal_master() -> None:
    ome = parse_master_xml(_MINIMAL)
    assert ome.size_t == ome.size_c == ome.size_z == 1
    assert ome.dtype == np.dtype("uint8")
    # Channel had only ID, so the fallback chain lands on ID.
    assert ome.channel_names == ["Channel:0"]
    # No PhysicalSize* attrs at all.
    assert ome.pixel_size_x_um is None
    assert ome.pixel_size_y_um is None
    assert ome.pixel_size_z_um is None
    assert ome.file_map == {(0, 0, 0): "only.ome.tif"}


def test_malformed_xml_raises() -> None:
    with pytest.raises(BlazeMetadataError, match="failed to parse"):
        parse_master_xml("<OME this is not<<< well-formed >>>")


def test_unsupported_schema_raises() -> None:
    xml = _MINIMAL.replace("2008-02", "2016-06")
    with pytest.raises(BlazeMetadataError, match="unsupported OME schema"):
        parse_master_xml(xml)


def test_missing_pixels_raises() -> None:
    xml = """<?xml version="1.0"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0"/>
</OME>"""
    with pytest.raises(BlazeMetadataError, match="no <Pixels>"):
        parse_master_xml(xml)


def test_tiffdata_count_mismatch_raises() -> None:
    # SizeZ=2 but only one TiffData supplied.
    xml = """<?xml version="1.0"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="1" SizeY="1" SizeZ="2" SizeC="1" SizeT="1">
      <Channel ID="Channel:0"/>
      <TiffData>
        <UUID FileName="only.ome.tif">urn:uuid:0</UUID>
      </TiffData>
    </Pixels>
  </Image>
</OME>"""
    with pytest.raises(BlazeMetadataError, match="!= SizeT\\*SizeC\\*SizeZ"):
        parse_master_xml(xml)


def test_tiffdata_out_of_range_raises() -> None:
    xml = """<?xml version="1.0"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="1" SizeY="1" SizeZ="1" SizeC="1" SizeT="1">
      <Channel ID="Channel:0"/>
      <TiffData FirstZ="5">
        <UUID FileName="oob.ome.tif">urn:uuid:0</UUID>
      </TiffData>
    </Pixels>
  </Image>
</OME>"""
    with pytest.raises(BlazeMetadataError, match="out of range"):
        parse_master_xml(xml)
