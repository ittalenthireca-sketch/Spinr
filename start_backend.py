"""
Dev launcher for Spinr FastAPI backend.
Run: python3 start_backend.py

reload=False is intentional for the Claude Code preview environment.
On Windows, uvicorn's reload mode spawns child processes via multiprocessing
"spawn" — those children start fresh Python interpreters that don't inherit
sys.path modifications, causing bare-import failures (e.g. `from db import db`).
Running without reload avoids the subprocess entirely: uvicorn serves the app
in-process where sys.path is already patched. The preview_start tool handles
server restart on demand, so live-reload is not needed here.
"""
import sys
import os

repo_root = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(repo_root, "backend")

# Patch path so both `import backend` and bare imports like
# `from db import db` resolve correctly in this process.
sys.path.insert(0, backend_dir)
sys.path.insert(0, repo_root)
os.chdir(repo_root)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "backend.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
