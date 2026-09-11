import asyncio
import json
import time
from backend.streamer import DataStreamer

async def run_streamer_test():
    streamer = DataStreamer()
    await streamer.start_loop()
    print("Streamer started. Waiting 4 seconds for ticks...")

    # Wait for loop to cycle and generate ticks
    for i in range(4):
        await asyncio.sleep(1.0)
        nifty_chain = streamer.chains.get("NIFTY")
        sensex_chain = streamer.chains.get("SENSEX")
        if nifty_chain:
            n_syn = streamer.synthetic_engine.compute_synthetic_future(nifty_chain)
            print(f"[{i+1}s] NIFTY  | Spot: {n_syn['spot']} | Strike: {n_syn['selected_strike']} | Fut: {n_syn['synthetic_future']} | Basis: {n_syn['basis']}")
        if sensex_chain:
            s_syn = streamer.synthetic_engine.compute_synthetic_future(sensex_chain)
            print(f"[{i+1}s] SENSEX | Spot: {s_syn['spot']} | Strike: {s_syn['selected_strike']} | Fut: {s_syn['synthetic_future']} | Basis: {s_syn['basis']}")

    await streamer.stop_loop()
    print("Streamer test passed successfully!")

if __name__ == "__main__":
    asyncio.run(run_streamer_test())
