import time
import re
import datetime
import logging
import random
from typing import Dict, List, Optional, Any
from curl_cffi import requests

logger = logging.getLogger("fetcher")
logger.setLevel(logging.INFO)

class NSEFetcher:
    def __init__(self):
        self.session: Optional[requests.Session] = None
        self.last_cookie_time = 0
        self.cached_expiries: List[str] = []
        self.cached_chain: Dict[str, Any] = {}
        self.last_fetch_time = 0
        self.error_count = 0

    def _init_session(self):
        try:
            self.session = requests.Session(impersonate="chrome120")
            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
            }
            self.session.get("https://www.nseindia.com", headers=headers, timeout=12)
            self.session.get("https://www.nseindia.com/option-chain", headers=headers, timeout=12)
            self.last_cookie_time = time.time()
            self.error_count = 0
            logger.info("NSE session initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing NSE session: {e}")
            self.session = None

    def _ensure_session(self):
        if self.session is None or (time.time() - self.last_cookie_time > 300):
            self._init_session()

    def get_expiries(self, symbol="NIFTY") -> List[str]:
        self._ensure_session()
        if not self.session:
            return self.cached_expiries

        try:
            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "accept": "application/json, text/plain, */*",
                "referer": "https://www.nseindia.com/option-chain",
            }
            url = f"https://www.nseindia.com/api/option-chain-contract-info?symbol={symbol}"
            res = self.session.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                expiries = data.get("expiryDates", [])
                if expiries:
                    self.cached_expiries = expiries
                    return expiries
            elif res.status_code in (401, 403):
                self._init_session()
        except Exception as e:
            logger.error(f"Error getting NSE expiries: {e}")
            self.error_count += 1
            if self.error_count > 3:
                self.session = None

        return self.cached_expiries

    def get_option_chain(self, symbol="NIFTY", expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        self._ensure_session()
        expiries = self.get_expiries(symbol)
        if not expiries:
            return None

        selected_expiry = expiry if (expiry and expiry in expiries) else expiries[0]

        try:
            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "accept": "application/json, text/plain, */*",
                "referer": "https://www.nseindia.com/option-chain",
            }
            url = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={symbol}&expiry={selected_expiry}"
            res = self.session.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                rec = data.get("records", {})
                spot = float(rec.get("underlyingValue") or 0.0)
                timestamp = rec.get("timestamp") or datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S")

                raw_strikes = data.get("filtered", {}).get("data") or rec.get("data", [])
                strikes_map: Dict[float, Dict[str, Any]] = {}

                for row in raw_strikes:
                    strike = float(row.get("strikePrice") or 0.0)
                    if strike <= 0:
                        continue
                    ce = row.get("CE")
                    pe = row.get("PE")

                    ce_info = None
                    if ce:
                        ce_info = {
                            "ltp": float(ce.get("lastPrice") or 0.0),
                            "bid": float(ce.get("buyPrice1") or 0.0),
                            "ask": float(ce.get("sellPrice1") or 0.0),
                            "change": float(ce.get("change") or 0.0),
                            "pChange": float(ce.get("pChange") or 0.0),
                            "iv": float(ce.get("impliedVolatility") or 0.0),
                            "oi": int(ce.get("openInterest") or 0),
                            "volume": int(ce.get("totalTradedVolume") or 0)
                        }

                    pe_info = None
                    if pe:
                        pe_info = {
                            "ltp": float(pe.get("lastPrice") or 0.0),
                            "bid": float(pe.get("buyPrice1") or 0.0),
                            "ask": float(pe.get("sellPrice1") or 0.0),
                            "change": float(pe.get("change") or 0.0),
                            "pChange": float(pe.get("pChange") or 0.0),
                            "iv": float(pe.get("impliedVolatility") or 0.0),
                            "oi": int(pe.get("openInterest") or 0),
                            "volume": int(pe.get("totalTradedVolume") or 0)
                        }

                    strikes_map[strike] = {
                        "strike": strike,
                        "CE": ce_info,
                        "PE": pe_info
                    }

                result = {
                    "symbol": symbol,
                    "spot": spot,
                    "timestamp": timestamp,
                    "selected_expiry": selected_expiry,
                    "all_expiries": expiries,
                    "strikes": strikes_map,
                    "source": "NSE_LIVE"
                }
                self.cached_chain[selected_expiry] = result
                self.last_fetch_time = time.time()
                return result
            elif res.status_code in (401, 403):
                self._init_session()
        except Exception as e:
            logger.error(f"Error fetching NSE option chain: {e}")

        if selected_expiry in self.cached_chain:
            return self.cached_chain[selected_expiry]
        return None


