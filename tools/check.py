"""Complete existing offline gate; no live collector or model."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
if env.get("HUB_CORE"):
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [env["HUB_CORE"], env.get("PYTHONPATH")]))
subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
               cwd=root, env=env, check=True)
