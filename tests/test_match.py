from pathlib import Path

from zarrmony_blaze.match import match


def test_match_blaze_master(synthetic_blaze_dir: Path) -> None:
    assert match(synthetic_blaze_dir) == 100


def test_match_returns_none_without_blaze_token(tmp_path: Path) -> None:
    # OME-tiff file present but missing the _Blaze_ vendor literal.
    (tmp_path / "sample_C00_Z0000.ome.tif").write_bytes(b"")
    assert match(tmp_path) is None


def test_match_returns_none_without_z0000_master(tmp_path: Path) -> None:
    # _Blaze_ token present but no _Z0000 master — only a companion plane.
    (tmp_path / "sample_Blaze_C00_Z0042.ome.tif").write_bytes(b"")
    assert match(tmp_path) is None


def test_match_returns_none_for_non_directory(tmp_path: Path) -> None:
    f = tmp_path / "not_a_dir.ome.tif"
    f.write_bytes(b"")
    assert match(f) is None


def test_match_returns_none_for_empty_directory(tmp_path: Path) -> None:
    assert match(tmp_path) is None
