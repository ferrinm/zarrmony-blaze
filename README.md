# zarrmony-blaze

Miltenyi UltraMicroscope Blaze (MACS iQ-processed) reader plugin for
[zarrmony](https://github.com/ferrinm/zarrmony).

> **Status: pre-alpha.** v0.1 design is documented in
> [`docs/v0.1-design.md`](./docs/v0.1-design.md); implementation is tracked in
> the issue list. Not yet on PyPI.

## What it will do

Wraps the per-`(channel, Z-plane)` OME-TIFF directory produced by the
MACS iQ View processing pipeline so that
`zarrmony convert /path/to/<blaze-experiment-dir>` Just Works.

## Why a separate plugin

Vanilla zarrmony routes `.ome.tif` to `bioio-ome-tiff`, which fails on
real MACS iQ exports because `ome-types` strictly rejects the old OME
schema after a 2008→2016 upgrade. This plugin reads the OME-XML with
stdlib `xml.etree` and builds the dask graph from `<TiffData>`
references directly, sidestepping both issues. See
[ADR-0001](./docs/adr/0001-tifffile-over-bioio-ome-tiff.md).

## Domain context

See [`CONTEXT.md`](./CONTEXT.md) for the glossary (Blaze experiment, raw
vs processed export, multi-file OME master file).

## License

Apache-2.0. See [LICENSE](./LICENSE).
