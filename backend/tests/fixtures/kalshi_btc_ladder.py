"""Recorded from the live Kalshi API on 2026-09-13.

``GET /trade-api/v2/markets?event_ticker=KXBTCD-26SEP1817`` — a BTC strike
ladder, kept verbatim in the field shapes the exchange actually returns:
prices as decimal *strings* in dollars, sizes with an ``_fp`` suffix, and
``status: "active"``. Coding to the documented integer-cents shape would make
every probability a hundredth of its real value.
"""

from __future__ import annotations

EVENT_TICKER = "KXBTCD-26SEP1817"
EXPIRATION = "2026-09-18T21:00:00Z"


def _market(strike: float, bid: str, ask: str, volume: str, open_interest: str) -> dict:
    return {
        "ticker": f"{EVENT_TICKER}-T{strike}",
        "event_ticker": EVENT_TICKER,
        "title": f"BTC price on Sep 18, 2026 at 5pm EDT?",
        "yes_sub_title": f"${strike + 0.01:,.0f}+",
        "strike_type": "greater",
        "floor_strike": strike,
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
        "volume_fp": volume,
        "open_interest_fp": open_interest,
        "expiration_time": EXPIRATION,
        "status": "active",
        "market_type": "binary",
    }


# (floor_strike, yes_bid, yes_ask, volume, open_interest) exactly as quoted.
LADDER = [
    _market(66999.99, "0.9800", "1.0000", "0.00", "0.00"),
    _market(69499.99, "0.9600", "0.9700", "26768.73", "26768.73"),
    _market(70499.99, "0.9400", "0.9500", "37522.14", "37317.00"),
    _market(71999.99, "0.9000", "0.9200", "7719.87", "5334.50"),
    _market(72999.99, "0.8700", "0.8800", "3343.18", "2783.69"),
    _market(73999.99, "0.8000", "0.8100", "925.19", "638.81"),
    _market(74999.99, "0.6900", "0.7000", "9310.51", "7048.65"),
    _market(75999.99, "0.5900", "0.6000", "5529.22", "4245.78"),
    _market(76499.99, "0.5200", "0.5300", "12444.06", "10365.64"),
    _market(76999.99, "0.4600", "0.4800", "17207.21", "10518.37"),
    _market(77499.99, "0.4000", "0.4100", "16019.19", "7820.07"),
    _market(77999.99, "0.3400", "0.3500", "10186.62", "7500.33"),
    _market(78499.99, "0.2800", "0.2900", "5011.04", "3032.04"),
    _market(78999.99, "0.2400", "0.2600", "6679.67", "4810.32"),
    _market(79499.99, "0.2000", "0.2200", "2589.79", "1553.26"),
    _market(79999.99, "0.1700", "0.1800", "13239.01", "11850.60"),
    _market(80499.99, "0.1300", "0.1500", "4350.89", "3596.68"),
    _market(80999.99, "0.1100", "0.1200", "2096.27", "1736.84"),
    _market(81499.99, "0.0900", "0.1000", "3981.55", "3719.11"),
    _market(81999.99, "0.0700", "0.0800", "5620.32", "4812.74"),
    _market(82999.99, "0.0500", "0.0600", "13441.13", "13341.13"),
    _market(83999.99, "0.0300", "0.0500", "19304.00", "19204.00"),
    # Deep out of the money: no bid, no volume, no information.
    _market(86999.99, "0.0000", "0.0300", "0.00", "0.00"),
]

RESPONSE = {"cursor": "", "markets": LADDER}
