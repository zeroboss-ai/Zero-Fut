import time
import datetime
from typing import Dict, List, Optional, Any, Tuple

class SyntheticEngine:
    def __init__(self):
        # Dynamic in-memory historical candle buffers: { series_key: { interval: [ bar_dict ] } }
        self.history: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        # Current open bars: { series_key: { interval: bar_dict } }
        self.current_bars: Dict[str, Dict[str, Optional[Dict[str, Any]]]] = {}
        self.last_prices: Dict[str, float] = {}

    def _ensure_symbol(self, symbol: str):
        if symbol not in self.history:
            self.history[symbol] = {"1s": [], "5s": [], "1m": []}
            self.current_bars[symbol] = {"1s": None, "5s": None, "1m": None}
            self.last_prices[symbol] = 0.0

    def find_atm_strike(self, spot: float, strikes: List[float]) -> float:
        if not strikes:
            return round(spot / 50.0) * 50.0
        return min(strikes, key=lambda k: abs(k - spot))

    def compute_synthetic_future(
        self,
        chain_data: Dict[str, Any],
        target_strike: Optional[float] = None,
        calc_mode: str = "ltp"  # "ltp" or "mid"
    ) -> Dict[str, Any]:
        """
        Computes Put-Call Parity Synthetic Future:
        F_syn = K + C - P
        Basis = F_syn - Spot
        """
        spot = float(chain_data.get("spot") or 0.0)
        strikes_map = chain_data.get("strikes", {})
        all_strikes = sorted([float(k) for k in strikes_map.keys()])

        if not all_strikes:
            # Fallback placeholder
            k = round(spot / 50.0) * 50.0 if spot > 0 else 23300.0
            return {
                "symbol": chain_data.get("symbol", "NIFTY"),
                "spot": spot,
                "atm_strike": k,
                "selected_strike": k,
                "synthetic_future": spot,
                "basis": 0.0,
                "call_price": 0.0,
                "put_price": 0.0,
                "strike_matrix": [],
                "timestamp": chain_data.get("timestamp", "")
            }

        atm_strike = self.find_atm_strike(spot, all_strikes)
        selected_strike = target_strike if (target_strike and target_strike in strikes_map) else atm_strike

        row = strikes_map.get(selected_strike) or strikes_map.get(str(selected_strike)) or {}
        ce = row.get("CE") or {}
        pe = row.get("PE") or {}

        if calc_mode == "mid":
            ce_bid = ce.get("bid", 0.0)
            ce_ask = ce.get("ask", 0.0)
            c_price = (ce_bid + ce_ask) / 2.0 if (ce_bid > 0 and ce_ask > 0) else ce.get("ltp", 0.0)

            pe_bid = pe.get("bid", 0.0)
            pe_ask = pe.get("ask", 0.0)
            p_price = (pe_bid + pe_ask) / 2.0 if (pe_bid > 0 and pe_ask > 0) else pe.get("ltp", 0.0)
        else:
            c_price = ce.get("ltp", 0.0)
            p_price = pe.get("ltp", 0.0)

        # Put-Call Parity: F = K + C - P
        synthetic_fut = round(selected_strike + c_price - p_price, 2)
        basis = round(synthetic_fut - spot, 2)

        # Build Strike Matrix around ATM (ATM ± 8 strikes)
        atm_idx = all_strikes.index(atm_strike) if atm_strike in all_strikes else len(all_strikes)//2
        start_idx = max(0, atm_idx - 8)
        end_idx = min(len(all_strikes), atm_idx + 9)
        matrix = []

        for k in all_strikes[start_idx:end_idx]:
            k_row = strikes_map.get(k) or {}
            k_ce = k_row.get("CE") or {}
            k_pe = k_row.get("PE") or {}
            k_c_ltp = k_ce.get("ltp", 0.0)
            k_p_ltp = k_pe.get("ltp", 0.0)
            k_syn = round(k + k_c_ltp - k_p_ltp, 2) if (k_c_ltp > 0 and k_p_ltp > 0) else 0.0
            k_basis = round(k_syn - spot, 2) if k_syn > 0 else 0.0

            matrix.append({
                "strike": k,
                "is_atm": (k == atm_strike),
                "is_selected": (k == selected_strike),
                "ce_ltp": k_c_ltp,
                "ce_bid": k_ce.get("bid", 0.0),
                "ce_ask": k_ce.get("ask", 0.0),
                "ce_oi": k_ce.get("oi", 0),
                "ce_change": k_ce.get("change", 0.0),
                "pe_ltp": k_p_ltp,
                "pe_bid": k_pe.get("bid", 0.0),
                "pe_ask": k_pe.get("ask", 0.0),
                "pe_oi": k_pe.get("oi", 0),
                "pe_change": k_pe.get("change", 0.0),
                "synthetic_future": k_syn,
                "basis": k_basis
            })

        return {
            "symbol": chain_data.get("symbol", "NIFTY"),
            "spot": spot,
            "atm_strike": atm_strike,
            "selected_strike": selected_strike,
            "all_strikes": all_strikes,
            "synthetic_future": synthetic_fut,
            "basis": basis,
            "call_price": c_price,
            "put_price": p_price,
            "calc_mode": calc_mode,
            "expiry": chain_data.get("selected_expiry", ""),
            "all_expiries": chain_data.get("all_expiries", []),
            "strike_matrix": matrix,
            "source": chain_data.get("source", ""),
            "timestamp": chain_data.get("timestamp", datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S"))
        }

    def update_candle(self, symbol: str, price: float, spot: float, basis: float, current_timestamp: Optional[int] = None) -> Dict[str, Any]:
        """
        Updates candlestick intervals (1s, 5s, 1m) and returns the current bar for each interval.
        """
        self._ensure_symbol(symbol)
        now = current_timestamp or int(time.time())
        intervals = [("1s", 1), ("5s", 5), ("1m", 60)]
        res_bars = {}

        for int_name, int_sec in intervals:
            bucket_time = (now // int_sec) * int_sec
            cur_bar = self.current_bars[symbol][int_name]

            if cur_bar is None or cur_bar["time"] != bucket_time:
                # Close previous bar if exists
                if cur_bar is not None:
                    self.history[symbol][int_name].append(cur_bar)
                    # Limit memory history to 2000 bars
                    if len(self.history[symbol][int_name]) > 2000:
                        self.history[symbol][int_name].pop(0)

                # Start new bar
                cur_bar = {
                    "time": bucket_time,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1,
                    "spot": spot,
                    "basis": basis
                }
            else:
                # Update ongoing bar
                cur_bar["high"] = max(cur_bar["high"], price)
                cur_bar["low"] = min(cur_bar["low"], price)
                cur_bar["close"] = price
                cur_bar["volume"] += 1
                cur_bar["spot"] = spot
                cur_bar["basis"] = basis

            self.current_bars[symbol][int_name] = cur_bar
            res_bars[int_name] = cur_bar

        self.last_prices[symbol] = price
        return res_bars

    def get_history(self, symbol: str, interval: str = "1s") -> List[Dict[str, Any]]:
        self._ensure_symbol(symbol)
        bars = list(self.history[symbol].get(interval, []))
        cur = self.current_bars[symbol].get(interval)
        if cur:
            bars.append(cur)
        return bars

    def prefill_history(self, symbol: str, base_price: float, base_spot: float):
        """Generates past 300 bars of 1s candles so chart opens with meaningful history."""
        self._ensure_symbol(symbol)
        if len(self.history[symbol]["1s"]) > 20:
            return
        
        now = int(time.time())
        p = base_price
        s = base_spot
        bars = []
        for i in range(300, 0, -1):
            t = now - i
            drift = (hash(f"{symbol}-{t}") % 21 - 10) * 0.15
            p = round(p + drift, 2)
            s = round(s + drift * 0.95, 2)
            b = round(p - s, 2)
            high = round(p + abs(drift * 0.4), 2)
            low = round(p - abs(drift * 0.4), 2)
            open_p = round(p - drift * 0.5, 2)
            bars.append({
                "time": t,
                "open": open_p,
                "high": max(open_p, p, high),
                "low": min(open_p, p, low),
                "close": p,
                "volume": 10 + (hash(f"vol-{t}") % 50),
                "spot": s,
                "basis": b
            })
        self.history[symbol]["1s"] = bars
        self.last_prices[symbol] = p
