from dataclasses import dataclass
from typing import TypedDict, Literal, Optional, Callable
from utils import get_signer

class RegularInstruction(TypedDict):
        accounts: list[str]
        data: str
        programId: str
        stackHeight: Optional[int]

class ParsedInstruction(TypedDict):
        parsed: dict
        program: str
        programId: str
        stackHeight: Optional[int]

Instruction = RegularInstruction | ParsedInstruction

class TransactionMeta(TypedDict):
    class InnerInstruction(TypedDict):
        index: int
        instructions: list[Instruction]

    computeUnitsConsumed: int
    err: Optional[dict]
    fee: int
    innerInstructions: list[InnerInstruction]
    logMessages: list[str]
    postBalances: list[int]
    postTokenBalances: list[int]
    preBalances: list[int]
    preTokenBalances: list[int]

class TransactionMessage(TypedDict):
    class AccountKey(TypedDict):
        pubkey: str
        signer: bool
        source: Literal['transaction']
        writable: bool

    accountKeys: list[AccountKey]
    instructions: list[Instruction]
    recentBlockhash: str

class Transaction(TypedDict):
    message: TransactionMessage
    signatures: list[str]

class TransactionResponse(TypedDict):
    blockTime: int
    meta: TransactionMeta
    slot: int
    transaction: Transaction
    version: Literal['legacy', 0]

@dataclass
class PotentialSwap:
    exchange_instruction: RegularInstruction
    transfer_instructions: list[ParsedInstruction]
    top_level_ix: RegularInstruction

    @property
    def is_top_level(self) -> bool:
        return self.exchange_instruction["programId"] == self.top_level_ix["programId"]

@dataclass
class PotentialSwapWithTxContext:
    tx_resp: TransactionResponse
    potential_swap: PotentialSwap
    number_of_tx_swaps: int

@dataclass
class ExchangeInfo:
    pool_index: int
    is_valid_swap_data: Callable[[bytes], bool]

@dataclass
class PoolInfo:
    id: str
    token_a: str
    token_b: str
    token_a_vault: str
    token_b_vault: str

@dataclass
class TransferInfo:
    mint: Optional[str]
    amount: int
    source: str
    destination: str

    @staticmethod
    def from_ix(ix: ParsedInstruction) -> "TransferInfo":
        if ix["parsed"]["type"] == "transferChecked":
            return TransferInfo(
                mint=ix["parsed"]["info"]["mint"],
                amount=int(ix["parsed"]["info"]["tokenAmount"]["amount"]),
                source=ix["parsed"]["info"]["source"],
                destination=ix["parsed"]["info"]["destination"]
            )
        elif ix["program"] == "spl-token":
            return TransferInfo(
                mint=None,
                amount=int(ix["parsed"]["info"]["amount"]),
                source=ix["parsed"]["info"]["source"],
                destination=ix["parsed"]["info"]["destination"]
            )
        elif ix["program"] == "system":
            return TransferInfo(
                mint="So11111111111111111111111111111111111111112",
                amount=int(ix["parsed"]["info"]["lamports"]),
                source=ix["parsed"]["info"]["source"],
                destination=ix["parsed"]["info"]["destination"]
            )
        else:
            raise Exception(f"Unknown transfer instruction: {ix}")

@dataclass
class PotentialSandwich:
    entry_tx: PotentialSwapWithTxContext
    target_txs: list[PotentialSwapWithTxContext]
    exit_tx: PotentialSwapWithTxContext

    @property
    def dex(self) -> str:
        return self.entry_tx.potential_swap.exchange_instruction["programId"]
    
    @property
    def bot(self) -> str:
        return self.entry_tx.potential_swap.top_level_ix["programId"]

@dataclass
class TargetTx:
    signature: str
    signer: str
    profit_token_amount: int
    targeted_token_amount: int

    @staticmethod
    def from_potential_swap(tx: PotentialSwapWithTxContext, profit_token_vault: str, targeted_token_vault: str) -> "TargetTx":
        transfer_infos = list(map(TransferInfo.from_ix, tx.potential_swap.transfer_instructions))
        if profit_token_vault == transfer_infos[0].source or profit_token_vault == transfer_infos[0].destination:
            profit_token_transfer = transfer_infos[0]
            targeted_token_transfer = transfer_infos[1]
        elif targeted_token_vault == transfer_infos[0].source or targeted_token_vault == transfer_infos[0].destination:
            profit_token_transfer = transfer_infos[1]
            targeted_token_transfer = transfer_infos[0]
        else:
            raise Exception(f"Unknown transfer instruction: {tx.potential_swap.transfer_instructions}")
        return TargetTx(
            signature=tx.tx_resp["transaction"]["signatures"][0],
            signer=get_signer(tx.tx_resp),
            profit_token_amount=profit_token_transfer.amount,
            targeted_token_amount=targeted_token_transfer.amount
        )

