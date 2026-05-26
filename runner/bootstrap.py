import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
ENV = ROOT / ".env"


def run(cmd):
    print(f"\n>>> {' '.join(cmd)}")
    subprocess.check_call(cmd)


def ensure_venv():
    if VENV.exists():
        print("✓ venv exists")
        return

    print("Creating virtual environment...")
    run([sys.executable, "-m", "venv", str(VENV)])


def python_bin():
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"

    return VENV / "bin" / "python"


def pip_install():
    py = str(python_bin())

    print("Installing dependencies...")

    run([py, "-m", "pip", "install", "--upgrade", "pip"])

    if REQ.exists():
        run([py, "-m", "pip", "install", "-r", str(REQ)])


def validate_env():
    if not ENV.exists():
        raise RuntimeError(".env file missing")

    print("✓ .env exists")


def start_dev():
    py = str(python_bin())

    run([py, "-m", "runner.dev"])


def main():
    os.chdir(ROOT)
    
    session_path = ROOT / "data" / "current_session_id.txt"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        encoding="utf-8",
    )
    ensure_venv()
    pip_install()
    validate_env()

    start_dev()


if __name__ == "__main__":
    main()
