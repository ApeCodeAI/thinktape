"""thinktape — personal dump tool."""

__version__ = "2.0.0"

from .core import ThinkTape
from .models import Item

__all__ = ["ThinkTape", "Item", "__version__"]
