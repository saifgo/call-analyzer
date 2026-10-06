"""The installed agent app (CallAnalyzerAgent.exe): a tray icon, a first-run window to connect to the server, and
start-with-Windows, around the agent in agent.py.

    CallAnalyzerAgent.exe                 open the app (connect window the first time, then the tray icon)
    CallAnalyzerAgent.exe --background    the same, started with Windows: no window unless it must connect
    CallAnalyzerAgent.exe login --code ca1.…  |  run  |  status  |  autostart [--off]     (command line, same as
                                                                    python -m call_analyzer agent …)
"""
import argparse
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import agent as agent_mod
from .config import FROZEN

APP_NAME = "Call Analyzer Agent"
TEAL = (13, 148, 136)
STATE_COLORS = {  # the dot on the tray icon
    "online": (34, 197, 94), "working": (59, 130, 246), "paused": (245, 158, 11),
    "offline": (156, 163, 175), "error": (239, 68, 68),
}


# --- Helpers ------------------------------------------------------------------------------------

def draw_icon(state: str | None = None, size: int = 64):
    """The app icon (teal square, "CA"), with a coloured status dot for the tray."""
    from PIL import Image, ImageDraw, ImageFont
    scale = 4  # draw big, then shrink: smooth edges
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 14 // 64, fill=TEAL)
    font = None
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, big * 26 // 64)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    draw.text((big // 2, big // 2), "CA", fill="white", font=font, anchor="mm")
    if state:
        r = big * 13 // 64
        cx = cy = big - r - big // 32
        draw.ellipse((cx - r - big // 40, cy - r - big // 40, cx + r + big // 40, cy + r + big // 40), fill="white")
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=STATE_COLORS[state])
    return image.resize((size, size), Image.LANCZOS)


def message(text: str, *, error: bool = False):
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
    else:
        print(text, file=sys.stderr if error else sys.stdout)


def attach_console():
    """The app is a windowed program; when it is started from a terminal with a command, print there."""
    if os.name == "nt" and FROZEN:
        try:
            if ctypes.windll.kernel32.AttachConsole(-1):  # the parent's console
                sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        except Exception:
            pass


def relaunch(*args: str):
    command = [sys.executable, *args] if FROZEN else [sys.executable, "-m", "call_analyzer.agent_app", *args]
    subprocess.Popen(command, close_fds=True)


_keep = []  # the single-instance handle must stay alive as long as the program runs


def single_instance() -> bool:
    if os.name == "nt":
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\CallAnalyzerAgent")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        _keep.append(handle)
        return True
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 47653))
    except OSError:
        return False
    _keep.append(sock)
    return True


def _dpi_aware():
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


# --- First-run window ---------------------------------------------------------------------------

def setup_window() -> bool:
    """Ask for the connection code and connect. Returns True once connected."""
    import tkinter as tk
    from tkinter import ttk

    _dpi_aware()
    root = tk.Tk()
    root.title(APP_NAME)
    root.resizable(False, False)
    try:
        from PIL import ImageTk
        root.iconphoto(True, ImageTk.PhotoImage(draw_icon()))
    except Exception:
        pass
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")

    frame = ttk.Frame(root, padding=24)
    frame.grid()
    ttk.Label(frame, text="Connect this PC to your Call Analyzer server", font=("Segoe UI", 13, "bold")).grid(
        sticky="w")
    ttk.Label(frame, wraplength=460, justify="left", text=(
        "On the server, open Remote agents, click Add agent, and copy the connection code. "
        "Paste it here. This PC will then transcribe and analyze calls for the server.")).grid(
        sticky="w", pady=(8, 14))
    code = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=code, width=66)
    entry.grid(sticky="ew")
    entry.focus_set()
    status = tk.StringVar()
    status_label = ttk.Label(frame, textvariable=status, wraplength=460, justify="left", foreground="#b91c1c")
    status_label.grid(sticky="w", pady=(10, 0))
    buttons = ttk.Frame(frame)
    buttons.grid(sticky="e", pady=(16, 0))
    connect_button = ttk.Button(buttons, text="Connect")
    quit_button = ttk.Button(buttons, text="Quit", command=root.destroy)
    quit_button.grid(row=0, column=0, padx=(0, 8))
    connect_button.grid(row=0, column=1)

    result = {"connected": False, "reply": None}

    def poll():
        if result["reply"] is None:
            root.after(100, poll)
            return
        kind, value = result["reply"]
        result["reply"] = None
        if kind == "ok":
            result["connected"] = True
            root.destroy()
            return
        status_label.configure(foreground="#b91c1c")
        status.set(value)
        connect_button.state(["!disabled"])
        entry.state(["!disabled"])

    def work(server: str, token: str):
        try:
            agent_mod.connect(server, token)
            result["reply"] = ("ok", None)
        except agent_mod.ConnectError as exc:
            result["reply"] = ("err", str(exc))
        except Exception as exc:  # never leave the window stuck on "Connecting…"
            result["reply"] = ("err", f"Unexpected error: {exc}")

    def go(_event=None):
        try:
            server, token = agent_mod.parse_connection(code.get())
        except agent_mod.ConnectError as exc:
            status.set(str(exc))
            return
        status_label.configure(foreground="#374151")
        status.set("Connecting…")
        connect_button.state(["disabled"])
        entry.state(["disabled"])
        threading.Thread(target=work, args=(server, token), daemon=True).start()
        poll()

    connect_button.configure(command=go)
    root.bind("<Return>", go)
    root.update_idletasks()
    root.geometry(f"+{(root.winfo_screenwidth() - root.winfo_width()) // 2}+{(root.winfo_screenheight() - root.winfo_height()) // 3}")
    root.mainloop()
    return result["connected"]


