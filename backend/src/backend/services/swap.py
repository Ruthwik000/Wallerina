"""0x Swap API client (AllowanceHolder flow).

Quotes come from ``GET /swap/allowance-holder/quote``. Two rules from 0x's
documentation are enforced by ``services/execution.py`` rather than trusted to
the response:

* allowances go only to the AllowanceHolder contract, never to the Settler
  contract a swap may be routed through;
* native tokens (ETH, POL) are sold as ``NATIVE_TOKEN`` and need no allowance.
"""

from __future__ import annotations

from backend.core.config import get_settings
from backend.services.http import UpstreamError, get_client

PROVIDER = "0x"

# AllowanceHolder on Cancun-hardfork chains, which include Ethereum, Base,
# Arbitrum and Polygon.
ALLOWANCE_HOLDER = "0x0000000000001fF3684f28c67538d4D072C22734"
NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


class SwapUnavailable(RuntimeError):
    """No 0x API key is configured. The message is safe to show to the user."""


async def get_quote(
    *,
    chain_id: int,
    sell_token: str,
    buy_token: str,
    sell_amount: int,
    taker: str,
    slippage_bps: int,
) -> dict:
    settings = get_settings()
    if not settings.zeroex_api_key:
        raise SwapUnavailable(
            "Execution needs ZEROEX_API_KEY on the backend (from dashboard.0x.org): quotes come from the 0x Swap API."
        )

    response = await get_client().get(
        f"{settings.zeroex_base_url.rstrip('/')}/swap/allowance-holder/quote",
        params={
            "chainId": chain_id,
            "sellToken": sell_token,
            "buyToken": buy_token,
            "sellAmount": str(sell_amount),
            "taker": taker,
            "slippageBps": slippage_bps,
        },
        headers={"0x-api-key": settings.zeroex_api_key, "0x-version": "v2"},
    )

    if response.status_code != 200:
        try:
            message = response.json().get("message") or response.text
        except ValueError:
            message = response.text
        raise UpstreamError(
            PROVIDER, f"quote returned {response.status_code}: {str(message)[:200]}", response.status_code
        )

    return response.json()
