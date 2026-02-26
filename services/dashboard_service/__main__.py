"""Entry point: `python -m services.dashboard_service`."""

from .app import run_server

if __name__ == "__main__":
    print("Starting Alchimista Dashboard...")
    print("Open http://localhost:8000 in your browser")
    run_server()
