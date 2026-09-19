import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.streamer import DataStreamer

streamer = DataStreamer()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start 1-second streaming background engine on startup
    await streamer.start_loop()
    yield
    # Stop on shutdown
    await streamer.stop_loop()

app = FastAPI(title="ZeroSyN Synthetic Future Terminal", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST Endpoints
@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/ping", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "ok"}

@app.api_route("/api/status", methods=["GET", "HEAD"])
async def get_status():
    return {
        "status": "online",
        "active_clients": len(streamer.active_connections),
        "symbols": ["NIFTY", "SENSEX"],
        "nifty_cached": streamer.chains["NIFTY"] is not None,
        "sensex_cached": streamer.chains["SENSEX"] is not None,
        "nifty_source": streamer.chains["NIFTY"].get("source") if streamer.chains["NIFTY"] else None,
        "sensex_source": streamer.chains["SENSEX"].get("source") if streamer.chains["SENSEX"] else None,
    }

@app.get("/api/expiries")
async def get_expiries(symbol: str = Query("NIFTY")):
    chain = streamer.chains.get(symbol)
    if chain:
        return {"symbol": symbol, "expiries": chain.get("all_expiries", [])}
    if symbol == "NIFTY":
        exp = streamer.nse_fetcher.get_expiries()
        return {"symbol": symbol, "expiries": exp}
    else:
        return {"symbol": symbol, "expiries": streamer.bse_fetcher.cached_expiries}

@app.get("/api/history")
async def get_history(symbol: str = Query("NIFTY"), interval: str = Query("1s")):
    bars = streamer.synthetic_engine.get_history(symbol, interval=interval)
    return {"symbol": symbol, "interval": interval, "bars": bars}

# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await streamer.register(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "SET_CONFIG":
                await streamer.update_client_config(websocket, data)
    except WebSocketDisconnect:
        streamer.unregister(websocket)
    except Exception:
        streamer.unregister(websocket)

# Mount frontend static directory
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# PWA & Static Endpoints
@app.get("/manifest.json")
@app.get("/manifest.webmanifest")
async def serve_manifest():
    manifest_path = os.path.join(static_dir, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/manifest+json")
    return JSONResponse({"error": "manifest not found"}, status_code=404)

@app.get("/sw.js")
async def serve_service_worker():
    sw_path = os.path.join(static_dir, "sw.js")
    if os.path.exists(sw_path):
        return FileResponse(
            sw_path,
            media_type="application/javascript",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        )
    return JSONResponse({"error": "service worker not found"}, status_code=404)

@app.get("/favicon.ico")
async def serve_favicon():
    fav_path = os.path.join(static_dir, "favicon.ico")
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/x-icon")
    return Response(status_code=204)

@app.api_route("/", methods=["GET", "HEAD"])
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"message": "ZeroSyN Synthetic Future Backend Running"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)
