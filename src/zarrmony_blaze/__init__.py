"""zarrmony-blaze — Miltenyi Blaze (MACS iQ-processed) reader plugin for zarrmony.

Importing this package exposes a ``plugin`` value (a ``ReaderPlugin``) that is
also surfaced via the ``zarrmony.readers`` entry point declared in
``pyproject.toml``. End users do not import from this package directly; they
``pip install zarrmony-blaze`` and zarrmony picks the plugin up automatically.
"""

from pathlib import Path

from zarrmony.readers.plugin import ReaderPlugin

from .adapter import BlazeReader
from .match import match

__all__ = ["BlazeReader", "match", "plugin"]


def _open(path: Path) -> BlazeReader:
    return BlazeReader(path)


plugin = ReaderPlugin(
    name="zarrmony-blaze",
    match=match,
    open=_open,
    distribution="zarrmony-blaze",
    source="entry_point",
)