class BSEFetcher:
    def __init__(self):
        self.session: requests.Session = requests.Session(impersonate="chrome120")
        self.cached_expiries: List[str] = []
        self.cached_chain: Dict[str, Any] = {}
        self.last_fetch_time = 0
        self.cached_spot = 0.0

    def _fetch_spot(self) -> float:
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "accept": "application/json, text/plain, */*",
            "referer": "https://www.bseindia.com/",
        }

        # 1. Primary: Direct official BSE Sensex ticker endpoint
        try:
            url = "https://api.bseindia.com/BseIndiaAPI/api/IndexSensexData1/w"
            r = self.session.get(url, headers=headers, timeout=6)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    val = float(data.get("LatestVal") or data.get("PrevClose") or 0.0)
                    if val > 0:
                        self.cached_spot = val
                        return val
        except Exception as e:
            logger.debug(f"IndexSensexData1 spot fetch attempt: {e}")

        # 2. Fallback: BSE Sensex Graph Data endpoint
        try:
            url_fallback = "https://api.bseindia.com/BseIndiaAPI/api/SensexGraphData/w?index=16&flag=0&sector=&seriesid=R&frd=null&tod=null"
            r = self.session.get(url_fallback, headers=headers, timeout=6)
            if r.status_code == 200:
                raw = r.json()
                if isinstance(raw, str) and "#@#" in raw:
                    parts = raw.split("#@#")
                    meta = json.loads(parts[0])
                    if isinstance(meta, list) and len(meta) > 0:
                        val = float(meta[0].get("LatestVal") or meta[0].get("PreClose") or 0.0)
                        if val > 0:
                            self.cached_spot = val
                            return val
        except Exception as e:
            logger.error(f"Error fetching BSE spot from fallback: {e}")

        return self.cached_spot

    def get_option_chain(self, symbol="SENSEX", expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # Fast return from cache if recently fetched (< 2.5s)
        if expiry and expiry in self.cached_chain and (time.time() - self.last_fetch_time < 2.5):
            return self.cached_chain[expiry]

        spot = self._fetch_spot()

        try:
            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "accept": "application/json, text/plain, */*",
                "referer": "https://www.bseindia.com/",
            }
            url = "https://api.bseindia.com/BseIndiaAPI/api/EquityDerivaties_home/w?CallPut=&SeriesType=&StrategyID="
            res = self.session.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                table = data.get("Table", [])

                expiries_set = set()
                expiry_data: Dict[str, Dict[float, Dict[str, Any]]] = {}

                for row in table:
                    series = row.get("Series_Name", "")
                    if not series.startswith("SENSEX"):
                        continue

                    raw_exp = row.get("End_TimeStamp")
                    if not raw_exp:
                        continue
                    try:
                        dt = datetime.datetime.fromisoformat(raw_exp.split("T")[0])
                        exp_str = dt.strftime("%d-%b-%Y")
                    except Exception:
                        exp_str = raw_exp[:10]

                    expiries_set.add(exp_str)
                    if exp_str not in expiry_data:
                        expiry_data[exp_str] = {}

                    strike = float(row.get("Strike_Price") or 0.0)
                    if strike <= 0:
                        continue

                    if strike not in expiry_data[exp_str]:
                        expiry_data[exp_str][strike] = {"strike": strike, "CE": None, "PE": None}

                    cp = row.get("Call_Put")
                    opt_info = {
                        "ltp": float(row.get("LastTradeRate") or 0.0),
                        "bid": float(row.get("BestBidRate1") or 0.0),
                        "ask": float(row.get("BestOfferRate1") or 0.0),
                        "change": float(row.get("Change") or 0.0),
                        "pChange": float(row.get("ChangePerc") or 0.0),
                        "iv": 0.0,
                        "oi": int(row.get("OI") or 0),
                        "volume": int(row.get("Volume") or 0)
                    }

                    if cp == "CE":
                        expiry_data[exp_str][strike]["CE"] = opt_info
                    elif cp == "PE":
                        expiry_data[exp_str][strike]["PE"] = opt_info

                sorted_expiries = sorted(
                    list(expiries_set),
                    key=lambda x: datetime.datetime.strptime(x, "%d-%b-%Y") if "-" in x else x
                )
                self.cached_expiries = sorted_expiries

                if not sorted_expiries:
                    return None

                selected_expiry = expiry if (expiry and expiry in sorted_expiries) else sorted_expiries[0]

                # Fallback spot from Put-Call parity if spot <= 0
                if spot <= 0 and expiry_data.get(selected_expiry):
                    parity_estimates = []
                    for k, row in expiry_data[selected_expiry].items():
                        ce = row.get("CE")
                        pe = row.get("PE")
                        if ce and pe and ce.get("ltp", 0) > 0 and pe.get("ltp", 0) > 0:
                            parity_estimates.append(k + ce["ltp"] - pe["ltp"])
                    if parity_estimates:
                        parity_estimates.sort()
                        spot = round(parity_estimates[len(parity_estimates) // 2], 2)

                timestamp_now = datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S")

                # Cache data for ALL expiries parsed from this response
                for exp_item in sorted_expiries:
                    self.cached_chain[exp_item] = {
                        "symbol": "SENSEX",
                        "spot": spot,
                        "timestamp": timestamp_now,
                        "selected_expiry": exp_item,
                        "expiry": exp_item,
                        "all_expiries": sorted_expiries,
                        "strikes": expiry_data.get(exp_item, {}),
                        "source": "BSE_LIVE"
                    }

                self.last_fetch_time = time.time()
                return self.cached_chain.get(selected_expiry)
        except Exception as e:
            logger.error(f"Error fetching BSE option chain: {e}")

        if expiry and expiry in self.cached_chain:
            return self.cached_chain[expiry]
        elif self.cached_chain:
            first_k = next(iter(self.cached_chain))
            return self.cached_chain[first_k]
        return None


class MarketSimulator:
    """Provides smooth, realistic 1-second micro-ticks using Put-Call parity dynamics."""
    def __init__(self):
        self.sim_state = {
            "NIFTY": {
                "spot": 23292.0,
                "step": 50.0,
            },
            "SENSEX": {
                "spot": 74500.0,
                "step": 100.0,
            }
        }

    def generate_tick(self, base_chain: Optional[Dict[str, Any]], symbol="NIFTY") -> Dict[str, Any]:
        state = self.sim_state.get(symbol, self.sim_state["NIFTY"])
        if base_chain and base_chain.get("spot", 0) > 0:
            state["spot"] = base_chain["spot"]

        drift = random.gauss(0, 0.8 if symbol == "NIFTY" else 2.5)
        state["spot"] = round(state["spot"] + drift, 2)
        step = state["step"]
        atm_strike = round(state["spot"] / step) * step

        if base_chain and base_chain.get("strikes"):
            strikes = base_chain["strikes"]
            atm_row = strikes.get(atm_strike) or strikes.get(float(atm_strike))
            if atm_row and atm_row.get("CE") and atm_row.get("PE"):
                atm_row["CE"]["ltp"] = max(0.05, round(atm_row["CE"]["ltp"] + drift * 0.5, 2))
                atm_row["PE"]["ltp"] = max(0.05, round(atm_row["PE"]["ltp"] - drift * 0.5, 2))
                base_chain["spot"] = state["spot"]
                base_chain["timestamp"] = datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S")
                return base_chain

        expiries = base_chain.get("all_expiries", ["15-Sep-2026", "22-Sep-2026"]) if base_chain else ["15-Sep-2026", "22-Sep-2026"]
        synthetic_strikes = {}
        for i in range(-15, 16):
            k = atm_strike + i * step
            moneyness = (state["spot"] - k)
            ce_val = max(5.0, round(120.0 + moneyness * 0.55 + random.uniform(-0.5, 0.5), 2))
            pe_val = max(5.0, round(120.0 - moneyness * 0.45 + random.uniform(-0.5, 0.5), 2))
            synthetic_strikes[k] = {
                "strike": k,
                "CE": {
                    "ltp": ce_val,
                    "bid": round(ce_val - 0.2, 2),
                    "ask": round(ce_val + 0.2, 2),
                    "change": round(drift * 0.5, 2),
                    "pChange": round(drift * 0.4, 2),
                    "iv": 14.5,
                    "oi": 50000 + abs(i) * 3000,
                    "volume": 200000 + abs(i) * 10000
                },
                "PE": {
                    "ltp": pe_val,
                    "bid": round(pe_val - 0.2, 2),
                    "ask": round(pe_val + 0.2, 2),
                    "change": round(-drift * 0.5, 2),
                    "pChange": round(-drift * 0.4, 2),
                    "iv": 15.2,
                    "oi": 48000 + abs(i) * 2800,
                    "volume": 180000 + abs(i) * 9000
                }
            }

        return {
            "symbol": symbol,
            "spot": state["spot"],
            "timestamp": datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S"),
            "selected_expiry": expiries[0],
            "all_expiries": expiries,
            "strikes": synthetic_strikes,
            "source": "SIMULATION"
        }
