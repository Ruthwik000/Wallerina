"""Trusted asset registry.

Specification section 9 requires that classification does not rely on token
names: a spam token can call itself anything it likes, and mislabelling one as
a stablecoin would corrupt the entire allocation decision. Classification is
therefore driven by contract address on a known network, and anything absent
from the registry is reported as ``unknown`` rather than being guessed at.
"""

from __future__ import annotations

from enum import StrEnum


class AssetClass(StrEnum):
    STABLECOIN = "stablecoin"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


# Alchemy echoes Polygon back as "matic-mainnet" while accepting
# "polygon-mainnet" on the way in. Normalise to one spelling.
NETWORK_ALIASES: dict[str, str] = {
    "polygon-mainnet": "matic-mainnet",
}

NETWORK_LABELS: dict[str, str] = {
    "eth-mainnet": "Ethereum",
    "base-mainnet": "Base",
    "arb-mainnet": "Arbitrum",
    "matic-mainnet": "Polygon",
    "opt-mainnet": "Optimism",
}

# Native (gas) token per network. Alchemy returns these with a null contract
# address and null metadata, so symbol and decimals have to come from here.
NATIVE_TOKENS: dict[str, tuple[str, str, int]] = {
    # network: (symbol, name, decimals)
    "eth-mainnet": ("ETH", "Ethereum", 18),
    "base-mainnet": ("ETH", "Ethereum", 18),
    "arb-mainnet": ("ETH", "Ethereum", 18),
    "opt-mainnet": ("ETH", "Ethereum", 18),
    "matic-mainnet": ("POL", "Polygon", 18),
}

# Fiat-referenced stablecoins, keyed by (network, lowercased contract address).
STABLECOINS: dict[tuple[str, str], str] = {
    # Ethereum
    ("eth-mainnet", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"): "USDC",
    ("eth-mainnet", "0xdac17f958d2ee523a2206206994597c13d831ec7"): "USDT",
    ("eth-mainnet", "0x6b175474e89094c44da98b954eedeac495271d0f"): "DAI",
    ("eth-mainnet", "0x6c3ea9036406852006290770bedfcaba0e23a0e8"): "PYUSD",
    ("eth-mainnet", "0x4c9edd5852cd905f086c759e8383e09bff1e68b3"): "USDe",
    ("eth-mainnet", "0x853d955acef822db058eb8505911ed77f175b99e"): "FRAX",
    ("eth-mainnet", "0x8e870d67f660d95d5be530380d0ec0bd388289e1"): "USDP",
    ("eth-mainnet", "0x0000000000085d4780b73119b644ae5ecd22b376"): "TUSD",
    # Base
    ("base-mainnet", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): "USDC",
    ("base-mainnet", "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"): "USDbC",
    ("base-mainnet", "0x50c5725949a6f0c72e6c4a641f24049a917db0cb"): "DAI",
    ("base-mainnet", "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2"): "USDT",
    # Arbitrum
    ("arb-mainnet", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"): "USDC",
    ("arb-mainnet", "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8"): "USDC.e",
    ("arb-mainnet", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"): "USDT",
    ("arb-mainnet", "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1"): "DAI",
    # Polygon
    ("matic-mainnet", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"): "USDC",
    ("matic-mainnet", "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"): "USDC.e",
    ("matic-mainnet", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"): "USDT",
    ("matic-mainnet", "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063"): "DAI",
    # Optimism
    ("opt-mainnet", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"): "USDC",
    ("opt-mainnet", "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58"): "USDT",
    ("opt-mainnet", "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1"): "DAI",
}

# Major volatile assets we are willing to name. Wrapped and liquid-staked
# variants are included because they track their underlying closely enough to
# be treated as the same exposure.
MAJOR_VOLATILE: dict[tuple[str, str], str] = {
    ("eth-mainnet", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"): "WETH",
    ("eth-mainnet", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"): "WBTC",
    ("eth-mainnet", "0xae7ab96520de3a18e5e111b5eaab095312d7fe84"): "stETH",
    ("eth-mainnet", "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0"): "wstETH",
    ("eth-mainnet", "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"): "UNI",
    ("eth-mainnet", "0x514910771af9ca656af840dff83e8264ecf986ca"): "LINK",
    ("eth-mainnet", "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0"): "MATIC",
    ("eth-mainnet", "0x4200000000000000000000000000000000000042"): "OP",
    ("base-mainnet", "0x4200000000000000000000000000000000000006"): "WETH",
    ("base-mainnet", "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22"): "cbETH",
    ("arb-mainnet", "0x82af49447d8a07e3bd95bd0d56f35241523fbab1"): "WETH",
    ("arb-mainnet", "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f"): "WBTC",
    ("arb-mainnet", "0x912ce59144191c1204e64559fe8253a0e49e6548"): "ARB",
    ("matic-mainnet", "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619"): "WETH",
    ("matic-mainnet", "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270"): "WMATIC",
}

# Symbol used when asking Alchemy's price endpoints for history, where the
# registry symbol differs from the tradable one.
PRICE_SYMBOL_OVERRIDES: dict[str, str] = {
    "WETH": "ETH",
    "stETH": "ETH",
    "wstETH": "ETH",
    "cbETH": "ETH",
    "WBTC": "BTC",
    "WMATIC": "POL",
    "MATIC": "POL",
    "USDC.e": "USDC",
    "USDbC": "USDC",
}

# Spam airdrops frequently encode instructions in the token symbol. Any of
# these fragments disqualifies a token regardless of its reported price.
SPAM_SYMBOL_FRAGMENTS: tuple[str, ...] = (
    "http", "www.", ".com", ".org", ".net", ".io", ".eu", ".cc", ".xyz",
    "claim", "visit", "reward", "airdrop", "t.me", "@", "bonus", "voucher",
)

MAX_REASONABLE_SYMBOL_LENGTH = 16


def normalise_network(network: str) -> str:
    """Collapse Alchemy's network aliases onto a single spelling."""
    return NETWORK_ALIASES.get(network, network)


def network_label(network: str) -> str:
    return NETWORK_LABELS.get(normalise_network(network), network)


def classify(network: str, contract_address: str | None) -> tuple[AssetClass, str | None]:
    """Classify a holding by network and contract address.

    Returns the class and the registry's canonical symbol, which is ``None``
    for assets the registry does not recognise.
    """
    network = normalise_network(network)

    if contract_address is None:
        native = NATIVE_TOKENS.get(network)
        if native is None:
            return AssetClass.UNKNOWN, None
        return AssetClass.VOLATILE, native[0]

    key = (network, contract_address.lower())

    if symbol := STABLECOINS.get(key):
        return AssetClass.STABLECOIN, symbol

    if symbol := MAJOR_VOLATILE.get(key):
        return AssetClass.VOLATILE, symbol

    return AssetClass.UNKNOWN, None


def is_spam_symbol(symbol: str | None) -> bool:
    """Heuristic rejection of advertising disguised as a token symbol."""
    if not symbol:
        return False

    lowered = symbol.lower()
    if any(fragment in lowered for fragment in SPAM_SYMBOL_FRAGMENTS):
        return True

    return len(symbol) > MAX_REASONABLE_SYMBOL_LENGTH


def price_symbol(symbol: str) -> str:
    """Map a registry symbol onto the symbol Alchemy prices it under."""
    return PRICE_SYMBOL_OVERRIDES.get(symbol, symbol)
