"""
getABG Strategy: Early-Momentum Screener with switchable exits.

Entry (reconstructed from Documentation.docx — the original .py was empty):
  Additive directional score; go LONG when net score >= +6.
    MACD : +3 line crosses ABOVE signal | +2 hist turns up while < 0 (early turn)
           -3 / -2 symmetric for bearish
    RSI  : +/-1 on a 50-line cross
    9 EMA: +/-1 for close above / below the 9 EMA
    Volume (magnitude, signed by direction): +3 if vol>2x 20d avg, +2 if >1.5x
    Squeeze release (directional via breakout): +2 if a BB-inside-KC squeeze in the
           last 3 bars releases with a band breakout (up=bullish, down=bearish)

Exits — pick one via VARIATION:
  "A" : MACD negative crossover  OR  RSI falling back below 70 after exceeding 70
  "B" : daily close below the 55 EMA
Optional initial stop via USE_ATR_STOP: exit if low <= entry - 2*ATR(at entry).

To run the 4 configs, set the two constants below and run run_backtest.py each time:
  (VARIATION, USE_ATR_STOP) in {("A",False),("A",True),("B",False),("B",True)}

ASSUMPTIONS (flag for refinement): scoring weights/thresholds and the cross-vs-
position choices are inferred from the docs and isolated as constants for tuning.
Entry fills on the signal bar (platform convention, matching ma_crossover.py).
"""

import math


