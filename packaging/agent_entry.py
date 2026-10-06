"""Entry point of CallAnalyzerAgent.exe (PyInstaller). All the code is in call_analyzer/agent_app.py."""
import multiprocessing

from call_analyzer import agent_app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    agent_app.main()
