import sys
import os
from pathlib import Path

backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import uvicorn
from main import app

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    print(f"Starting Meridian Knowledge-Base Agent Server at http://127.0.0.1:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)


