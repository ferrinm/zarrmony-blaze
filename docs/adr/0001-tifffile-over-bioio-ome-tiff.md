# ADR-0001: Read MACS iQ output with `tifffile` + stdlib XML, not `bioio-ome-tiff`

Date: 2026-06-17
Status: Accepted

## Context

MACS iQ View writes processed Blaze exports as a standard OME-TIFF multi-file
series: one master file per channel carrying the OME-XML, ~8k `BinaryOnly`
companion files referenced by UUID. Reading this is what `bioio-ome-tiff`
exists for. Every other zarrmony reader plugin either is a thin wrapper around
a bioio sub-package or delegates to `BioImage` outright. The default path of
least resistance is to do the same here.

We tested it. **It fails.**

On a real export, `bioio_ome_tiff.Reader(<master>)` raises
`UnsupportedFileFormatError`, root cause:

```
ParserError: Unknown property
    {http://www.openmicroscopy.org/Schemas/OME/2016-06}OME:
    {http://www.openmicroscopy.org/Schemas/OME/2016-06}AnnotationRef
```

`ome-types` (bioio-ome-tiff's XML parser) upgrades the file's 2008-02 schema
to 2016-06, then runs the parser in strict `fail_on_unknown_properties=True`
mode. The upgraded XML places `<AnnotationRef>` where the strict 2016 schema
doesn't accept it, and parsing dies.

We also tested falling back to `tifffile.TiffFile.series` (which has its own
permissive OME parser and doesn't go through `ome-types`). It works, but
`series` eagerly stats all ~8k referenced companion files at construction
time. On a remote-mounted drive this takes minutes per `open()`, making it
unusable for `inspect()` and any latency-sensitive workflow.

## Decision

Parse the master's OME-XML with stdlib `xml.etree.ElementTree`. Build the
`(t, c, z) → filename` map ourselves. Use `tifffile.imread(<single_file>)` per
dask chunk for the actual pixel reads. Do not depend on `bioio-ome-tiff` or
`ome-types`.

## Consequences

### Positive

- The plugin reads real MACS iQ output. The bioio path doesn't.
- `open()` is essentially free — one master file is read for its
  `ImageDescription` tag, ~1.5 MB of XML is parsed in stdlib, done. No
  per-companion stat calls.
- No transitive dependency on `ome-types` or its strict-schema baggage.
- We only extract the fields we use (Pixels, Channel, TiffData). The full XML
  is preserved verbatim in the converted store's
  `OME/source/raw.ome.xml` for downstream consumers that want more.

### Negative

- We own the XML parser. If MACS iQ changes the OME-XML structure in a future
  version, we have to update our parser rather than getting it for free from
  bioio.
- We don't validate the XML against a schema. A malformed export could parse
  successfully and produce subtly wrong output. Mitigation: post-parse
  validation (count of TiffData entries matches SizeT × SizeC × SizeZ; all
  channel indices in range; no duplicate (t, c, z) keys).
- The `<AnnotationRef>` content is silently ignored. We don't currently surface
  any annotations into the converted store's metadata. If we ever need them,
  we extend `_ome_xml.py`, not the read path.

### Reversibility

- **Low cost to revisit upstream.** If `ome-types` (or `bioio-ome-tiff`) ships
  a permissive mode that accepts these exports, we can switch by changing
  `_ome_xml.py` to delegate. The Reader Protocol surface doesn't change.
- **Bug filed upstream** is the right long-term move: the 2008→2016 upgrade
  should either produce strict-valid XML or the strict mode should be opt-in.

## Considered alternatives

| Alternative | Why rejected |
| --- | --- |
| Use `bioio-ome-tiff` directly | Fails on real exports, see Context. |
| `tifffile.TiffFile.series` then wrap | Eager file-stat at construction is unacceptable over network mounts. |
| Pre-clean XML before handing to `ome-types` | We can't modify the file; bioio reads the XML internally. Monkey-patching is fragile. |
| Wait for upstream fix in `bioio-ome-tiff` | Indefinite timeline. We need to ship now; the parser is small. |

## References

- Verified failure: `UnsupportedFileFormatError` on real export, 2026-06-17.
- `tifffile.TiffFile.series` slowness: verified by hanging Part 1 of the
  verification script, 2026-06-17.
- Working path proof: `xml.etree` parse + `tifffile.imread` per single
  companion, sub-second on the same data over the same mount, 2026-06-17.
