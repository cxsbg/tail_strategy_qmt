from __future__ import annotations

import argparse

from scripts._bootstrap import ensure_src_path

ensure_src_path()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Tail Strategy QMT web console.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    import uvicorn

    uvicorn.run("web_console.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
