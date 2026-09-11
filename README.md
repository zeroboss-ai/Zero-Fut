# ZeroSyN - Real-Time Synthetic Future Terminal (NIFTY & SENSEX)

An institutional-grade, single-page real-time **Synthetic Future Terminal** for **NIFTY 50 (NSE)** and **SENSEX (BSE)** options.

It ingests live option chain contracts directly from official exchange endpoints, calculates the Synthetic Future every second using **Put-Call Parity**, and streams real-time candlesticks and ticks into a high-performance **TradingView Lightweight Chart**.

---

## The Mathematics of Synthetic Futures

### 1. Put-Call Parity Formula
In arbitrage-free markets, a synthetic long future position is created by buying a call option and selling a put option with the same strike price ($K$) and expiration date:

$$F_{syn} = K + C_K - P_K$$

Where:
* **$K$**: Strike Price (typically the At-The-Money strike $K_{ATM}$ closest to Spot)
* **$C_K$**: Call Option Last Traded Price (LTP) or Mid-Price $\frac{\text{Bid} + \text{Ask}}{2}$
* **$P_K$**: Put Option Last Traded Price (LTP) or Mid-Price $\frac{\text{Bid} + \text{Ask}}{2}$

### 2. Synthetic Basis (Premium / Discount)
$$\text{Basis} = F_{syn} - \text{Spot}$$

* **$\text{Basis} > 0$ (Premium)**: Synthetic Future is trading above the Spot Index (bullish carry cost / positive sentiment).
* **$\text{Basis} < 0$ (Discount)**: Synthetic Future is trading below Spot (bearish sentiment / dividend impact).

---

## Features

* **Official Exchange Live Data**:
  * **NSE NIFTY**: Fetches active expiries from `option-chain-contract-info` and live strikes from `option-chain-v3` with Chrome TLS session impersonation via `curl_cffi`.
  * **BSE SENSEX**: Fetches real-time SENSEX options from `EquityDerivaties_home` and Spot Index from `SensexGraphData`.
* **1-Second Streaming Engine**:
  * Exchange poller queries exchanges at an optimal 2.5s cadence to prevent Akamai/WAF rate-limits and IP blocks.
  * Real-time WebSocket server streams second-by-second ticks and OHLC candlestick bars to the frontend.
  * Includes an intelligent fallback simulator when market is closed (nights, weekends, holidays) or testing offline.
* **TradingView Lightweight Charts**:
  * **Main Chart**: Real-time 1s, 5s, 1m Candlestick bars or smooth Line/Area view.
  * **Spot Overlay**: Dashed amber line comparing the underlying Spot Index directly against the Synthetic Future.
  * **Basis Sub-Pane**: Real-time histogram showing Basis premium (green) and discount (red).
* **Terminal Controls**:
  * **Symbol Switcher**: Instant 1-click toggle between `NIFTY 50` (NSE) and `SENSEX` (BSE).
  * **Dynamic Expiry Picker**: Automatically loads all valid exchange expiration dates.
  * **Auto ATM vs. Custom Strike**: Defaults to auto-tracking ATM as spot price shifts, with instant manual lock on any strike.
  * **Calculation Mode**: Toggle between **LTP** and **Bid/Ask Mid-Price**.
  * **Strike Matrix Table**: Interactive table showing ATM ± 8 strikes with Calls, Puts, individual Synthetic Futures, and Basis. Click any row to lock calculation to that strike.
  * **Audio Tick Feedback**: Web Audio API synthesizer for acoustic tick pulses (toggleable).

---

## Quick Start

### 1. Launch Terminal
Run the one-click launcher from the project root:

```bash
python run.py
```

This automatically starts the FastAPI server and opens `http://127.0.0.1:8000` in your default browser.

### 2. Manual Start (Alternative)
```bash
python -m backend.main
```
Then navigate to:
[http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## Project Structure

```
Zero SyN/
├── backend/
│   ├── __init__.py
│   ├── fetcher.py        # NSE & BSE live option chain fetchers & market simulator
│   ├── synthetic.py      # Put-Call parity calculations & 1s OHLC candlestick aggregator
│   ├── streamer.py       # WebSocket broadcaster & 1-second tick loop
│   └── main.py           # FastAPI app serving REST, WebSocket, and static assets
├── static/
│   ├── index.html        # Single-page terminal UI
│   ├── styles.css        # OLED dark-mode financial styling
│   ├── app.js            # TradingView chart integration & WebSocket client
│   └── lib/
│       └── lightweight-charts.standalone.production.js  # Bundled local chart library
├── tests/
│   ├── test_synthetic.py    # Unit tests for Put-Call Parity and OHLC logic
│   ├── test_server.py       # FastAPI REST & WebSocket integration tests
│   └── test_live_stream.py  # 1-second live tick stream verification test
├── run.py                # One-click launch script
└── README.md
```

---

## Running Automated Tests

Run the test suite:

```bash
# Test Put-Call Parity calculations
python -m unittest tests/test_synthetic.py

# Test Server REST endpoints and WebSocket handshakes
python -m unittest tests/test_server.py

# Test 1-second live tick stream
python -m tests.test_live_stream
```
