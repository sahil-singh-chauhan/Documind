"""
ExplainDoc Frontend Dev Server
Run this from the frontend/ directory:  python server.py
"""
import http.server
import socketserver
import os
import sys

PORT = int(os.environ.get("PORT", 3000))

class SilentHandler(http.server.SimpleHTTPRequestHandler):
    """Suppress per-request log noise so only the startup banner shows."""
    def log_message(self, format, *args):
        pass  # Suppress per-request logging

if __name__ == "__main__":
    # Change working directory to the folder this script lives in
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    with socketserver.TCPServer(("", PORT), SilentHandler) as httpd:
        print("")
        print("  ExplainDoc Frontend")
        print("  -----------------")
        print(f"  Local:   http://localhost:{PORT}")
        print(f"  Network: http://127.0.0.1:{PORT}")
        print("")
        print("  Press CTRL+C to stop the server.")
        print("")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Frontend server stopped.")
            sys.exit(0)
