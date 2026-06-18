import json
from pathlib import Path

import numpy as np
import pytest
import tifffile
import zarr
from zarrmony.readers.plugin import ReaderProtocol

from zarrmony_blaze import BlazeReader, plugin
from zarrmony_blaze.adapter import (
    BlazeMetadataError,
    BlazeMultipositionUnsupportedError,
)

from .conftest import MultiFileFixture


def test_adapter_satisfies_reader_protocol(synthetic_blaze_dir: Path) -> None:
    r = BlazeReader(synthetic_blaze_dir)
    assert isinstance(r, ReaderProtocol)


def test_layout_hint_is_flat(synthetic_blaze_dir: Path) -> None:
    r = BlazeReader(synthetic_blaze_dir)
    assert r.layout_hint == "flat"
    assert r.plate_layout is None


def test_scene_is_directory_basename(synthetic_blaze_dir: Path) -> None:
    r = BlazeReader(synthetic_blaze_dir)
    assert r.scenes == [synthetic_blaze_dir.name]


def test_xarray_dims_dtype_shape(synthetic_blaze_dir: Path) -> None:
    r = BlazeReader(synthetic_blaze_dir)
    r.set_scene(0)
    xarr = r.xarray_dask_data
    assert xarr.dims == ("T", "C", "Z", "Y", "X")
    assert xarr.shape == (1, 1, 1, 4, 4)
    assert xarr.dtype == "uint16"
    assert list(xarr.coords["C"].values) == ["C:0"]


def test_physical_pixel_sizes_in_microns(synthetic_blaze_dir: Path) -> None:
    r = BlazeReader(synthetic_blaze_dir)
    px = r.physical_pixel_sizes
    assert px.X == pytest.approx(1.5)
    assert px.Y == pytest.approx(1.5)
    assert px.Z == pytest.approx(5.0)


def test_channel_names_default(synthetic_blaze_dir: Path) -> None:
    r = BlazeReader(synthetic_blaze_dir)
    assert r.channel_names == ["C:0"]


def test_metadata_returns_raw_xml(synthetic_blaze_dir: Path) -> None:
    r = BlazeReader(synthetic_blaze_dir)
    raw = r.metadata
    assert "<OME" in raw
    assert "Pixels" in raw


def _convert_with_plugin(src: Path, out: Path) -> None:
    """Run ``zarrmony.convert`` against this plugin without touching real entry points."""
    from zarrmony.api import convert
    from zarrmony.readers import plugin as plugin_mod

    snap_plugins = dict(plugin_mod._PLUGINS)
    snap_loaded = plugin_mod._ENTRY_POINTS_LOADED
    plugin_mod._PLUGINS.clear()
    plugin_mod._ENTRY_POINTS_LOADED = True
    try:
        plugin_mod.register_plugin(plugin)
        convert(str(src), str(out), permissive=True)
    finally:
        plugin_mod._PLUGINS.clear()
        plugin_mod._PLUGINS.update(snap_plugins)
        plugin_mod._ENTRY_POINTS_LOADED = snap_loaded


def test_end_to_end_convert_produces_ome_zarr(synthetic_blaze_dir: Path, tmp_path: Path) -> None:
    """Synthesised fixture → ``zarrmony.convert`` → valid OME-Zarr 0.5 store."""
    out_dir = tmp_path / "out"
    _convert_with_plugin(synthetic_blaze_dir, out_dir)

    stores = sorted(out_dir.glob("*.ome.zarr"))
    assert len(stores) == 1, f"expected one .ome.zarr, got {[s.name for s in stores]}"
    store = stores[0]
    grp = zarr.open_group(str(store), mode="r")
    # OME-Zarr v0.5 multiscales puts pixel data at "0" (full-res level).
    arr = grp["0"]
    assert arr.shape == (1, 1, 1, 4, 4)
    assert str(arr.dtype) == "uint16"


