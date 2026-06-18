# Test fixtures

Most tests build their data on the fly under `tmp_path` from the helpers in
`tests/conftest.py`. The exception is the **real-world MACS iQ subset**, which
has to be derived from an actual processed export and committed because the
source data lives on a network volume that isn't always mounted.

## `macs_iq_subset/`

A spatially-cropped, Z-window subset of a real MACS iQ-processed Blaze
experiment. Exercises `BlazeReader` and `zarrmony.convert` against the OME-XML
the vendor actually emits, on the file-naming convention the vendor actually
uses, without dragging 2.9 TB of pixels into git.

**Layout**

```
tests/fixtures/macs_iq_subset/
├── <prefix>_Blaze_C00_Z0000.ome.tif    # OME multi-file master (carries XML)
├── <prefix>_Blaze_C00_Z0001.ome.tif    # BinaryOnly companion
├── <prefix>_Blaze_C00_Z0002.ome.tif
├── <prefix>_Blaze_C00_Z0003.ome.tif
└── (per additional channel: a C<NN>_Z0000 master + companions)
```

Filenames mirror the vendor convention (`..._Blaze_C<NN>_Z<NNNN>.ome.tif`) so
the matcher and adapter behave identically to a full export. The master's
`<Pixels>` / `<TiffData>` XML is rewritten so the dims and file map are
self-consistent with the trimmed companion set.

**Where the source lives**

Calico's NAS, under
`/Volumes/advanced-imaging-ro/Cleared-Tissue-Data/blaze-macsiq-processed/<experiment>`.
Any of the experiments under that directory should work. The integration test
asserts only on the structural invariants (dims, channel names, pixel sizes)
that should hold for every well-formed MACS iQ export, so the choice of source
experiment doesn't affect the assertions.

**How to regenerate**

```bash
python scripts/build_macs_iq_subset.py \
    /Volumes/advanced-imaging-ro/Cleared-Tissue-Data/blaze-macsiq-processed/<exp> \
    tests/fixtures/macs_iq_subset \
    --z-start 0 --z-count 4 --crop 256
```

The defaults — first 4 Z-planes, 256×256 spatial crop — keep the fixture under
a few hundred kilobytes per channel even on uint16 data. Adjust `--z-count`
or `--crop` if a future test needs more coverage; bigger windows are fine, the
test logic doesn't care about absolute sizes.

After regenerating, run `pytest tests/test_real_macs_iq.py` to confirm.

**If the fixture is missing**

`tests/test_real_macs_iq.py` skips with a message pointing at this README,
rather than failing the suite. CI runs against the synthetic fixtures only;
the real-world integration test gates on whether the subset has been built
and committed.
