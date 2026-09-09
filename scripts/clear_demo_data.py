"""Remove only records created by the optional JobPilot demo seed."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jobpilot.storage import ApplicationRepository  # noqa: E402


def clear_demo_data(repository: ApplicationRepository | None = None) -> int:
    """Delete records marked as demo and return the number removed."""
    repository = repository or ApplicationRepository()
    return repository.delete_demo_applications()


def main() -> None:
    removed = clear_demo_data()
    print(f"Removed {removed} demo applications.")


if __name__ == "__main__":
    main()
