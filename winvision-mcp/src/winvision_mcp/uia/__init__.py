"""UI Automation layer.

Wrappers over the ``uiautomation`` library (yinkaisheng) to:

- enumerate/serialize the UIA tree (:mod:`tree`)
- find elements by composable queries (:mod:`finder`)
- invoke standard UIA patterns (:mod:`patterns`)
- cache element handles by opaque token (:mod:`cache`)

All functions in this package are Windows-only — importing the package on
non-Windows raises ``OSError`` at first use, but the module itself can be
imported (so tooling like ruff/mypy can lint it cross-platform).
"""

from __future__ import annotations
