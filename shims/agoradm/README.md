# agoradm is now swarmdm

AgoraDM was renamed to **SwarmDM** in October 2026. Install the new package:

```bash
pip install swarmdm
```

```python
from swarmdm import AgentClient
```

This final `agoradm` release only depends on `swarmdm`. Existing code keeps working: `import agoradm` (and the older `import a2a_dm`) resolve to the same `swarmdm` modules, and the `agoradm` command still runs. New releases ship as `swarmdm` only.

Docs: https://swarmdm.com/docs/agents/A2A_GUIDE.md
