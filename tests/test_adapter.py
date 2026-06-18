from pathlib import Path

import pytest
import zarr
from zarrmony.readers.plugin import ReaderProtocol

from zarrmony_blaze import BlazeReader, plugin


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


def test_end_to_end_convert_produces_ome_zarr(synthetic_blaze_dir: Path, tmp_path: Path) -> None:
    """Synthesised fixture → ``zarrmony.convert`` → valid OME-Zarr 0.5 store."""
    from zarrmony.api import convert
    from zarrmony.readers import plugin as plugin_mod

    out_dir = tmp_path / "out"
    snap_plugins = dict(plugin_mod._PLUGINS)
    snap_loaded = plugin_mod._ENTRY_POINTS_LOADED
    plugin_mod._PLUGINS.clear()
    plugin_mod._ENTRY_POINTS_LOADED = True  # skip real entry-point walk
    try:
        plugin_mod.register_plugin(plugin)
        convert(str(synthetic_blaze_dir), str(out_dir), permissive=True)
    finally:
        plugin_mod._PLUGINS.clear()
        plugin_mod._PLUGINS.update(snap_plugins)
        plugin_mod._ENTRY_POINTS_LOADED = snap_loaded

    stores = sorted(out_dir.glob("*.ome.zarr"))
    assert len(stores) == 1, f"expected one .ome.zarr, got {[s.name for s in stores]}"
    store = stores[0]
    grp = zarr.open_group(str(store), mode="r")
    # OME-Zarr v0.5 multiscales puts pixel data at "0" (full-res level).
    arr = grp["0"]
    assert arr.shape == (1, 1, 1, 4, 4)
    assert str(arr.dtype) == "uint16"