def test_multi_file_reader_reflects_xml(synthetic_blaze_multi: MultiFileFixture) -> None:
    """Adapter reads dims, channel names, and pixel sizes from the master XML."""
    r = BlazeReader(synthetic_blaze_multi.dir)
    assert r.scenes == [synthetic_blaze_multi.dir.name]
    assert r.channel_names == list(synthetic_blaze_multi.channel_names)
    px = r.physical_pixel_sizes
    assert px.X == pytest.approx(synthetic_blaze_multi.pixel_size_um)
    assert px.Y == pytest.approx(synthetic_blaze_multi.pixel_size_um)
    assert px.Z == pytest.approx(synthetic_blaze_multi.z_step_um)

    xarr = r.xarray_dask_data
    assert xarr.dims == ("T", "C", "Z", "Y", "X")
    assert xarr.shape == (
        1,
        len(synthetic_blaze_multi.channel_names),
        synthetic_blaze_multi.size_z,
        synthetic_blaze_multi.size_y,
        synthetic_blaze_multi.size_x,
    )
    assert xarr.dtype == "uint16"
    assert list(xarr.coords["C"].values) == list(synthetic_blaze_multi.channel_names)


def test_multi_file_chunks_return_per_plane_constants(
    synthetic_blaze_multi: MultiFileFixture,
) -> None:
    """Each (c, z) chunk should read back the constant the fixture wrote."""
    r = BlazeReader(synthetic_blaze_multi.dir)
    arr = r.xarray_dask_data.data  # underlying dask array
    for c in range(len(synthetic_blaze_multi.channel_names)):
        for z in range(synthetic_blaze_multi.size_z):
            plane = np.asarray(arr[0, c, z])
            expected = synthetic_blaze_multi.value_for(c, z)
            assert plane.shape == (synthetic_blaze_multi.size_y, synthetic_blaze_multi.size_x)
            assert plane.dtype == np.uint16
            assert int(plane.min()) == expected
            assert int(plane.max()) == expected


def test_multi_file_end_to_end_convert(
    synthetic_blaze_multi: MultiFileFixture, tmp_path: Path
) -> None:
    """Full conversion: 2C × 5Z fixture → OME-Zarr store with the right pixels."""
    out_dir = tmp_path / "out"
    _convert_with_plugin(synthetic_blaze_multi.dir, out_dir)

    stores = sorted(out_dir.glob("*.ome.zarr"))
    assert len(stores) == 1, f"expected one .ome.zarr, got {[s.name for s in stores]}"
    store = stores[0]
    grp = zarr.open_group(str(store), mode="r")
    arr = grp["0"]
    assert arr.shape == (
        1,
        len(synthetic_blaze_multi.channel_names),
        synthetic_blaze_multi.size_z,
        synthetic_blaze_multi.size_y,
        synthetic_blaze_multi.size_x,
    )
    assert str(arr.dtype) == "uint16"
    full = arr[...]
    for c in range(len(synthetic_blaze_multi.channel_names)):
        for z in range(synthetic_blaze_multi.size_z):
            plane = full[0, c, z]
            expected = synthetic_blaze_multi.value_for(c, z)
            assert int(plane.min()) == expected
            assert int(plane.max()) == expected

    ome_attrs = grp.attrs["ome"]
    channel_labels = [ch["label"] for ch in ome_attrs["omero"]["channels"]]
    assert channel_labels == list(synthetic_blaze_multi.channel_names)
    # multiscales scale is in TCZYX order; the spatial entries must match the XML.
    scale = ome_attrs["multiscales"][0]["datasets"][0]["coordinateTransformations"][0]["scale"]
    assert scale[2] == pytest.approx(synthetic_blaze_multi.z_step_um)  # Z
    assert scale[3] == pytest.approx(synthetic_blaze_multi.pixel_size_um)  # Y
    assert scale[4] == pytest.approx(synthetic_blaze_multi.pixel_size_um)  # X

    # The master XML should land verbatim in the audit's source dump.
    raw = (store / "OME" / "source" / "raw.xml").read_text()
    assert raw == BlazeReader(synthetic_blaze_multi.dir).metadata


