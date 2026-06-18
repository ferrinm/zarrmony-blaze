from pathlib import Path

import numpy as np
import pytest
import zarr
from zarrmony.readers.plugin import ReaderProtocol

from zarrmony_blaze import BlazeReader, plugin

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
