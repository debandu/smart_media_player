#!/usr/bin/env python3
"""
run.py — setup and launch for Smart Media Player.

First run: creates the venv, installs dependencies, creates a .env template.
Subsequent runs: launches the app directly.

Usage:
    python run.py           # setup if needed, then launch
    python run.py --setup   # force re-run the setup steps
"""

import os
import sys
import subprocess
import shutil
import platform
from pathlib import Path

ROOT = Path(__file__).parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
ENV_FILE = ROOT / ".env"
SENTINEL = ROOT / ".setup_done"

REQUIRED_ENV_KEYS = ["GROQ_API_KEY", "MODEL", "BASE_URL", "CHROMA_DB_PATH"]
PLACEHOLDER_GROQ_KEY = "your_groq_api_key_here"


# ---------------------------------------------------------------------------
# Paths inside the venv
# ---------------------------------------------------------------------------

def _venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_pip() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _venv_ready() -> bool:
    return _venv_python().exists()


def _packages_installed() -> bool:
    if not SENTINEL.exists():
        return False
    # Quickly verify a key package is actually importable in the venv
    result = subprocess.run(
        [str(_venv_python()), "-c", "import PySide6, faster_whisper, chromadb"],
        capture_output=True,
    )
    return result.returncode == 0


def _env_configured() -> bool:
    if not ENV_FILE.exists():
        return False
    text = ENV_FILE.read_text()
    for key in REQUIRED_ENV_KEYS:
        value = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                value = line[len(key) + 1:].strip()
                break
        if not value or value == PLACEHOLDER_GROQ_KEY:
            return False
    return True


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _is_setup_done() -> bool:
    return _venv_ready() and _packages_installed() and _env_configured()


# ---------------------------------------------------------------------------
# Setup steps
# ---------------------------------------------------------------------------

def _create_venv() -> None:
    print("[setup] Creating virtual environment ...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    print("[setup] Done.")


def _install_packages() -> None:
    print("[setup] Installing dependencies (this may take a few minutes) ...")
    subprocess.run(
        [str(_venv_pip()), "install", "--upgrade", "pip"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [str(_venv_pip()), "install", "-r", str(REQUIREMENTS)],
        check=True,
    )
    SENTINEL.write_text("installed\n")
    print("[setup] Dependencies installed.")


def _create_env_template() -> None:
    print("[setup] Creating .env template ...")
    ENV_FILE.write_text(
        "# LLM — get a free key at https://console.groq.com\n"
        f"GROQ_API_KEY={PLACEHOLDER_GROQ_KEY}\n"
        "MODEL=llama3-8b-8192\n"
        "BASE_URL=https://api.groq.com/openai/v1\n"
        "\n"
        "# ChromaDB\n"
        "CHROMA_DB_PATH=./chroma_db\n"
    )
    print(f"[setup] .env created at {ENV_FILE}")


def _run_setup(force: bool = False) -> None:
    print("=" * 50)
    print("  Smart Media Player — Setup")
    print("=" * 50)

    if not _venv_ready() or force:
        _create_venv()
    else:
        print("[setup] Virtual environment already exists — skipping.")

    if not _packages_installed() or force:
        _install_packages()
    else:
        print("[setup] Dependencies already installed — skipping.")

    if not ENV_FILE.exists():
        _create_env_template()
        print(
            "\n[action required] Edit .env and replace the placeholder GROQ_API_KEY,\n"
            "                  then run `python run.py` again.\n"
        )
        sys.exit(0)
    else:
        print("[setup] .env already exists — skipping template creation.")

    print("\n[setup] Setup complete.\n")


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def _launch() -> None:
    print("[run] Starting Smart Media Player ...")
    python = str(_venv_python())
    main_script = str(ROOT / "main.py")
    # Replace the current process so the app owns the terminal properly
    if platform.system() == "Windows":
        result = subprocess.run([python, main_script])
        sys.exit(result.returncode)
    else:
        os.execv(python, [python, main_script])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    force_setup = "--setup" in sys.argv

    if force_setup or not _is_setup_done():
        _run_setup(force=force_setup)

    # After setup, re-check env before launching
    if not _env_configured():
        print(
            "[error] .env is missing or has placeholder values.\n"
            f"        Edit {ENV_FILE} and set these keys:\n"
        )
        for key in REQUIRED_ENV_KEYS:
            print(f"          {key}")
        print("\nRe-run `python run.py` when done.")
        sys.exit(1)

    if not _ffmpeg_available():
        print("[warn] ffmpeg is not on your PATH — transcription will fail.")
        if platform.system() == "Darwin":
            print("       Install with: brew install ffmpeg")
        elif platform.system() == "Windows":
            print("       Install with: choco install ffmpeg")
        else:
            print("       Install with: sudo apt install ffmpeg")
        print()

    _launch()


if __name__ == "__main__":
    main()