@dataclass
class AttackerTx:
    signature: str
    profit_token_amount: int
    targeted_token_amount: int
    jito_tip: int
    priority_fee: int

    @staticmethod
    def from_potential_swap(tx: PotentialSwapWithTxContext, profit_token_vault: str, targeted_token_vault: str, jito_tip_accounts: set[str]) -> "AttackerTx":
        transfer_infos = list(map(TransferInfo.from_ix, tx.potential_swap.transfer_instructions))
        if profit_token_vault == transfer_infos[0].source or profit_token_vault == transfer_infos[0].destination:
            profit_token_transfer = transfer_infos[0]
            targeted_token_transfer = transfer_infos[1]
        elif targeted_token_vault == transfer_infos[0].source or targeted_token_vault == transfer_infos[0].destination:
            profit_token_transfer = transfer_infos[1]
            targeted_token_transfer = transfer_infos[0]
        else:
            raise Exception(f"Unknown transfer instruction: {tx.potential_swap.transfer_instructions}")
        return AttackerTx(
            signature=tx.tx_resp["transaction"]["signatures"][0],
            profit_token_amount=profit_token_transfer.amount,
            targeted_token_amount=targeted_token_transfer.amount,
            jito_tip=AttackerTx.get_jito_tip(tx, jito_tip_accounts),
            priority_fee=0
        )
    
    @staticmethod
    def get_jito_tip(tx: PotentialSwapWithTxContext, jito_tip_accounts: set[str]) -> int:
        for ix in tx.tx_resp["transaction"]["message"]["instructions"]:
            if (parsed_ix := ix.get("parsed")) and parsed_ix["type"] == "transfer" and parsed_ix["info"]["destination"] in jito_tip_accounts:
                return int(parsed_ix["info"]["lamports"])
        for inner_ix in tx.tx_resp["meta"]["innerInstructions"]:
            for ix in inner_ix["instructions"]:
                if (parsed_ix := ix.get("parsed")) and parsed_ix["type"] == "transfer" and parsed_ix["info"]["destination"] in jito_tip_accounts:
                    return int(parsed_ix["info"]["lamports"])
        return 0

@dataclass
class Sandwich:
    block: int
    block_time: int
    dex: str
    pool: str
    bot: str
    attacker: str
    profit_token: str
    targeted_token: str
    entry_tx: AttackerTx
    target_txs: list[TargetTx]
    exit_tx: AttackerTx


class Exchanges:
    ORCA_WHIRLPOOL_ADDRESS = 'whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc'
    RAYDIUM_CLMM_ADDRESS = 'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK'
    RAYDIUM_LPV4_ADDRESS = '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8'
    METEORA_PP_ADDRESS = 'Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB'
    METEORA_DLMM_ADDRESS = 'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo'
    LIFINITY_V2_ADDRESS = '2wT8Yq49kHgDzXuPxZSaeLaH1qbmGXtEyPy64bL7aD3c'
    RAYDIUM_CPMM_ADDRESS = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'
    SOLFI_ADDRESS = 'SoLFiHG9TfgtdUXUjWAxi3LtvYuFyDLVhBWxdMZxyCe'
    CROPPER_ADDRESS = 'H8W3ctz92svYg6mkn1UtGfu2aQr2fnUFHM1RhScEtQDt'
    OBRIC_ADDRESS = 'obriQD1zbpyLz95G5n7nJe6a4DPjpFwa5XYPoNm113y'
    STABBLE_ADDRESS = 'swapNyd8XiQwJ6ianp9snpu4brUqFxadzvHebnAXjJZ'
    ZEROFI_ADDRESS = 'ZERor4xhbUycZ6gb9ntrhqscUcZmAbQDjEAtCf4hbZY'
    OPENBOOK_V2_ADDRESS = 'opnb2LAfJYbRMAHHvqjCwQxanZn7ReEHp1k81EohpZb'
    PUMP_SWAP_ADDRESS = 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'

EXCHANGE_NAME_MAP = {
    Exchanges.ORCA_WHIRLPOOL_ADDRESS: "orca",
    Exchanges.RAYDIUM_CLMM_ADDRESS: "raydium_clmm",
    Exchanges.RAYDIUM_LPV4_ADDRESS: "raydium_lpv4",
    Exchanges.RAYDIUM_CPMM_ADDRESS: "raydium_cpmm",    
    Exchanges.SOLFI_ADDRESS: "solfi",
    Exchanges.CROPPER_ADDRESS: "cropper",
    Exchanges.OBRIC_ADDRESS: "obric",
    Exchanges.ZEROFI_ADDRESS: "zerofi",
    Exchanges.OPENBOOK_V2_ADDRESS: "openbook_v2",
    Exchanges.METEORA_DLMM_ADDRESS: "meteora_dlmm",
    Exchanges.METEORA_PP_ADDRESS: "meteora_pp",
    Exchanges.LIFINITY_V2_ADDRESS: "lifinity_v2",
    Exchanges.PUMP_SWAP_ADDRESS: "pump_swap",
}

EXCHANGES_INFO = {
    Exchanges.ORCA_WHIRLPOOL_ADDRESS: ExchangeInfo(2, lambda x: True),
    Exchanges.RAYDIUM_CLMM_ADDRESS: ExchangeInfo(2, lambda x: True),
    Exchanges.RAYDIUM_LPV4_ADDRESS: ExchangeInfo(1, lambda x: True),
    Exchanges.METEORA_PP_ADDRESS: ExchangeInfo(0, lambda x: True),
    Exchanges.METEORA_DLMM_ADDRESS: ExchangeInfo(0, lambda x: True),
    Exchanges.LIFINITY_V2_ADDRESS: ExchangeInfo(1, lambda x: True),
    Exchanges.SOLFI_ADDRESS: ExchangeInfo(1, lambda x: True),
    Exchanges.CROPPER_ADDRESS: ExchangeInfo(2, lambda x: True),
    Exchanges.OBRIC_ADDRESS: ExchangeInfo(0, lambda x: True),
    Exchanges.OPENBOOK_V2_ADDRESS: ExchangeInfo(2, lambda x: True),
    Exchanges.ZEROFI_ADDRESS: ExchangeInfo(0, lambda x: True),
    Exchanges.PUMP_SWAP_ADDRESS: ExchangeInfo(0, lambda x: True),
}