def _write_master_with_xml(dir_path: Path, master_name: str, xml: str) -> None:
    """Write a single 1×1 uint16 TIFF carrying ``xml`` as its OME ImageDescription."""
    dir_path.mkdir(parents=True, exist_ok=True)
    data = np.zeros((1, 1), dtype=np.uint16)
    tifffile.imwrite(dir_path / master_name, data, description=xml, metadata=None)


_MULTIPOSITION_MASTER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="1" SizeY="1" SizeZ="1" SizeC="1" SizeT="1">
      <Channel ID="Channel:0"/>
      <TiffData>
        <UUID FileName="MP_Blaze_C00_Z0000.ome.tif">urn:uuid:p0</UUID>
      </TiffData>
    </Pixels>
  </Image>
  <Image ID="Image:1">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="1" SizeY="1" SizeZ="1" SizeC="1" SizeT="1">
      <Channel ID="Channel:0"/>
      <TiffData>
        <UUID FileName="MP_Blaze_C00_Z0000.ome.tif">urn:uuid:p1</UUID>
      </TiffData>
    </Pixels>
  </Image>
</OME>"""


def test_multiposition_master_raises_from_reader_init(tmp_path: Path) -> None:
    """A multi-<Image> master surfaces as a typed NotImplementedError from __init__."""
    exp = tmp_path / "multipos_experiment"
    _write_master_with_xml(exp, "MP_Blaze_C00_Z0000.ome.tif", _MULTIPOSITION_MASTER_XML)
    with pytest.raises(BlazeMultipositionUnsupportedError) as excinfo:
        BlazeReader(exp)
    assert isinstance(excinfo.value, NotImplementedError)
    assert "convert one position at a time" in str(excinfo.value)


# SizeZ=2 promises 2 planes, but only one <TiffData> entry is supplied.
_FILEMAP_MISMATCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-02">
  <Image ID="Image:0">
    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"
            SizeX="1" SizeY="1" SizeZ="2" SizeC="1" SizeT="1">
      <Channel ID="Channel:0"/>
      <TiffData FirstZ="0">
        <UUID FileName="BAD_Blaze_C00_Z0000.ome.tif">urn:uuid:a</UUID>
      </TiffData>
    </Pixels>
  </Image>
</OME>"""


def test_filemap_size_mismatch_raises_from_reader_init(tmp_path: Path) -> None:
    """A broken master XML (TiffData count ≠ SizeT*SizeC*SizeZ) is caught at init."""
    exp = tmp_path / "broken_experiment"
    _write_master_with_xml(exp, "BAD_Blaze_C00_Z0000.ome.tif", _FILEMAP_MISMATCH_XML)
    with pytest.raises(BlazeMetadataError) as excinfo:
        BlazeReader(exp)
    msg = str(excinfo.value)
    # Message names both the expected count and the count actually found.
    assert "SizeT*SizeC*SizeZ" in msg
    assert "2" in msg  # expected
    assert "1" in msg  # found


def test_audit_record_carries_master_xml_and_provenance(
    synthetic_blaze_multi: MultiFileFixture, tmp_path: Path
) -> None:
    """End-to-end audit propagation: raw XML verbatim + reader provenance fields."""
    out_dir = tmp_path / "out"
    _convert_with_plugin(synthetic_blaze_multi.dir, out_dir)
    store = next(out_dir.glob("*.ome.zarr"))

    # Raw master XML is mirrored verbatim into OME/source/.
    raw = (store / "OME" / "source" / "raw.xml").read_text()
    assert raw == BlazeReader(synthetic_blaze_multi.dir).metadata

    # Audit lives in root.attrs["zarrmony"]; reader_plugin carries provenance.
    grp = zarr.open_group(str(store), mode="r")
    audit = json.loads(json.dumps(dict(grp.attrs)))["zarrmony"]
    reader_block = audit["reader_plugin"]
    assert reader_block["name"] == "zarrmony-blaze"
    assert reader_block["distribution"] == "zarrmony-blaze"
    assert reader_block["source"] == "entry_point"
