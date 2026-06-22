# zarrmony-blaze

Miltenyi UltraMicroscope Blaze (MACS iQ-processed) reader plugin for
[zarrmony](https://github.com/ferrinm/zarrmony). Detects a processed Blaze
export directory and converts it to OME-NGFF 0.5 in one shot:

```bash
zarrmony convert /path/to/<blaze-experiment-dir> ./out
```

## Install

```bash
pip install zarrmony-blaze
```

This pulls `zarrmony` from PyPI as a transitive dependency. Not yet on PyPI as
of this writing — install from source until v0.1.0 is published:

```bash
pip install git+https://github.com/ferrinm/zarrmony-blaze
```

## Verify the plugin registered

```python
from zarrmony.readers.plugin import list_plugins
print([p.name for p in list_plugins()])
# -> [..., 'zarrmony-blaze']
```

For a clean-venv install smoke test (the same shape CI runs):

```bash
uv venv .venv-smoke
source .venv-smoke/bin/activate
uv pip install .
python -c "from zarrmony.readers.plugin import list_plugins; \
           assert 'zarrmony-blaze' in {p.name for p in list_plugins()}"
```

The same assertion runs in CI as `tests/test_install_smoke.py`.

## Use

```bash
zarrmony inspect /path/to/BlazeExperiment    # dims, channels, pixel sizes
zarrmony convert /path/to/BlazeExperiment ./out
```

Output is a single `<dir-basename>.ome.zarr` store with dims `(T, C, Z, Y, X)`,
one chunk per `(t, c, z)` plane, channel names taken from the vendor's
`<Channel Name="...">` (falling back to `Fluor` → `ID` if `Name` is missing),
and physical pixel sizes copied verbatim from `<Pixels PhysicalSizeX/Y/Z>`.

The full master OME-XML is preserved in the audit at
`<store>/OME/source/raw.ome.xml`.

## Supported Blaze exports

- **MACS iQ-processed directories.** The vendor-stitched output written as one
  OME-TIFF per `(channel, Z-plane)`, named
  `<prefix>_Blaze_C<NN>_Z<NNNN>.ome.tif`. The plugin reads the C0 master
  (`_C00_Z0000.ome.tif`) for OME-XML and assembles the rest from
  `<TiffData>` UUID references.

Detection requires both the `_Blaze_` vendor token in the filename **and** at
least one `_Z0000.ome.tif` master in the directory.

Raw (unstitched) ImSpector output is **not** handled in v0.1; see Limitations.

## Limitations

- **Multiposition exports are not supported.** A master with more than one
  `<Image>` element raises `BlazeMultipositionUnsupportedError`
  (a `NotImplementedError`). Workaround: convert one position at a time;
  full multiposition support is tracked for v0.2 alongside raw-mode.
- **No raw-tile support.** Raw, unstitched ImSpector output
  (`measurementInfo.txt` + `tiles.txt`, one TIFF per `(tile, channel)`) is
  out of scope for v0.1. v0.2 will add a separate matcher that emits one
  scene per tile with stage XY on `attrs.zarrmony.tile.*`; stitching is
  delegated to BigStitcher / ASHLAR / m2stitch / TeraStitcher.
- **No stitching.** The plugin assembles already-stitched per-plane files
  into one TCZYX volume; it does not stitch tiles.
- **`<AnnotationRef>` parsing not implemented.** Only the fields needed for
  conversion (channels, pixel sizes, file map) are extracted from the XML.
  The full XML is preserved verbatim in the audit.

## Why a separate package?

Vanilla zarrmony routes `.ome.tif` to `bioio-ome-tiff`, which fails on real
MACS iQ exports because `ome-types` strictly rejects the old OME schema after
a 2008→2016 upgrade. This plugin reads the OME-XML with stdlib `xml.etree`
and builds the dask graph from `<TiffData>` references directly, sidestepping
both that and the eager-stat-all-companions behaviour of
`tifffile.TiffFile.series`. See
[ADR-0001](docs/adr/0001-tifffile-over-bioio-ome-tiff.md) for the full
rationale and the
[reader-plugin authoring guide](https://github.com/ferrinm/zarrmony/blob/main/docs/writing-a-reader-plugin.md)
for how to build your own plugin.

## Domain context

See [`CONTEXT.md`](CONTEXT.md) for the glossary (Blaze experiment, raw vs
processed export, multi-file OME master file) and
[`docs/v0.1-design.md`](docs/v0.1-design.md) for the v0.1 implementation plan.

## License

Apache-2.0. See [LICENSE](LICENSE).