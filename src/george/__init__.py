"""George, the creepy gargoyle Discord bot."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("botgeorge")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "1.1.0"
