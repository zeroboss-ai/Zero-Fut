import asyncio
import json
import logging
import time
from typing import Set, Dict, Any, Optional
from fastapi import WebSocket

from backend.fetcher import NSEFetcher, BSEFetcher, MarketSimulator
from backend.synthetic import SyntheticEngine

logger = logging.getLogger("streamer")
logger.setLevel(logging.INFO)

class DataStreamer:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.client_settings: Dict[WebSocket, Dict[str, Any]] = {}
        
        self.nse_fetcher = NSEFetcher()
        self.bse_fetcher = BSEFetcher()
        self.simulator = MarketSimulator()
        self.synthetic_engine = SyntheticEngine()
        
        # In-memory latest chains
        self.chains: Dict[str, Optional[Dict[str, Any]]] = {
            "NIFTY": None,
            "SENSEX": None
        }
        self.last_exchange_fetch_time: Dict[str, float] = {
            "NIFTY": 0.0,
            "SENSEX": 0.0
        }
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def register(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        self.client_settings[websocket] = {
            "symbol": "NIFTY",
            "expiry": None,
            "strike": "auto",
            "calc_mode": "ltp",
            "interval": "1s"
        }
        # Send initial snapshot and history
        await self.send_initial_state(websocket)

    def unregister(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        self.client_settings.pop(websocket, None)

    async def update_client_config(self, websocket: WebSocket, new_config: Dict[str, Any]):
        if websocket in self.client_settings:
            self.client_settings[websocket].update(new_config)
            await self.send_initial_state(websocket)

    async def get_or_fetch_chain(self, symbol: str, expiry: Optional[str] = None) -> Dict[str, Any]:
        cache_key = f"{symbol}_{expiry}" if expiry else symbol
        if cache_key in self.chains and self.chains[cache_key]:
            return self.chains[cache_key]

        loop = asyncio.get_running_loop()
        live_res = await loop.run_in_executor(None, self._fetch_exchange_sync, symbol, expiry)
        if live_res and live_res.get("spot", 0) > 0 and len(live_res.get("strikes", {})) > 0:
            actual_exp = live_res.get("selected_expiry") or expiry
            self.chains[f"{symbol}_{actual_exp}"] = live_res
            self.chains[cache_key] = live_res
            if not self.chains.get(symbol):
                self.chains[symbol] = live_res
            return live_res

        fallback = self.chains.get(symbol)
        if fallback:
            return fallback
        return self.simulator.generate_tick(None, symbol=symbol)

    async def send_initial_state(self, websocket: WebSocket):
        cfg = self.client_settings.get(websocket, {})
        sym = cfg.get("symbol", "NIFTY")
        expiry = cfg.get("expiry")
        interval = cfg.get("interval", "1s")
        target_strike = None if cfg.get("strike") == "auto" else float(cfg.get("strike"))
        calc_mode = cfg.get("calc_mode", "ltp")

        chain = await self.get_or_fetch_chain(sym, expiry)
        syn_data = self.synthetic_engine.compute_synthetic_future(
            chain, target_strike=target_strike, calc_mode=calc_mode
        )
        
        # Unique series key per expiry for chart continuity
        series_key = f"{sym}_{syn_data.get('expiry', '')}" if syn_data.get('expiry') else sym
        self.synthetic_engine.prefill_history(series_key, syn_data["synthetic_future"], syn_data["spot"])
        history_bars = self.synthetic_engine.get_history(series_key, interval=interval)

        payload = {
            "type": "SNAPSHOT",
            "config": cfg,
            "synthetic": syn_data,
            "history": history_bars,
            "timestamp": int(time.time())
        }
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception as e:
            logger.error(f"Error sending snapshot: {e}")

    def _fetch_exchange_sync(self, symbol: str, expiry: Optional[str] = None):
        try:
            if symbol == "NIFTY":
                return self.nse_fetcher.get_option_chain("NIFTY", expiry=expiry)
            elif symbol == "SENSEX":
                return self.bse_fetcher.get_option_chain("SENSEX", expiry=expiry)
        except Exception as e:
            logger.error(f"Error fetching from exchange {symbol}: {e}")
        return None

    async def start_loop(self):
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._streaming_loop())

    async def stop_loop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()

    async def _streaming_loop(self):
        logger.info("Starting 1-second streaming tick engine...")
        loop = asyncio.get_running_loop()

        while self.is_running:
            start_t = time.time()
            now = time.time()

            # Identify all active (symbol, expiry) targets needed by connected clients
            needed_targets = set()
            for ws, cfg in self.client_settings.items():
                needed_targets.add((cfg.get("symbol", "NIFTY"), cfg.get("expiry")))
            
            # Ensure base symbols are present
            needed_targets.add(("NIFTY", None))
            needed_targets.add(("SENSEX", None))

            for sym, exp in needed_targets:
                cache_key = f"{sym}_{exp}" if exp else sym
                last_fetch = self.last_exchange_fetch_time.get(cache_key, 0.0)

                if (now - last_fetch) >= 2.5:
                    self.last_exchange_fetch_time[cache_key] = now
                    live_res = await loop.run_in_executor(None, self._fetch_exchange_sync, sym, exp)
                    if live_res and live_res.get("spot", 0) > 0 and len(live_res.get("strikes", {})) > 0:
                        actual_exp = live_res.get("selected_expiry") or exp
                        self.chains[f"{sym}_{actual_exp}"] = live_res
                        self.chains[cache_key] = live_res
                        if exp is None or not self.chains.get(sym):
                            self.chains[sym] = live_res

                # Smoothly simulate micro-tick between exchange updates
                curr_chain = self.chains.get(cache_key) or self.chains.get(sym)
                if curr_chain:
                    simulated_tick = self.simulator.generate_tick(curr_chain, symbol=sym)
                    self.chains[cache_key] = simulated_tick

            # Broadcast 1-second ticks to all connected clients based on their preferences
            if self.active_connections:
                now_ts = int(time.time())
                for ws in list(self.active_connections):
                    try:
                        cfg = self.client_settings.get(ws, {})
                        sym = cfg.get("symbol", "NIFTY")
                        exp = cfg.get("expiry")
                        interval = cfg.get("interval", "1s")
                        target_strike = None if cfg.get("strike") == "auto" else float(cfg.get("strike"))
                        calc_mode = cfg.get("calc_mode", "ltp")

                        cache_key = f"{sym}_{exp}" if exp else sym
                        chain = self.chains.get(cache_key) or self.chains.get(sym)
                        if not chain:
                            continue

                        syn_data = self.synthetic_engine.compute_synthetic_future(
                            chain, target_strike=target_strike, calc_mode=calc_mode
                        )

                        series_key = f"{sym}_{syn_data.get('expiry', '')}" if syn_data.get('expiry') else sym
                        current_bars = self.synthetic_engine.update_candle(
                            series_key, syn_data["synthetic_future"], syn_data["spot"], syn_data["basis"], current_timestamp=now_ts
                        )

                        tick_payload = {
                            "type": "TICK",
                            "symbol": sym,
                            "expiry": syn_data.get("expiry"),
                            "synthetic": syn_data,
                            "bar": current_bars.get(interval),
                            "timestamp": now_ts
                        }
                        await ws.send_text(json.dumps(tick_payload))
                    except Exception as e:
                        logger.warning(f"Error broadcasting to client: {e}")
                        self.unregister(ws)

            # Sleep remaining time to maintain accurate 1.0 second rhythm
            elapsed = time.time() - start_t
            sleep_time = max(0.05, 1.0 - elapsed)
            await asyncio.sleep(sleep_time)
