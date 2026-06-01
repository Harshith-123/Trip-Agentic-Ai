"""
AI Travel Savings Agent - Launcher
Usage: python main.py

Starts the FastAPI backend (port 8000) + Next.js frontend (port 3000),
then opens http://localhost:3000 in your browser.

Two separate UIs are available:
  /agent   - Agentic AI pipeline  (LangGraph + Duffel + Groq/Claude/OpenAI)
  /scraper - Quick Scraper        (15+ platforms, no LLM needed)

Press Ctrl+C to stop all servers.
"""
import os
import sys
import time
import socket
import subprocess
import threading
import webbrowser
from pathlib import Path

ROOT          = Path(__file__).parent
FRONTEND      = ROOT / "frontend"
BACKEND_PORT  = 8000
FRONTEND_PORT = 3000


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_port(port: int, timeout: int = 90, label: str = "") -> bool:
    label = label or f"port {port}"
    print(f"  Waiting for {label}", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            print(" ✓")
            return True
        print(".", end="", flush=True)
        time.sleep(1)
    print(" ✗ timed out")
    return False


def _stop_all(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def _start_backend(procs: list[subprocess.Popen]) -> bool:
    print("\n[1/3] Backend  (FastAPI - port 8000)")
    if _port_open(BACKEND_PORT):
        print("  Already running - skipping.")
        return True
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.server:app",
         "--host", "0.0.0.0", "--port", str(BACKEND_PORT),
         "--log-level", "warning"],
        cwd=str(ROOT),
    )
    procs.append(proc)
    if not _wait_for_port(BACKEND_PORT, timeout=40, label="FastAPI"):
        print("\n  ERROR: Backend failed to start.")
        return False
    return True


def _start_frontend(procs: list[subprocess.Popen]) -> bool:
    print("\n[2/3] Frontend (Next.js - port 3000)")
    if _port_open(FRONTEND_PORT):
        print("  Already running - skipping.")
        return True
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    if not (FRONTEND / "node_modules").exists():
        print("  First run - installing npm packages…")
        subprocess.run([npm, "install"], cwd=str(FRONTEND), check=True)
    proc = subprocess.Popen(
        [npm, "run", "dev"],
        cwd=str(FRONTEND),
        env={**os.environ, "PORT": str(FRONTEND_PORT)},
    )
    procs.append(proc)
    if not _wait_for_port(FRONTEND_PORT, timeout=90, label="Next.js"):
        print("\n  ERROR: Frontend failed to start.")
        return False
    return True


def _print_banner(url: str) -> None:
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print(f"║  App   →  {url:<47}  ║")
    print(f"║  Docs  →  http://localhost:{BACKEND_PORT}/docs{'':<28}  ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  ✈️  /agent    LangGraph + Duffel + LLM pipeline          ║")
    print("║  🔍 /scraper  Direct scraping - 15+ platforms, no LLM    ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print("\n  Press Ctrl+C to stop.\n")


def main() -> None:
    procs: list[subprocess.Popen] = []

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         AI Travel Savings Agent  -  Launcher             ║")
    print("╚══════════════════════════════════════════════════════════╝")

    try:
        if not _start_backend(procs):
            _stop_all(procs)
            sys.exit(1)

        if not _start_frontend(procs):
            _stop_all(procs)
            sys.exit(1)

        print("\n[3/3] Opening browser…")
        url = f"http://localhost:{FRONTEND_PORT}"
        threading.Thread(
            target=lambda: (time.sleep(1.5), webbrowser.open(url)),
            daemon=True,
        ).start()

        _print_banner(url)

        for p in procs:
            p.wait()

    except KeyboardInterrupt:
        print("\n\nStopping servers…")
    finally:
        _stop_all(procs)
        print("Done.")


if __name__ == "__main__":
    main()
