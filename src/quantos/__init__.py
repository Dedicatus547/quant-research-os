"""Deterministic quantitative research infrastructure."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("quant-research-os")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.1.0.dev0"

__all__ = ["__version__"]
