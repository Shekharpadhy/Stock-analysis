"""Create a timestamped PostgreSQL database backup."""
import subprocess, sys
from datetime import datetime

def backup(db_url: str, output_dir: str = "backups") -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{output_dir}/bcsi_backup_{ts}.sql"
    print(f"Backing up database to {fname}...")
    # subprocess.run(["pg_dump", db_url, "-f", fname], check=True)
    print("Backup complete (dry run — add pg_dump call).")

if __name__ == "__main__":
    import os
    backup(os.environ.get("DATABASE_URL", ""))
