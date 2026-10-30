"""Compatibility alias: ``agoradm_mcp`` was renamed to ``swarmdm_mcp`` (2026-10, AgoraDM → SwarmDM).

``import agoradm_mcp`` and ``from agoradm_mcp.<submodule> import ...`` keep working and
return the very same module objects as ``swarmdm_mcp``, so isinstance checks and
module state are shared. New code should import ``swarmdm_mcp``.
"""

import importlib
import importlib.abc
import importlib.util
import sys

_OLD, _NEW = "agoradm_mcp", "swarmdm_mcp"


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Resolve ``agoradm_mcp.x.y`` to the already-importable ``swarmdm_mcp.x.y``."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(_OLD + "."):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        module = importlib.import_module(_NEW + spec.name[len(_OLD):])
        spec.loader_state = module.__spec__
        return module

    def exec_module(self, module):
        # The import system stamps the alias spec on the module; put the
        # real one back so reloads and introspection see swarmdm_mcp.
        module.__spec__ = module.__spec__.loader_state


sys.meta_path.insert(0, _Alias())
sys.modules[__name__] = importlib.import_module(_NEW)
