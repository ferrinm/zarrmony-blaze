# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-06-22

### Changed

- README cleanup now that the package is live on PyPI: removed the "not yet
  on PyPI" caveat and the `git+https://...` install fallback. No code
  changes; this release exists solely to exercise the new
  Trusted-Publishing workflow end-to-end.

## [0.1.0] — 2026-06-22

### Added

- Initial release. `BlazeReader` adapter satisfies zarrmony's `ReaderProtocol`
  and registers as `zarrmony-blaze` via the `zarrmony.readers` entry point.
- **Directory matcher** that fires on the presence of a `_Blaze_..._Z0000.ome.tif`
  master file. Matches the directory, not a single file, so users do not need to
  know which internal file carries the OME-XML.
- **OME-XML parser** (`_ome_xml.py`) built on stdlib `xml.etree.ElementTree`.
  Sidesteps the 2008→2016 schema upgrade in `ome-types` that breaks
  `bioio-ome-tiff` on real MACS iQ exports (see
  [ADR-0001](docs/adr/0001-tifffile-over-bioio-ome-tiff.md)). Reads `<Pixels>`,
  `<Channel>` (with `Name` → `Fluor` → `ID` fallback), `<TiffData>` UUID
  references, and supports both `<Channel>`-under-`<Pixels>` and
  `<LogicalChannel>`-under-`<Image>` placements.
- **Multi-file dask graph.** One chunk per `(t, c, z)` plane, each backed by a
  lazy `tifffile.imread(<companion>)` call. Avoids `tifffile.TiffFile.series`,
  which eagerly stats ~8k companion files at construction time and is
  unusable over network mounts.
- **Multiposition guardrail.** Multi-`<Image>` masters raise
  `BlazeMultipositionUnsupportedError` (a `NotImplementedError` subclass) with
  a workaround pointing at single-position-at-a-time conversion and the v0.2
  raw-mode tracker.
- **Metadata sanity check.** Asserts
  `len(file_map) == size_t * size_c * size_z` after parsing and raises
  `BlazeMetadataError` with the expected-vs-found counts on mismatch.
- **Audit propagation.** The verbatim master XML is exposed via
  `BlazeReader.metadata` so `zarrmony.convert` writes it to
  `OME/source/raw.ome.xml`; the reader's `name`, `distribution`, and
  `source = "entry_point"` flow into the audit record.
- **Real MACS iQ integration fixture.** A spatially-cropped, Z-windowed
  subset committed under `tests/fixtures/macs_iq_subset/` exercises the
  full pipeline against vendor-emitted OME-XML. Regeneration is documented
  in `tests/fixtures/README.md`.

### Known limitations

- One scene per directory; multiposition exports raise `NotImplementedError`.
- No raw-tile support (tracked for v0.2).
- No stitching.
- `<AnnotationRef>` parsing not implemented — full XML is preserved verbatim
  in the audit.