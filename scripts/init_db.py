"""Initialize the database by running all Alembic migrations."""
import subprocess
import sys


def init_db() -> None:
    print("Running Alembic migrations...")
    result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Migration failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Database initialized successfully.")
    if result.stdout:
        print(result.stdout)


if __name__ == "__main__":
    init_db()
