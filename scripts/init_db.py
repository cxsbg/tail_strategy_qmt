from __future__ import annotations

from pathlib import Path

from storage.sqlite import SQLiteStore
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


def main() -> None:
    configure_logging()
    logger = get_logger(__name__)
    data_config = load_config_file(Path("config/data_source.yaml"))
    sqlite_path = data_config["storage"]["sqlite_path"]
    SQLiteStore(sqlite_path).initialize()
    logger.info("SQLite database initialized at %s", sqlite_path)


if __name__ == "__main__":
    main()
