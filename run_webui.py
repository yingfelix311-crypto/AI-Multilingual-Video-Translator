"""Entry point for the VideoLingo dubbing web UI."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Run the VideoLingo dubbing web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ["PATH"] += os.pathsep + str(ROOT)
    # NLTK blocks imports from the working directory, which breaks spacy/regex here.
    os.environ.setdefault("NLTK_DISABLE_IMPORT_SECURITY", "1")
    os.environ.setdefault("PYTHONWARNINGS", "ignore")

    import uvicorn

    print(f"VideoLingo Dubbing UI -> http://{args.host}:{args.port}")
    uvicorn.run("webui.server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
