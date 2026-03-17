#!/usr/bin/env python3
"""
reset_data.py — wipe all persisted game data and start fresh.

Usage (run from the repo root or backend directory):
    python scripts/reset_data.py

Stop the backend server before running this script — SQLite may have a write
lock open if the backend is running.
"""

import os
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data")
DATA_DIR = os.path.normpath(DATA_DIR)

# SQLite database file (replaced LanceDB — no directory, just one file)
TARGETS = [
    os.path.join(DATA_DIR, "mud.db"),
]


def confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
        return answer == "y"
    except (KeyboardInterrupt, EOFError):
        return False


def reset():
    print("\n=== SINGLE PLAYER AI MUD — DATA RESET ===\n")

    found = [t for t in TARGETS if os.path.exists(t)]
    if not found:
        print("Nothing to delete — data directory is already clean.")
        return

    print("The following will be permanently deleted:")
    for path in found:
        size = os.path.getsize(path)
        print(f"  {path}  ({size / 1024:.1f} KB)")

    print()
    if not confirm("Delete all game data?"):
        print("Aborted — nothing was deleted.")
        return

    errors = []
    for path in found:
        try:
            os.remove(path)
            print(f"  Deleted: {path}")
        except Exception as e:
            errors.append((path, str(e)))
            print(f"  ERROR deleting {path}: {e}")

    if errors:
        print(f"\n{len(errors)} error(s) occurred. Close the backend server and try again.")
        sys.exit(1)
    else:
        print("\nDone. All game data cleared.")
        print("Restart the backend — it will recreate the database on first player creation.")


if __name__ == "__main__":
    reset()
