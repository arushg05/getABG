
import yfinance as yf
import pandas as pd
import numpy as np

class Strategy:
    METADATA = {
        "name": "SAR 2-Lot Bollinger Strategy",
        "description": "Bollinger Bands + Parabolic SAR dual-lot volatility breakout fade.",
        "type": "hybrid",
    }

    def __init__(self):
        # ==========================================
        # 1. THE SETUP ROOM
        # Define strategy info and assets to trade
        # ==========================================
        self.metadata = {
            "name": "SAR 2-Lot Bollinger Strategy",
            "version": "1.0"
        }

        # Universe
        self.universe = ["AAPL", "NVDA", "RELIANCE.NS"]

        # Strategy Parameters
        self.threshold_pct = 0.004
        self.bb_period = 20
        self.bb_std = 2.0

        # ==========================================
        # 2. THE MEMORY ROOM
        # ==========================================
        self.positions = {
            ticker: {
                "lot1": 0,
                "lot2": 0
            }
            for ticker in self.universe
        }

        self.history = {
            ticker: pd.DataFrame()
            for ticker in self.universe
        }

        self.lot2_active = {
            ticker: False
            for ticker in self.universe
        }

    def on_init(self, params: dict):
        # Override universe if provided by host
        if "tickers" in params:
            self.universe = params["tickers"]
            # Reinitialize positions and history for the correct universe
            self.positions = {
                ticker: {
                    "lot1": 0,
                    "lot2": 0
                }
                for ticker in self.universe
            }
            self.history = {
                ticker: pd.DataFrame()
                for ticker in self.universe
            }
            self.lot2_active = {
                ticker: False
                for ticker in self.universe
            }

    def calculate_indicators(self, df):
        # Normalize column names to lowercase to prevent casing mismatches
        df.columns = [c.lower() for c in df.columns]

        # ===== CUSTOM SAR =====
        df['ema5_h'] = df['high'].ewm(span=5, adjust=False).mean()
        df['ema5_c'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema5_l'] = df['low'].ewm(span=5, adjust=False).mean()

        df['sma5_ema5_h'] = df['ema5_h'].rolling(window=5).mean()
        df['sma5_ema5_c'] = df['ema5_c'].rolling(window=5).mean()
        df['sma5_ema5_l'] = df['ema5_l'].rolling(window=5).mean()

        df['sar'] = (
            df['sma5_ema5_h'] +
            df['sma5_ema5_c'] +
            df['sma5_ema5_l']
        ) / 3

        # ===== BOLLINGER BANDS =====
        df['bb_mid'] = df['close'].rolling(window=self.bb_period).mean()
        df['bb_std'] = df['close'].rolling(window=self.bb_period).std()

        df['bb_upper'] = (
            df['bb_mid'] +
            self.bb_std * df['bb_std']
        )

        df['bb_lower'] = (
            df['bb_mid'] -
            self.bb_std * df['bb_std']
        )

        return df


    def on_tick(self, timestamp, market_state, portfolio_state):

        # ==========================================
        # 3. THE EXECUTION ROOM
        # ==========================================
        orders = []

        for ticker in self.universe:

            if ticker not in market_state:
                continue

            current_tick = market_state[ticker]

            close_price = current_tick.get('close', current_tick.get('Close'))
            high_price = current_tick.get('high', current_tick.get('High'))
            low_price = current_tick.get('low', current_tick.get('Low'))

            # ======================================
            # UPDATE MEMORY
            # ======================================
            self.history[ticker] = pd.concat([
                self.history[ticker],
                pd.DataFrame([current_tick])
            ], ignore_index=True)

            # Keep rolling buffer
            if len(self.history[ticker]) > 100:
                self.history[ticker] = self.history[ticker].iloc[-100:]

            # Need enough candles
            if len(self.history[ticker]) < 30:
                continue

            # ======================================
            # CALCULATE INDICATORS
            # ======================================
            df = self.calculate_indicators(
                self.history[ticker].copy()
            )

            latest = df.iloc[-1]

            sar = latest['sar']
            bb_upper = latest['bb_upper']
            bb_lower = latest['bb_lower']

            if pd.isna(sar) or pd.isna(bb_upper):
                continue

            upper_thresh = sar * (1 + self.threshold_pct)
            lower_thresh = sar * (1 - self.threshold_pct)

            lot1_pos = self.positions[ticker]["lot1"]
            lot2_pos = self.positions[ticker]["lot2"]

            # ======================================
            # LOT 1 LOGIC
            # ======================================
            new_pos = lot1_pos
            lot1_flip = False

            if lot1_pos == 1 and low_price <= lower_thresh:
                new_pos = -1
                lot1_flip = True

            elif lot1_pos == -1 and high_price >= upper_thresh:
                new_pos = 1
                lot1_flip = True

            elif close_price > sar and lot1_pos != 1:
                new_pos = 1
                lot1_flip = True

            elif close_price < sar and lot1_pos != -1:
                new_pos = -1
                lot1_flip = True

            # ======================================
            # EXECUTE LOT1 REVERSAL
            # ======================================
            if lot1_flip:

                # Close Existing Position
                if lot1_pos == 1:
                    orders.append({
                        "ticker": ticker,
                        "action": "SELL",
                        "quantity": 100,
                        "type": "MARKET",
                        "tag": "LOT1_EXIT_LONG"
                    })

                elif lot1_pos == -1:
                    orders.append({
                        "ticker": ticker,
                        "action": "BUY",
                        "quantity": 100,
                        "type": "MARKET",
                        "tag": "LOT1_EXIT_SHORT"
                    })

                # Open New Position
                if new_pos == 1:
                    orders.append({
                        "ticker": ticker,
                        "action": "BUY",
                        "quantity": 100,
                        "type": "MARKET",
                        "tag": "LOT1_LONG"
                    })

                elif new_pos == -1:
                    orders.append({
                        "ticker": ticker,
                        "action": "SELL",
                        "quantity": 100,
                        "type": "MARKET",
                        "tag": "LOT1_SHORT"
                    })

                self.positions[ticker]["lot1"] = new_pos

            # ======================================
            # LOT2 FOLLOW LOGIC
            # ======================================
            if lot1_flip:

                # Exit Existing Lot2
                if lot2_pos == 1:
                    orders.append({
                        "ticker": ticker,
                        "action": "SELL",
                        "quantity": 100,
                        "type": "MARKET",
                        "tag": "LOT2_EXIT_LONG"
                    })

                elif lot2_pos == -1:
                    orders.append({
                        "ticker": ticker,
                        "action": "BUY",
                        "quantity": 100,
                        "type": "MARKET",
                        "tag": "LOT2_EXIT_SHORT"
                    })

                # Follow Lot1 Direction
                if new_pos == 1:
                    orders.append({
                        "ticker": ticker,
                        "action": "BUY",
                        "quantity": 100,
                        "type": "MARKET",
                        "tag": "LOT2_LONG"
                    })

                elif new_pos == -1:
                    orders.append({
                        "ticker": ticker,
                        "action": "SELL",
                        "quantity": 100,
                        "type": "MARKET",
                        "tag": "LOT2_SHORT"
                    })

                self.positions[ticker]["lot2"] = new_pos

            # ======================================
            # LOT2 BB EXIT LOGIC
            # ======================================
            lot2_pos = self.positions[ticker]["lot2"]

            if lot2_pos == 1 and close_price >= bb_upper:

                orders.append({
                    "ticker": ticker,
                    "action": "SELL",
                    "quantity": 100,
                    "type": "MARKET",
                    "tag": "LOT2_BB_EXIT_LONG"
                })

                self.positions[ticker]["lot2"] = 0

            elif lot2_pos == -1 and close_price <= bb_lower:

                orders.append({
                    "ticker": ticker,
                    "action": "BUY",
                    "quantity": 100,
                    "type": "MARKET",
                    "tag": "LOT2_BB_EXIT_SHORT"
                })

                self.positions[ticker]["lot2"] = 0

        return orders
