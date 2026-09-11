import unittest
from backend.synthetic import SyntheticEngine

class TestSyntheticEngine(unittest.TestCase):
    def setUp(self):
        self.engine = SyntheticEngine()

    def test_put_call_parity_synthetic_future(self):
        # Strike = 23300, CE = 125.50, PE = 110.00
        # F_syn = 23300 + 125.50 - 110.00 = 23315.50
        dummy_chain = {
            "symbol": "NIFTY",
            "spot": 23310.0,
            "strikes": {
                23300.0: {
                    "strike": 23300.0,
                    "CE": {"ltp": 125.50, "bid": 125.0, "ask": 126.0},
                    "PE": {"ltp": 110.00, "bid": 109.5, "ask": 110.5},
                }
            }
        }
        res = self.engine.compute_synthetic_future(dummy_chain, target_strike=23300.0, calc_mode="ltp")
        self.assertEqual(res["synthetic_future"], 23315.50)
        # Basis = 23315.50 - 23310.0 = 5.50
        self.assertEqual(res["basis"], 5.50)
        self.assertEqual(res["atm_strike"], 23300.0)

    def test_mid_price_calculation(self):
        # CE bid = 100, ask = 102 => mid = 101
        # PE bid = 80, ask = 82 => mid = 81
        # K = 23000 => F_syn = 23000 + 101 - 81 = 23020
        dummy_chain = {
            "symbol": "NIFTY",
            "spot": 23015.0,
            "strikes": {
                23000.0: {
                    "strike": 23000.0,
                    "CE": {"ltp": 105.0, "bid": 100.0, "ask": 102.0},
                    "PE": {"ltp": 75.0, "bid": 80.0, "ask": 82.0},
                }
            }
        }
        res = self.engine.compute_synthetic_future(dummy_chain, target_strike=23000.0, calc_mode="mid")
        self.assertEqual(res["synthetic_future"], 23020.0)
        self.assertEqual(res["basis"], 5.0)

    def test_find_atm_strike(self):
        strikes = [23100.0, 23150.0, 23200.0, 23250.0, 23300.0]
        self.assertEqual(self.engine.find_atm_strike(23212.0, strikes), 23200.0)
        self.assertEqual(self.engine.find_atm_strike(23245.0, strikes), 23250.0)

    def test_candlestick_aggregation(self):
        t0 = 1000
        # Tick 1: price 23300
        bars = self.engine.update_candle("NIFTY", 23300.0, 23300.0, 0.0, current_timestamp=t0)
        self.assertEqual(bars["1s"]["open"], 23300.0)
        self.assertEqual(bars["1s"]["high"], 23300.0)
        self.assertEqual(bars["1s"]["low"], 23300.0)
        self.assertEqual(bars["1s"]["close"], 23300.0)

        # Tick 2 at same second: price 23310
        bars2 = self.engine.update_candle("NIFTY", 23310.0, 23305.0, 5.0, current_timestamp=t0)
        self.assertEqual(bars2["1s"]["high"], 23310.0)
        self.assertEqual(bars2["1s"]["close"], 23310.0)
        self.assertEqual(bars2["1s"]["volume"], 2)

        # Tick 3 at next second: price 23305
        bars3 = self.engine.update_candle("NIFTY", 23305.0, 23302.0, 3.0, current_timestamp=t0 + 1)
        self.assertEqual(bars3["1s"]["open"], 23305.0)
        self.assertEqual(bars3["1s"]["close"], 23305.0)

if __name__ == "__main__":
    unittest.main()
