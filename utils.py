import aiohttp
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tx_types import TransactionResponse

async def get_block(rpc_url, slot):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBlock",
        "params": [
            slot,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "transactionDetails": "full",
                "rewards": False
            }
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(rpc_url, json=payload) as response:
            if response.status != 200:
                raise Exception(f"Failed to fetch block data: {await response.text()}")

            block_data = await response.json()
            if "error" in block_data:
                raise Exception(f"RPC Error: {block_data['error']['message']}")
            
    return block_data["result"]

def get_signer(tx_resp: 'TransactionResponse') -> str:
    return next(acc["pubkey"] for acc in tx_resp["transaction"]["message"]["accountKeys"] if acc["signer"])