# --- Tray app -----------------------------------------------------------------------------------

class TrayApp:
    def __init__(self, show_welcome: bool):
        import pystray
        self.pystray = pystray
        self.show_welcome = show_welcome
        server, token = agent_mod.load_credentials()
        overrides, slots = agent_mod.load_local()
        self.server = server
        self.agent = agent_mod.Agent(server, token, overrides, slots)
        self.state = "offline"
        self.stopping = threading.Event()
        self.icon = pystray.Icon("CallAnalyzerAgent", draw_icon(self.state), APP_NAME, self.menu())
        self.thread = threading.Thread(target=self._run_agent, daemon=True)

    # the agent runs in the background; the tray reflects it ----------------------------------------

    def _run_agent(self):
        try:
            self.agent.run()
        except agent_mod.AuthError:
            message("The server no longer accepts this PC: the agent was removed or given a new token.\n\n"
                    "Connect it again with a new connection code.", error=True)
            self.stopping.set()
            relaunch("--setup")
            self.icon.stop()
        except agent_mod.OutdatedError as exc:
            message(f"{exc}\n\nInstall the latest Call Analyzer Agent.", error=True)
            self.stopping.set()
            self.icon.stop()

    def current_state(self) -> str:
        agent = self.agent
        if not agent.connected:
            return "offline"
        if agent.paused or not agent.enabled:
            return "paused"
        return "working" if agent.running else "online"

    def status_text(self, *_) -> str:
        agent, state = self.agent, self.current_state()
        if state == "offline":
            return "Can't reach the server, trying again…"
        if not agent.enabled:
            return "Paused by an admin on the server"
        if agent.paused:
            return "Paused on this PC"
        if state == "working":
            kinds = sorted(set(agent.running.values()))
            return f"Working: {len(agent.running)} {'call' if len(agent.running) == 1 else 'calls'} ({', '.join(kinds)})"
        return "Connected, waiting for calls"

    def _watch(self):
        while not self.stopping.wait(2):
            state = self.current_state()
            if state != self.state:
                self.state = state
                self.icon.icon = draw_icon(state)
            self.icon.title = f"{APP_NAME}: {self.status_text()}"
            self.icon.update_menu()

    # menu ----------------------------------------------------------------------------------------

    def menu(self):
        item, menu = self.pystray.MenuItem, self.pystray.Menu
        nothing = lambda icon, entry: None  # noqa: E731
        items = [
            item(lambda entry: f"{APP_NAME}: {self.agent.name or 'connecting…'}", nothing, enabled=False),
            item(self.status_text, nothing, enabled=False),
            menu.SEPARATOR,
            item("Pause on this PC", self.toggle_pause, checked=lambda entry: self.agent.paused),
            item("Open the dashboard", lambda icon, entry: webbrowser.open(f"{self.server}/#agents")),
            item("Edit this agent's settings", self.open_settings),
            item("Open the log", lambda icon, entry: self.open_path(agent_mod.home() / "agent.log")),
        ]
        if FROZEN:
            items.append(item("Start with Windows", self.toggle_autostart,
                              checked=lambda entry: agent_mod.autostart_enabled()))
        items += [
            item("Connect to another server…", self.reconnect),
            menu.SEPARATOR,
            item("Quit", self.quit),
        ]
        return menu(*items)

    def toggle_pause(self, icon, entry):
        self.agent.paused = not self.agent.paused

    def toggle_autostart(self, icon, entry):
        agent_mod.set_autostart(not agent_mod.autostart_enabled())

    @staticmethod
    def open_path(path: Path):
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            webbrowser.open(path.as_uri())

    def open_settings(self, icon, entry):
        path = agent_mod.overrides_path()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(agent_mod.OVERRIDES_TEMPLATE, encoding="utf-8")
        self.open_path(path)

    def reconnect(self, icon, entry):
        self.stopping.set()
        relaunch("--setup")
        self.quit(icon, entry)

    def quit(self, icon=None, entry=None):
        self.stopping.set()
        self.agent.stop.set()
        self.icon.stop()

    # run -----------------------------------------------------------------------------------------

    def run(self):
        def ready(icon):
            icon.visible = True
            if self.show_welcome:
                try:
                    icon.notify("Connected. This PC now works for the server; the icon shows what it is doing.", APP_NAME)
                except Exception:
                    pass
            self.thread.start()
            threading.Thread(target=self._watch, daemon=True).start()

        self.icon.run(setup=ready)
        self.agent.stop.set()
        self.thread.join(8)  # lets it tell the server it is leaving


def run_app(*, background: bool = False, setup_first: bool = False):
    if setup_first or not agent_mod.credentials_path().exists() and not (
            os.getenv("AGENT_SERVER") and os.getenv("AGENT_TOKEN")):
        if not setup_window():
            return
        background = False
    if not single_instance():
        message("Call Analyzer Agent is already running: look for its icon near the clock.")
        return
    agent_mod._setup_logging()
    TrayApp(show_welcome=not background).run()


# --- Entry point --------------------------------------------------------------------------------

def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv in (["--background"], ["--setup"]):
        run_app(background=argv == ["--background"], setup_first=argv == ["--setup"])
        return
    attach_console()
    parser = argparse.ArgumentParser(prog="CallAnalyzerAgent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["login", "run", "status", "autostart"])
    parser.add_argument("--code", help="login: the connection code from the server's Remote agents page")
    parser.add_argument("--server", help="login: address of the server")
    parser.add_argument("--token", help="login: the agent's token")
    parser.add_argument("--off", action="store_true", help="autostart: remove the Windows startup entry")
    agent_mod.main(parser.parse_args(argv))


if __name__ == "__main__":
    main()
