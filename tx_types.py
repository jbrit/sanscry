from dataclasses import dataclass
from typing import TypedDict, Literal, Optional, Callable

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

