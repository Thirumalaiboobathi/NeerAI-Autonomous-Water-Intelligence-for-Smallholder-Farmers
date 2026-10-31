"""Start backend + frontend for the offline demo (no AWS needed). Ctrl+C stops both."""
import os, subprocess, sys, pathlib

root = pathlib.Path(__file__).resolve().parents[1]
py = root / "backend" / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
procs = [
    subprocess.Popen([str(py if py.exists() else sys.executable), "-m", "uvicorn", "app.main:create_app", "--factory", "--port", "8000"], cwd=root / "backend"),
    subprocess.Popen(["npm", "run", "dev"], cwd=root / "frontend", shell=os.name == "nt"),
]
print("NeerAI demo: http://localhost:5173  (API docs: http://localhost:8000/docs)")
try:
    [p.wait() for p in procs]
except KeyboardInterrupt:
    [p.terminate() for p in procs]
