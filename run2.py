"""Start the Support Ticket Triage API and Streamlit UI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
python = sys.executable

vector_path = ROOT / "data" / "vector_store"
if not vector_path.exists():
    print("Building local retrieval indexes; the first run downloads CPU models.")
    subprocess.run([python, "-m", "App.ingest"], check=True)

api = subprocess.Popen([
    python, "-m", "uvicorn", "App.api:app",
    "--host", "127.0.0.1", "--port", "8000",
])

try:
    deadline = time.monotonic() + 15

    while time.monotonic() < deadline:
        if api.poll() is not None:
            raise RuntimeError(
                "The API could not start on port 8000. Another process may "
                "already be using it. Stop the other project run, then try again."
            )

        try:
            with urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
                health = json.load(response)

            if health.get("app") != "Support Ticket Triage":
                raise RuntimeError(
                    "Port 8000 is serving a different API. Stop that process "
                    "before starting this project."
                )
            break
        except (URLError, TimeoutError, ValueError):
            time.sleep(0.25)
    else:
        raise RuntimeError(
            "The Support Ticket Triage API did not become ready on port 8000 "
            "within 15 seconds."
        )

    print("API: http://127.0.0.1:8000 | UI: http://localhost:8501")
    subprocess.run([
        python, "-m", "streamlit", "run",
        str(ROOT / "App" / "ui" / "streamlit_app.py"),
    ], check=False)
finally:
    if api.poll() is None:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()