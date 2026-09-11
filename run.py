import os
import sys
import webbrowser
import threading
import time
import socket
import uvicorn

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def find_available_port(start_port: int = 8000) -> int:
    port = start_port
    while port < 9000:
        if not is_port_in_use(port):
            return port
        port += 1
    return start_port

def open_browser(url: str):
    time.sleep(1.2)
    print(f"Opening browser at {url}...")
    webbrowser.open(url)

def main():
    port = int(os.environ.get("PORT") or find_available_port(8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    url = f"http://127.0.0.1:{port}"
    
    print("=" * 65)
    print("  ZeroSyN - NIFTY & SENSEX Synthetic Future Terminal")
    print("  Put-Call Parity Live Chart Engine (NSE / BSE)")
    print("=" * 65)
    print(f"  Server URL      : {url}")
    print(f"  WebSocket Stream: ws://{host}:{port}/ws")
    print("  Rate Frequency  : 1-second ticks")
    print("=" * 65)
    print("Press Ctrl+C to terminate the server.\n")

    # Open browser automatically if running locally
    if not os.environ.get("PORT"):
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    # Run Uvicorn server with auto-reload so code updates reflect immediately
    uvicorn.run("backend.main:app", host=host, port=port, reload=True, log_level="info")

if __name__ == "__main__":
    main()
