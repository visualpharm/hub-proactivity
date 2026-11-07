"""Demo hub for developing the plugin: the real hub page on a throwaway journal, the plugin's page part loaded.

    python3 dev/serve.py [--port N]

Hub code: $HUB_CORE (a hub checkout). Only the page tab is served (no process): the tab reads the
`config` post, so the demo seeds one the way the process writes it.
"""
import json
import os
import sys
import threading
import time

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = os.environ.get("HUB_CORE") or sys.exit("dev/serve.py: set HUB_CORE to a hub checkout")
sys.path.insert(0, HUB)

import tests  # noqa: E402, F401 — hub tests: own state and config folders, never the machine's
from tests import test_web  # noqa: E402


def seed(t, preset="draft"):
    own = {"channel": "cli", "owner": True}
    ev = lambda type, entity=None, **data: t.j.append(type, entity, data)   # noqa: E731
    ev("session.requested", "hub", session_id="s-hub", cwd="/w/hub-home", kind="hub", **own)
    ev("session.started", "hub", session_id="s-hub")
    cfg = {"kind": "config", "v": 1, "preset": preset, "triager": "auto", "digest_h": 3, "chosen": False,
           "level_send": False}
    ev("ext.post", None, plugin="proactivity", text=json.dumps(cfg), channel="plugin", owner=False, sender="proactivity")


def main(argv):
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 1101
    with open(os.environ["HUB_CONFIG"], "w") as f:
        json.dump({"dev": {"enabled": False}, "agent_dev": {"enabled": False}, "update": {"enabled": False},
                   "extensions": {"proactivity": {"path": PLUGIN, "web": "main.js"}}}, f)
    t = test_web.WebTest("test_page_and_snapshot")
    t.setUp()
    t.server.shutdown()
    t.server.server_close()
    t.server = t.web.serve(port=port)
    threading.Thread(target=t.server.serve_forever, daemon=True).start()
    seed(t, os.environ.get("PRESET", "draft"))
    t.settle()
    print(f"demo hub: http://127.0.0.1:{port}/", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        t.tearDown()


if __name__ == "__main__":
    main(sys.argv[1:])