class Strategy:

    METADATA = {
        "name": "Early Momentum Screener",
        "description": "Additive momentum score entry; exit Variation A (MACD/RSI) or B (55 EMA).",
        "type": "momentum",
    }

    # ── config (edit to switch configs) ──────────────────────────────
    VARIATION = "A"          # "A" or "B"
    USE_ATR_STOP = False     # True adds an initial entry - 2*ATR stop
    ATR_STOP_MULT = 2.0

    # ── tunable strategy constants ───────────────────────────────────
    SCORE_THRESHOLD = 6
    POSITION_SIZE_PCT = 0.95
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    EMA_FAST, EMA_SLOW, EMA_SIGNAL = 12, 26, 9
    EMA_SHORT, EMA_TREND = 9, 55
    BB_PERIOD, BB_STD = 20, 2.0
    KC_PERIOD, KC_MULT = 20, 1.5
    VOL_MA = 20
    SQUEEZE_LOOKBACK = 3
    WARMUP = 60              # bars before any signal (lets EMA55/RSI settle)

    def on_init(self, params: dict):
        self.tickers = params.get("tickers", [])
        self.s = {}                 # per-ticker rolling state
        self.entry_atr = {}         # ATR captured at entry, per ticker

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _ema(prev, price, n):
        if prev is None:
            return price
        k = 2.0 / (n + 1.0)
        return prev + k * (price - prev)

    def _new_state(self):
        return {
            "n": 0,
            "closes": [], "trs": [], "vols": [],
            "prev_close": None,
            "ema9": None, "ema55": None,
            "ema12": None, "ema26": None, "macd_sig": None,
            "rsi_ag": None, "rsi_al": None,           # Wilder avg gain/loss
            "prev_rsi": None, "prev_line": None, "prev_sig": None,
            "prev_hist": None,
            "squeeze_hist": [],                        # recent squeeze_on flags
            "was70": False,
        }

    def _update_indicators(self, st, o, h, l, c, v):
        # True range
        if st["prev_close"] is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - st["prev_close"]), abs(l - st["prev_close"]))
        st["trs"].append(tr)
        st["closes"].append(c)
        st["vols"].append(v)

        # EMAs
        st["ema9"] = self._ema(st["ema9"], c, self.EMA_SHORT)
        st["ema55"] = self._ema(st["ema55"], c, self.EMA_TREND)
        st["ema12"] = self._ema(st["ema12"], c, self.EMA_FAST)
        st["ema26"] = self._ema(st["ema26"], c, self.EMA_SLOW)
        macd_line = st["ema12"] - st["ema26"]
        st["macd_sig"] = self._ema(st["macd_sig"], macd_line, self.EMA_SIGNAL)
        macd_hist = macd_line - st["macd_sig"]

        # Wilder RSI
        if st["prev_close"] is not None:
            change = c - st["prev_close"]
            gain = max(change, 0.0)
            loss = max(-change, 0.0)
            if st["rsi_ag"] is None:
                st["rsi_ag"], st["rsi_al"] = gain, loss
            else:
                a = 1.0 / self.RSI_PERIOD
                st["rsi_ag"] = st["rsi_ag"] + a * (gain - st["rsi_ag"])
                st["rsi_al"] = st["rsi_al"] + a * (loss - st["rsi_al"])
            if st["rsi_al"] == 0:
                rsi = 100.0
            else:
                rs = st["rsi_ag"] / st["rsi_al"]
                rsi = 100.0 - 100.0 / (1.0 + rs)
        else:
            rsi = None

        # ATR (Wilder)
        if st.get("atr") is None:
            st["atr"] = tr
        else:
            st["atr"] = st["atr"] + (1.0 / self.ATR_PERIOD) * (tr - st["atr"])

        # Bollinger + Keltner over trailing windows
        squeeze_on = False
        if len(st["closes"]) >= self.BB_PERIOD:
            window = st["closes"][-self.BB_PERIOD:]
            mean = sum(window) / self.BB_PERIOD
            var = sum((x - mean) ** 2 for x in window) / self.BB_PERIOD
            sd = math.sqrt(var)
            bb_up, bb_lo = mean + self.BB_STD * sd, mean - self.BB_STD * sd
            atr_kc = sum(st["trs"][-self.KC_PERIOD:]) / self.KC_PERIOD
            kc_up, kc_lo = mean + self.KC_MULT * atr_kc, mean - self.KC_MULT * atr_kc
            squeeze_on = (bb_up < kc_up) and (bb_lo > kc_lo)
            st["bb_up"], st["bb_lo"] = bb_up, bb_lo
        else:
            st["bb_up"], st["bb_lo"] = None, None
        st["squeeze_hist"].append(squeeze_on)

        st["prev_close"] = c
        st["n"] += 1
        return macd_line, st["macd_sig"], macd_hist, rsi

    def _score(self, st, o, c, macd_line, macd_sig, macd_hist, rsi):
        # MACD points
        macd_pts = 0
        if st["prev_line"] is not None:
            cross_up = macd_line > macd_sig and st["prev_line"] <= st["prev_sig"]
            cross_dn = macd_line < macd_sig and st["prev_line"] >= st["prev_sig"]
            turn_up = macd_hist < 0 and st["prev_hist"] is not None and macd_hist > st["prev_hist"]
            turn_dn = macd_hist > 0 and st["prev_hist"] is not None and macd_hist < st["prev_hist"]
            if cross_up:
                macd_pts = 3
            elif cross_dn:
                macd_pts = -3
            elif turn_up:
                macd_pts = 2
            elif turn_dn:
                macd_pts = -2

        # RSI 50 cross
        rsi_pts = 0
        if rsi is not None and st["prev_rsi"] is not None:
            if rsi > 50 and st["prev_rsi"] <= 50:
                rsi_pts = 1
            elif rsi < 50 and st["prev_rsi"] >= 50:
                rsi_pts = -1

        # price vs 9 EMA
        ema_pts = 1 if c > st["ema9"] else -1

        # volume magnitude
        vol_pts = 0
        if len(st["vols"]) >= self.VOL_MA:
            vma = sum(st["vols"][-self.VOL_MA:]) / self.VOL_MA
            v = st["vols"][-1]
            if v > 2.0 * vma:
                vol_pts = 3
            elif v > 1.5 * vma:
                vol_pts = 2

        # squeeze release (directional via breakout)
        sq_signed = 0
        if st["bb_up"] is not None:
            recent = any(st["squeeze_hist"][-(self.SQUEEZE_LOOKBACK + 1):-1]) \
                if len(st["squeeze_hist"]) > 1 else False
            if recent and c > st["bb_up"]:
                sq_signed = 2
            elif recent and c < st["bb_lo"]:
                sq_signed = -2

        core = macd_pts + rsi_pts + ema_pts
        if core > 0:
            direction = 1
        elif core < 0:
            direction = -1
        else:
            direction = 1 if c >= o else -1

        return core + sq_signed + direction * vol_pts

    # ── main loop ────────────────────────────────────────────────────
    def on_tick(self, timestamp, market_state, portfolio_state):
        orders = []
        equity = portfolio_state["total_equity"]
        open_pos = {p["ticker"]: p for p in portfolio_state["open_positions"]}

        for ticker, bar in market_state.items():
            o, h = bar["open"], bar["high"]
            l, c, v = bar["low"], bar["close"], bar["volume"]

            if ticker not in self.s:
                self.s[ticker] = self._new_state()
            st = self.s[ticker]

            macd_line, macd_sig, macd_hist, rsi = self._update_indicators(st, o, h, l, c, v)

            in_pos = ticker in open_pos
            warm = st["n"] >= self.WARMUP

            if in_pos:
                exit_now = False
                if rsi is not None and rsi >= 70:
                    st["was70"] = True

                if self.USE_ATR_STOP:
                    entry_price = open_pos[ticker]["entry_price"]
                    eatr = self.entry_atr.get(ticker)
                    if eatr is not None and l <= entry_price - self.ATR_STOP_MULT * eatr:
                        exit_now = True

                if not exit_now:
                    if self.VARIATION == "A":
                        macd_neg = (st["prev_line"] is not None
                                    and macd_line < macd_sig
                                    and st["prev_line"] >= st["prev_sig"])
                        rsi_roll = st["was70"] and rsi is not None and rsi < 70
                        exit_now = macd_neg or rsi_roll
                    else:  # "B"
                        exit_now = c < st["ema55"]

                if exit_now:
                    orders.append({"ticker": ticker, "action": "SELL",
                                   "quantity": open_pos[ticker]["qty"],
                                   "order_type": "MARKET"})
                    st["was70"] = False
                    self.entry_atr.pop(ticker, None)

            elif warm:
                score = self._score(st, o, c, macd_line, macd_sig, macd_hist, rsi)
                if score >= self.SCORE_THRESHOLD:
                    qty = round((equity * self.POSITION_SIZE_PCT) / c, 2)
                    if qty > 0:
                        orders.append({"ticker": ticker, "action": "BUY",
                                       "quantity": qty, "order_type": "MARKET"})
                        self.entry_atr[ticker] = st["atr"]
                        st["was70"] = rsi is not None and rsi >= 70

            # store prev values for next tick's cross detection
            st["prev_line"], st["prev_sig"] = macd_line, macd_sig
            st["prev_hist"], st["prev_rsi"] = macd_hist, rsi

        return orders
