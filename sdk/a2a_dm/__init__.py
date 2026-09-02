"""Compatibility alias — this package was RENAMED to ``agoradm``.

Old imports keep working for one transition cycle::

    import a2a_dm                      # -> agoradm
    from a2a_dm.daemon import SSEDaemon

New code should import ``agoradm`` directly; this alias will be
removed in a future release.
"""

import sys as _sys
import warnings as _warnings

import agoradm as _agoradm

_warnings.warn(
    "the 'a2a_dm' package was renamed to 'agoradm' — update your "
    "imports (this alias will be removed in a future release)",
    DeprecationWarning,
    stacklevel=2,
)

# Swap the sys.modules entry so `a2a_dm` IS agoradm: attribute access
# and `a2a_dm.<submodule>` imports resolve through the real package.
_sys.modules[__name__] = _agoradm
