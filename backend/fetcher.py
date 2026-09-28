import time
import json
import datetime
import logging
import random
from typing import Dict, List, Optional, Any
from curl_cffi import requests

logger = logging.getLogger("fetcher")
logger.setLevel(logging.INFO)


def _iso_to_display(iso_str: str) -> str:
    """Convert 'YYYY-MM-DD' -> 'DD-MMM-YYYY' (e.g. '2026-09-29' -> '29-Sep-2026')."""
    try:
        dt = datetime.datetime.strptime(iso_str.strip(), "%Y-%m-%d")
        return dt.strftime("%d-%b-%Y")
    except Exception:
        return iso_str


def _display_to_iso(disp_str: str) -> str:
    """Convert 'DD-MMM-YYYY' -> 'YYYY-MM-DD' (e.g. '29-Sep-2026' -> '2026-09-29')."""
    try:
        dt = datetime.datetime.strptime(disp_str.strip(), "%d-%b-%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return disp_str


def _parse_groww_strikes(option_chains: List[Dict[str, Any]]) -> Dict[float, Dict[str, Any]]:
    strikes_map: Dict[float, Dict[str, Any]] = {}
    for row in option_chains:
        raw_strike = float(row.get("strikePrice") or 0.0)
        if raw_strike <= 0:
            continue
        strike = round(raw_strike / 100.0, 2)
        if strike.is_integer():
            strike = float(int(strike))

        ce = row.get("callOption")
        pe = row.get("putOption")

        ce_info = None
        if ce:
            ce_ltp = round(float(ce.get("ltp") or 0.0), 2)
            ce_info = {
                "ltp": ce_ltp,
                "bid": ce_ltp,
                "ask": ce_ltp,
                "change": round(float(ce.get("dayChange") or 0.0), 2),
                "pChange": round(float(ce.get("dayChangePerc") or 0.0), 2),
                "iv": 0.0,
                "oi": int(ce.get("openInterest") or 0),
                "volume": int(ce.get("volume") or 0)
            }

        pe_info = None
        if pe:
            pe_ltp = round(float(pe.get("ltp") or 0.0), 2)
            pe_info = {
                "ltp": pe_ltp,
                "bid": pe_ltp,
                "ask": pe_ltp,
                "change": round(float(pe.get("dayChange") or 0.0), 2),
                "pChange": round(float(pe.get("dayChangePerc") or 0.0), 2),
                "iv": 0.0,
                "oi": int(pe.get("openInterest") or 0),
                "volume": int(pe.get("volume") or 0)
            }

        strikes_map[strike] = {
            "strike": strike,
            "CE": ce_info,
            "PE": pe_info
        }
    return strikes_map


class NSEFetcher:
    def __init__(self):
        self.fast_session: requests.Session = requests.Session(impersonate="chrome120")
        self.session: Optional[requests.Session] = None
        self.last_cookie_time = 0
        self.cached_expiries: List[str] = []
        self.cached_chain: Dict[str, Any] = {}
        self.last_fetch_time = 0
        self.cached_spot = 0.0
        self.error_count = 0

    def _fetch_spot(self) -> float:
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "accept": "application/json, text/plain, */*",
        }
        # 1. Primary: Real-time 1-second NSE NIFTY spot endpoint
        try:
            url = "https://groww.in/v1/api/stocks_data/v1/accord_points/exchange/NSE/segment/CASH/latest_indices_ohlc/NIFTY"
            r = self.fast_session.get(url, headers=headers, timeout=4)
            if r.status_code == 200:
                val = float(r.json().get("value") or 0.0)
                if val > 0:
                    self.cached_spot = round(val, 2)
                    return self.cached_spot
        except Exception as e:
            logger.debug(f"Primary NIFTY spot fetch error: {e}")

        # 2. Secondary fallback: Moneycontrol real-time index feed
        try:
            url_mc = "https://priceapi.moneycontrol.com/pricefeed/notapplicable/inidicesindia/in%3BNSX"
            r = self.fast_session.get(url_mc, headers=headers, timeout=4)
            if r.status_code == 200:
                val = float(r.json().get("data", {}).get("pricecurrent") or 0.0)
                if val > 0:
                    self.cached_spot = round(val, 2)
                    return self.cached_spot
        except Exception as e:
            logger.debug(f"Secondary NIFTY spot fetch error: {e}")

        return self.cached_spot

    def get_expiries(self, symbol="NIFTY") -> List[str]:
        if self.cached_expiries:
            return self.cached_expiries
        chain = self.get_option_chain(symbol=symbol)
        if chain and chain.get("all_expiries"):
            return chain["all_expiries"]
        return self.cached_expiries

    def get_option_chain(self, symbol="NIFTY", expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        spot = self._fetch_spot()
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "accept": "application/json, text/plain, */*",
        }

        # 1. Primary: Real-time 1-second option chain feed (50-100ms response, no 60s CDN cache lag)
        try:
            use_custom_expiry = (
                expiry is not None
                and self.cached_expiries
                and expiry in self.cached_expiries
                and expiry != self.cached_expiries[0]
            )

            if use_custom_expiry:
                iso_exp = _display_to_iso(expiry)
                url = f"https://groww.in/v1/api/option_chain_service/v1/option_chain/derivatives/nifty?expiry={iso_exp}"
            else:
                url = "https://groww.in/v1/api/option_chain_service/v1/option_chain/nifty"

            res = self.fast_session.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                oc = data.get("optionChain", {})
                raw_expiries = oc.get("expiryDetailsDto", {}).get("expiryDates", [])
                if raw_expiries:
                    self.cached_expiries = [_iso_to_display(e) for e in raw_expiries]

                expiries = self.cached_expiries
                selected_expiry = expiry if (expiry and expiry in expiries) else (expiries[0] if expiries else "")

                # If caller requested a non-first expiry before cached_expiries was populated, fetch that specific expiry now
                if not use_custom_expiry and expiry and expiries and expiry in expiries and expiry != expiries[0]:
                    iso_exp = _display_to_iso(expiry)
                    url_exp = f"https://groww.in/v1/api/option_chain_service/v1/option_chain/derivatives/nifty?expiry={iso_exp}"
                    res_exp = self.fast_session.get(url_exp, headers=headers, timeout=5)
                    if res_exp.status_code == 200:
                        data = res_exp.json()
                        oc = data.get("optionChain", {})
                        selected_expiry = expiry

                strikes_map = _parse_groww_strikes(oc.get("optionChains", []))
                if strikes_map:
                    if spot <= 0:
                        spot = round(float(data.get("livePrice", {}).get("value") or 0.0), 2)

                    timestamp_now = datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S")
                    result = {
                        "symbol": "NIFTY",
                        "spot": spot,
                        "timestamp": timestamp_now,
                        "selected_expiry": selected_expiry,
                        "expiry": selected_expiry,
                        "all_expiries": expiries,
                        "strikes": strikes_map,
                        "source": "NSE_LIVE"
                    }
                    self.cached_chain[selected_expiry] = result
                    self.last_fetch_time = time.time()
                    return result
        except Exception as e:
            logger.warning(f"Primary NIFTY option chain fetch error: {e}")

        # 2. Fallback: Direct NSE option-chain-v3 API
        return self._get_nse_fallback_chain(symbol, expiry, spot)

    def _init_session(self):
        try:
            self.session = requests.Session(impersonate="chrome120")
            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
            }
            self.session.get("https://www.nseindia.com", headers=headers, timeout=10)
            self.session.get("https://www.nseindia.com/option-chain", headers=headers, timeout=10)
            self.last_cookie_time = time.time()
            self.error_count = 0
        except Exception as e:
            logger.error(f"Error initializing fallback NSE session: {e}")
            self.session = None

    def _ensure_session(self):
        if self.session is None or (time.time() - self.last_cookie_time > 300):
            self._init_session()

    def _get_nse_fallback_chain(self, symbol="NIFTY", expiry: Optional[str] = None, live_spot: float = 0.0) -> Optional[Dict[str, Any]]:
        self._ensure_session()
        if not self.session:
            return self.cached_chain.get(expiry) if expiry in self.cached_chain else next(iter(self.cached_chain.values()), None)

        try:
            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "accept": "application/json, text/plain, */*",
                "referer": "https://www.nseindia.com/option-chain",
            }
            if not self.cached_expiries:
                c_url = f"https://www.nseindia.com/api/option-chain-contract-info?symbol={symbol}"
                c_res = self.session.get(c_url, headers=headers, timeout=8)
                if c_res.status_code == 200:
                    self.cached_expiries = c_res.json().get("expiryDates", [])

            expiries = self.cached_expiries
            if not expiries:
                return None

            selected_expiry = expiry if (expiry and expiry in expiries) else expiries[0]
            url = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={symbol}&expiry={selected_expiry}"
            res = self.session.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                rec = data.get("records", {})
                spot = live_spot if live_spot > 0 else float(rec.get("underlyingValue") or 0.0)
                timestamp = datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S")

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
                    "expiry": selected_expiry,
                    "all_expiries": expiries,
                    "strikes": strikes_map,
                    "source": "NSE_LIVE"
                }
                self.cached_chain[selected_expiry] = result
                self.last_fetch_time = time.time()
                return result
        except Exception as e:
            logger.error(f"Error in NSE fallback option chain: {e}")

        if expiry and expiry in self.cached_chain:
            return self.cached_chain[expiry]
        return next(iter(self.cached_chain.values()), None)


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

        # 1. Primary: Real-time 1-second BSE SENSEX spot endpoint
        try:
            url_groww = "https://groww.in/v1/api/stocks_data/v1/accord_points/exchange/BSE/segment/CASH/latest_indices_ohlc/SENSEX"
            r = self.session.get(url_groww, headers=headers, timeout=4)
            if r.status_code == 200:
                val = float(r.json().get("value") or 0.0)
                if val > 0:
                    self.cached_spot = round(val, 2)
                    return self.cached_spot
        except Exception as e:
            logger.debug(f"Primary SENSEX spot fetch attempt: {e}")

        # 2. Secondary: Direct official BSE Sensex ticker endpoint
        try:
            url = "https://api.bseindia.com/BseIndiaAPI/api/IndexSensexData1/w"
            r = self.session.get(url, headers=headers, timeout=4)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    val = float(data.get("LatestVal") or data.get("PrevClose") or 0.0)
                    if val > 0:
                        self.cached_spot = round(val, 2)
                        return self.cached_spot
        except Exception as e:
            logger.debug(f"IndexSensexData1 spot fetch attempt: {e}")

        # 3. Tertiary: Moneycontrol real-time Sensex feed
        try:
            url_mc = "https://priceapi.moneycontrol.com/pricefeed/notapplicable/inidicesindia/in%3BSEN"
            r = self.session.get(url_mc, headers=headers, timeout=4)
            if r.status_code == 200:
                val = float(r.json().get("data", {}).get("pricecurrent") or 0.0)
                if val > 0:
                    self.cached_spot = round(val, 2)
                    return self.cached_spot
        except Exception as e:
            logger.error(f"Error fetching BSE spot from fallback: {e}")

        return self.cached_spot

    def get_option_chain(self, symbol="SENSEX", expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        spot = self._fetch_spot()
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "accept": "application/json, text/plain, */*",
        }

        # 1. Primary: Real-time 1-second BSE SENSEX option chain feed
        try:
            use_custom_expiry = (
                expiry is not None
                and self.cached_expiries
                and expiry in self.cached_expiries
                and expiry != self.cached_expiries[0]
            )

            if use_custom_expiry:
                iso_exp = _display_to_iso(expiry)
                url = f"https://groww.in/v1/api/option_chain_service/v1/option_chain/derivatives/sp-bse-sensex?expiry={iso_exp}"
            else:
                url = "https://groww.in/v1/api/option_chain_service/v1/option_chain/sp-bse-sensex"

            res = self.session.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                oc = data.get("optionChain", {})
                raw_expiries = oc.get("expiryDetailsDto", {}).get("expiryDates", [])
                if raw_expiries:
                    self.cached_expiries = [_iso_to_display(e) for e in raw_expiries]

                expiries = self.cached_expiries
                selected_expiry = expiry if (expiry and expiry in expiries) else (expiries[0] if expiries else "")

                if not use_custom_expiry and expiry and expiries and expiry in expiries and expiry != expiries[0]:
                    iso_exp = _display_to_iso(expiry)
                    url_exp = f"https://groww.in/v1/api/option_chain_service/v1/option_chain/derivatives/sp-bse-sensex?expiry={iso_exp}"
                    res_exp = self.session.get(url_exp, headers=headers, timeout=5)
                    if res_exp.status_code == 200:
                        data = res_exp.json()
                        oc = data.get("optionChain", {})
                        selected_expiry = expiry

                strikes_map = _parse_groww_strikes(oc.get("optionChains", []))
                if strikes_map:
                    if spot <= 0:
                        spot = round(float(data.get("livePrice", {}).get("value") or 0.0), 2)

                    timestamp_now = datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S")
                    result = {
                        "symbol": "SENSEX",
                        "spot": spot,
                        "timestamp": timestamp_now,
                        "selected_expiry": selected_expiry,
                        "expiry": selected_expiry,
                        "all_expiries": expiries,
                        "strikes": strikes_map,
                        "source": "BSE_LIVE"
                    }
                    self.cached_chain[selected_expiry] = result
                    self.last_fetch_time = time.time()
                    return result
        except Exception as e:
            logger.warning(f"Primary SENSEX option chain fetch error: {e}")

        # 2. Fallback: Direct BSE EquityDerivaties_home endpoint
        try:
            bse_headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "accept": "application/json, text/plain, */*",
                "referer": "https://www.bseindia.com/",
            }
            url = "https://api.bseindia.com/BseIndiaAPI/api/EquityDerivaties_home/w?CallPut=&SeriesType=&StrategyID="
            res = self.session.get(url, headers=bse_headers, timeout=8)
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
            logger.error(f"Error fetching BSE fallback option chain: {e}")

        if expiry and expiry in self.cached_chain:
            return self.cached_chain[expiry]
        elif self.cached_chain:
            first_k = next(iter(self.cached_chain))
            return self.cached_chain[first_k]
        return None


class MarketSimulator:
    """Provides fallback simulation only when live exchange APIs are unreachable."""
    def __init__(self):
        self.sim_state = {
            "NIFTY": {
                "spot": 22850.0,
                "step": 50.0,
            },
            "SENSEX": {
                "spot": 73500.0,
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

        expiries = base_chain.get("all_expiries", ["29-Sep-2026", "06-Oct-2026"]) if base_chain else ["29-Sep-2026", "06-Oct-2026"]
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
