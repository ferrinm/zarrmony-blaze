# Domain glossary

## Scene (v0.1)

Zarrmony's reader protocol requires `scenes: list[str]`. For Blaze processed
exports, v0.1 always exposes **one scene per processed directory** — the
directory's basename — with dims `(T=1, C, Z, Y, X)`. Multiposition exports
are not yet handled; if encountered, the adapter raises `NotImplementedError`
with a message pointing at single-position-at-a-time as the workaround.

Single-context project. Terms here are the ones meaningful to Blaze users and
to the zarrmony plugin author — not implementation details.

## Blaze experiment

A single acquisition run on the UltraMicroscope Blaze, exported by ImSpector as
one or more directories of OME-TIFF files. One Blaze experiment can be produced
in any of the acquisition modes documented in §8.3 of the Blaze manual:

- **Acquisition** — single 2D or 3D image, one position.
- **Multi Color 3D** — multi-channel Z-stack at one position.
- **Mosaic Acquisition / 3D Mosaic** — tiled XY mosaic at one position.
- **Multi Color Mosaic Acquisition** — tiled XY mosaic, multiple channels.
- **Multiposition Acquisition** — multiple discrete XY positions (not tiled).
- **Multi Color Multiposition Acquisition** — as above, multiple channels.

## Raw export

The unstitched, tiled output ImSpector writes during acquisition. One OME-TIFF
file per `(tile-position, channel)` named
`..._Blaze[<row> x <col>]_C<NN>.ome.tif`. Each file contains the full Z-stack
for that tile and channel. Stitching is performed downstream (typically in
ImSpector or a third-party tool like MACS iQ); zarrmony does not stitch.

Out of scope for v0.1. Tracked for v0.2 — until then, "processed only" is the
plugin's promise.

**v0.2 raw-mode contract (decided, not yet built):** the raw reader emits
**one scene per tile** (a `<tile>.ome.zarr` store with `T=1, C, Z, Y, X`),
populating `attrs.zarrmony.tile.{stage_x_um, stage_y_um, row, col}` from
`tiles.txt`. Stitching is explicitly out of scope and is delegated to
downstream tools (BigStitcher, ASHLAR, m2stitch, TeraStitcher). This mirrors
the LIF reader's `MosaicStitchingWarning` precedent — zarrmony preserves
tiles + positions; it does not stitch.

## Processed export

The vendor-stitched output, written as one OME-TIFF file per
`(channel, Z-plane)` named `..._Blaze_C<NN>_Z<NNNN>.ome.tif`. The mosaic has
already been merged; the plugin's job is to assemble these per-plane files into
one TCZYX volume per experiment. This is what v0.1 targets.

The processed dir has no sidecar files and most `.ome.tif` files contain no
OME-XML — BUT the `_Z0000.ome.tif` file of each channel IS a standard OME
multi-file **master**: `is_ome=True`, with ~1.5 MB of OME-XML in its
`ImageDescription` tag (TIFF tag 270, OME schema 2008-02, UUID-referenced).
All other Z-planes are `BinaryOnly` companions referenced from the master via
`<TiffData>` elements.

Practical consequence: channels, pixel sizes, dims, and per-file mappings
all come from the master `_Z0000.ome.tif` — no sibling raw discovery, no
sidecar JSON, no user kwargs needed. The earlier "no OME-XML" finding came
from inspecting a non-master file (Z2094); MACS iQ does follow the OME
multi-file standard, just sparingly.

One master per channel exists (e.g. `_C00_Z0000.ome.tif`,
`_C01_Z0000.ome.tif`, etc.) and each carries the full XML covering all
channels and Z-planes — they are redundant copies, not channel-partial. The
plugin reads one (conventionally C0's) and trusts it for the whole series.

OME-XML quirks observed in a real MACS iQ export: schema is the old
**2008-02** revision (current is 2016-06); `DimensionOrder` is `XYZCT`
(C outer to Z, matching the `_C<NN>_Z<NNNN>_` filename ordering);
`<TiffData>` elements reference companion files by `UUID` rather than by
index.

The strict 2008→2016 schema upgrade in `ome-types` (which `bioio-ome-tiff`
depends on) **fails on these exports** with a `ParserError` on `AnnotationRef`
placement. Plugin therefore reads the XML with stdlib `xml.etree.ElementTree`
(no schema validation, no upgrade) and bypasses `ome-types`. Likewise, it
does not call `tifffile.TiffFile.series` — that property eagerly stats all
~8k referenced companion files at construction time and is unusably slow over
network mounts.

Read path: the plugin parses `<TiffData>` from the master XML to build a
`(c, z) → filename` table, then builds a dask graph where each chunk is
`tifffile.imread(<companion_path>)` returning one `(Y, X)` plane. Channel
names come from `<Channel Name=>`; pixel sizes from `<Pixels PhysicalSizeX/Y/Z>`.

## Sibling raw dir (informational, v0.1)

When a Blaze experiment is processed (typically by MACS iQ), the processed
output lands in a sibling directory next to the raw export. The raw dir
contains two text sidecars worth pulling metadata from in a later milestone:

- **`measurementInfo.txt`** — key-value dump of acquisition parameters:
  objective + NA, clearing solution, per-channel excitation/emission/exposure,
  light-sheet config, xyz-Table step counts, mosaic overlap, camera ROI,
  image sizes. Lossy text format — no schema.
- **`tiles.txt`** — one line per raw tile file:
  `<filename>;;(<stage-X-um>, <stage-Y-um>, <channel-index>)`. First line is
  a header count. Drives raw-mode stitching in v0.2.

Mapping a processed dir to its sibling raw dir is heuristic (the names diverge:
processed = `<sample>/`, raw = `<date>_<sample>_<time>/`). Deferred — became
moot for v0.1 when full OME-XML metadata was discovered embedded in
`_Z0000.ome.tif`. Will be revisited for v0.2 raw-mode.