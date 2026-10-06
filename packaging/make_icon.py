"""Writes packaging/agent.ico (the app, installer and shortcut icon) from the same drawing the tray uses."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from call_analyzer.agent_app import draw_icon  # noqa: E402

out = Path(__file__).with_name("agent.ico")
draw_icon(None, 256).save(out, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print(f"wrote {out}")
