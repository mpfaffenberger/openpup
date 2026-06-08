"""Platform adapters: thin wrappers over official client libraries.

Each adapter implements :class:`PlatformAdapter` and is built via
``build_enabled_adapters(settings, registry)`` which only instantiates the
platforms that are both enabled in config and have their optional dependency
installed.
"""

from openpup.platforms.base import PlatformAdapter, build_enabled_adapters

__all__ = ["PlatformAdapter", "build_enabled_adapters"]
