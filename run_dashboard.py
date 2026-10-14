"""
run_dashboard.py
────────────────
Simple zero-dependency local web server to launch the AutoTok Studio Dashboard.
Opens your browser automatically to http://localhost:5000/dashboard.html
"""

import http.server
import socketserver
import webbrowser
from pathlib import Path

PORT = 5000
DIRECTORY = Path(__file__).parent / "docs"

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

def main():
    print("=" * 60)
    print("  🚀 AutoTok Studio Dashboard")
    print(f"  Serving on: http://localhost:{PORT}/dashboard.html")
    print("  Press Ctrl+C to stop the server.")
    print("=" * 60)

    # Open browser automatically after a short delay
    webbrowser.open(f"http://localhost:{PORT}/dashboard.html")

    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard server stopped.")

if __name__ == "__main__":
    main()
