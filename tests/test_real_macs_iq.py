"""End-to-end conversion against a real MACS iQ-processed Blaze subset.

Skipped when ``tests/fixtures/macs_iq_subset/`` is empty. See
``tests/fixtures/README.md`` for how to regenerate the subset from a real
export on the NAS.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import zarr

from zarrmony_blaze import BlazeReader

from .test_adapter import _convert_with_plugin

FIXTURE = Path(__file__).parent / "fixtures" / "macs_iq_subset"


def _has_real_fixture() -> bool:
    if not FIXTURE.is_dir():
        return False
    masters = list(FIXTURE.glob("*_Z0000.ome.tif"))
    return bool(masters)


pytestmark = pytest.mark.skipif(
    not _has_real_fixture(),
    reason="tests/fixtures/macs_iq_subset/ not populated — see fixtures/README.md",
)


def test_real_macs_iq_end_to_end_convert(tmp_path: Path) -> None:
    """A real MACS iQ subset converts to a valid OME-Zarr store."""
    reader = BlazeReader(FIXTURE)
    expected_channels = reader.channel_names
    px = reader.physical_pixel_sizes

    out_dir = tmp_path / "out"
    _convert_with_plugin(FIXTURE, out_dir)

    stores = sorted(out_dir.glob("*.ome.zarr"))
    assert len(stores) == 1, f"expected one .ome.zarr, got {[s.name for s in stores]}"
    store = stores[0]

    grp = zarr.open_group(str(store), mode="r")
    arr = grp["0"]
    t_size, c_size, *_ = arr.shape
    assert t_size == 1
    assert c_size == len(expected_channels)
    assert str(arr.dtype) == "uint16"

    ome_attrs = grp.attrs["ome"]
    channel_labels = [ch["label"] for ch in ome_attrs["omero"]["channels"]]
    assert channel_labels == expected_channels

    if px.X is not None:
        scale = ome_attrs["multiscales"][0]["datasets"][0]["coordinateTransformations"][0]["scale"]
        assert scale[3] == pytest.approx(px.Y)
        assert scale[4] == pytest.approx(px.X)
