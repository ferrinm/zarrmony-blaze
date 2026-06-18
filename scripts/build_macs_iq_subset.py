"""Produce a small committable subset of a real MACS iQ-processed Blaze export.

The full 2.9 TB export is way too big to live in the test fixtures directory.
This script reads a real master ``_Z0000.ome.tif``, picks a contiguous window
of Z-planes, optionally crops to a spatial ROI, and writes:

- One master ``_C00_Z0000.ome.tif`` whose OME-XML has been rewritten so the
  reduced ``<Pixels>`` / ``<TiffData>`` set is self-consistent with the
  companion files that ship alongside it.
- ``<size_c> * <window>`` plain TIFF companions, named to mirror the source
  filename convention so the matcher and adapter behave identically.

Run once, commit the output under ``tests/fixtures/macs_iq_subset/``, and the
integration test in ``tests/test_real_macs_iq.py`` will pick it up.

Usage:

    python scripts/build_macs_iq_subset.py \\
        /Volumes/advanced-imaging-ro/Cleared-Tissue-Data/blaze-macsiq-processed/<exp> \\
        tests/fixtures/macs_iq_subset \\
        --z-start 0 --z-count 4 --crop 256
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import tifffile

OME_NS = "http://www.openmicroscopy.org/Schemas/OME/2008-02"
ET.register_namespace("", OME_NS)


def _q(name: str) -> str:
    return f"{{{OME_NS}}}{name}"


def _find_master(src: Path) -> Path:
    candidates = sorted(src.glob("*_C00_Z0000.ome.tif")) or sorted(src.glob("*_Z0000.ome.tif"))
    if not candidates:
        raise SystemExit(f"no *_Z0000.ome.tif master found in {src}")
    return candidates[0]


def _rewrite_master_xml(
    xml: str,
    *,
    keep_z: range,
    crop_y: int | None,
    crop_x: int | None,
) -> tuple[str, dict[tuple[int, int, int], str]]:
    """Trim ``<Pixels>`` SizeZ/Y/X and drop ``<TiffData>`` outside ``keep_z``.

    Returns the new XML and the surviving ``(t, c, z) → filename`` map.
    """
    root = ET.fromstring(xml)
    images = root.findall(_q("Image"))
    if len(images) != 1:
        raise SystemExit(
            f"master has {len(images)} <Image> elements — refusing to subset a "
            "multiposition export (not yet supported)."
        )
    pixels = images[0].find(_q("Pixels"))
    if pixels is None:
        raise SystemExit("master XML has no <Pixels>")

    size_t = int(pixels.attrib.get("SizeT", "1"))
    size_c = int(pixels.attrib["SizeC"])
    size_z = int(pixels.attrib["SizeZ"])
    size_y = int(pixels.attrib["SizeY"])
    size_x = int(pixels.attrib["SizeX"])

    new_size_z = len(keep_z)
    new_size_y = min(size_y, crop_y) if crop_y else size_y
    new_size_x = min(size_x, crop_x) if crop_x else size_x

    if not all(0 <= z < size_z for z in keep_z):
        raise SystemExit(f"requested Z window {keep_z} falls outside source SizeZ={size_z}")

    pixels.set("SizeZ", str(new_size_z))
    pixels.set("SizeY", str(new_size_y))
    pixels.set("SizeX", str(new_size_x))

    file_map: dict[tuple[int, int, int], str] = {}
    z_index = {old: new for new, old in enumerate(keep_z)}
    for td in list(pixels.findall(_q("TiffData"))):
        t = int(td.attrib.get("FirstT", "0"))
        c = int(td.attrib.get("FirstC", "0"))
        z = int(td.attrib.get("FirstZ", "0"))
        if z not in z_index:
            pixels.remove(td)
            continue
        new_z = z_index[z]
        td.set("FirstZ", str(new_z))
        uuid_el = td.find(_q("UUID"))
        if uuid_el is None or "FileName" not in uuid_el.attrib:
            raise SystemExit(f"<TiffData FirstZ={z}> missing <UUID FileName=...>")
        old_name = uuid_el.attrib["FileName"]
        # Renumber Z in the filename so the file ordering on disk matches the XML.
        new_name = re.sub(r"_Z\d+\.ome\.tif$", f"_Z{new_z:04d}.ome.tif", old_name)
        uuid_el.set("FileName", new_name)
        file_map[(t, c, new_z)] = new_name

    expected = size_t * size_c * new_size_z
    if len(file_map) != expected:
        raise SystemExit(
            f"after subset, file_map has {len(file_map)} entries but expected "
            f"SizeT*SizeC*SizeZ = {expected}"
        )
    new_xml = ET.tostring(root, encoding="unicode")
    return new_xml, file_map


def _copy_or_crop(
    src_path: Path, dst_path: Path, *, crop_y: int | None, crop_x: int | None
) -> None:
    if crop_y is None and crop_x is None:
        shutil.copyfile(src_path, dst_path)
        return
    data = tifffile.imread(src_path, is_ome=False)
    if data.ndim != 2:
        raise SystemExit(f"{src_path.name}: expected 2D plane, got shape {data.shape}")
    y = min(data.shape[0], crop_y) if crop_y else data.shape[0]
    x = min(data.shape[1], crop_x) if crop_x else data.shape[1]
    tifffile.imwrite(dst_path, data[:y, :x])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("src", type=Path, help="real MACS iQ processed export dir")
    p.add_argument("dst", type=Path, help="output dir (will be created)")
    p.add_argument("--z-start", type=int, default=0, help="first Z to keep")
    p.add_argument("--z-count", type=int, default=4, help="how many Zs to keep")
    p.add_argument(
        "--crop",
        type=int,
        default=256,
        help="spatial crop to YxX (pass 0 to disable)",
    )
    args = p.parse_args(argv)

    crop = args.crop or None
    args.dst.mkdir(parents=True, exist_ok=True)

    master = _find_master(args.src)
    print(f"source master: {master}")

    with tifffile.TiffFile(master) as t:
        xml = t.ome_metadata
    if xml is None:
        raise SystemExit("master has no OME-XML — wrong file?")

    keep_z = range(args.z_start, args.z_start + args.z_count)
    new_xml, file_map = _rewrite_master_xml(xml, keep_z=keep_z, crop_y=crop, crop_x=crop)

    # The companion filenames in the source export include the original Z index;
    # we renumbered to a contiguous 0..N-1 window above. Recover the source name
    # by mapping each new Z back to its original Z.
    src_z_for = {new_z: old_z for new_z, old_z in enumerate(keep_z)}

    written = 0
    for (_t_idx, c, new_z), new_name in sorted(file_map.items()):
        old_z = src_z_for[new_z]
        # Reconstruct the original filename: same prefix, original Z.
        orig_name = re.sub(r"_Z\d+\.ome\.tif$", f"_Z{old_z:04d}.ome.tif", new_name)
        src_file = args.src / orig_name
        if not src_file.is_file():
            raise SystemExit(f"missing source companion: {src_file}")
        dst_file = args.dst / new_name
        if new_z == 0 and c == 0:
            # This will become the master; we'll write it with the new XML below.
            continue
        _copy_or_crop(src_file, dst_file, crop_y=crop, crop_x=crop)
        written += 1

    # Write the master last (it carries the new XML).
    master_name = file_map[(0, 0, 0)]
    src_master_data = tifffile.imread(
        args.src / master_name.replace(f"_Z{0:04d}.ome.tif", f"_Z{args.z_start:04d}.ome.tif"),
        is_ome=False,
    )
    if crop:
        src_master_data = src_master_data[:crop, :crop]
    tifffile.imwrite(
        args.dst / master_name,
        src_master_data,
        description=new_xml,
        metadata=None,
    )
    written += 1
    print(f"wrote {written} files to {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
