"""Compatibility alias: ``a2a_dm`` was renamed to ``swarmdm`` (2026-10, a2a-dm → AgoraDM → SwarmDM).

``import a2a_dm`` and ``from a2a_dm.<submodule> import ...`` keep working and
return the very same module objects as ``swarmdm``, so isinstance checks and
module state are shared. New code should import ``swarmdm``.
"""

import importlib
import importlib.abc
import importlib.util
import sys

_OLD, _NEW = "a2a_dm", "swarmdm"


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Resolve ``a2a_dm.x.y`` to the already-importable ``swarmdm.x.y``."""

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
        # real one back so reloads and introspection see swarmdm.
        module.__spec__ = module.__spec__.loader_state


sys.meta_path.insert(0, _Alias())
sys.modules[__name__] = importlib.import_module(_NEW)
