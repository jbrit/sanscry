import asyncio
from config import RPC_URL
from utils import get_block, get_signer
from tx_types import PotentialSwap, TransactionResponse, TransferInfo, Instruction, PotentialSwapWithTxContext, PotentialSandwich, Sandwich, AttackerTx, TargetTx, EXCHANGES_INFO
from db import get_pools_map


transfer_types = {"transfer", "transferChecked"}
def is_transfer(ix: Instruction) -> bool:
    if "parsed" in ix and type(ix["parsed"]) == dict and ix["parsed"]["type"] in transfer_types:
        return True
    return False

def is_transaction_successful(tx_resp: TransactionResponse) -> bool:
    return tx_resp["meta"]["err"] is None

def get_signature(tx_resp: TransactionResponse) -> str:
    return tx_resp["transaction"]["signatures"][0]

def extract_potential_swaps(tx_resp: TransactionResponse) -> list[PotentialSwap]:
    """
        Extract potential swaps from a transaction response.

        NOTE (potential edge case):
        - non_transfer_ix_a:
            - transfer_ix_a
            - transfer_ix_b
            - non_transfer_ix_c
            - transfer_ix_d
            - transfer_ix_e
    """
    potential_swaps: list[PotentialSwap] = []
    for inner_instruction in tx_resp['meta']['innerInstructions']:
        program_ixs = inner_instruction['instructions'].copy()
        program_ixs.insert(0, {
            **tx_resp["transaction"]["message"]["instructions"][inner_instruction['index']],
            "stackHeight": 0
        })
        top_level_ix = program_ixs[0]
        left_ptr, right_ptr = 0, 0
        while left_ptr < len(program_ixs) and right_ptr < len(program_ixs):
            non_transfer_ix_stack = []
            while left_ptr < len(program_ixs) and is_transfer(program_ixs[left_ptr]):
                left_ptr += 1
            right_ptr = left_ptr + 1
            non_transfer_ix = program_ixs[left_ptr if left_ptr < len(program_ixs) else -1]
            non_transfer_ix_stack.append(non_transfer_ix)

            while right_ptr < len(program_ixs):
                transfers = []
                while not(program_ixs[right_ptr]['stackHeight'] > non_transfer_ix_stack[-1]['stackHeight']):  # ensures call stack is maintained
                    non_transfer_ix_stack.pop()
                non_transfer_ix = non_transfer_ix_stack[-1]

                while right_ptr < len(program_ixs) and is_transfer(program_ixs[right_ptr]):
                    transfers.append(program_ixs[right_ptr])
                    right_ptr += 1

                if len(transfers) > 1 and len(transfers) < 5:
                    potential_swaps.append(PotentialSwap(non_transfer_ix, transfers, top_level_ix))

                while right_ptr < len(program_ixs) and not is_transfer(program_ixs[right_ptr]):
                    while not(program_ixs[right_ptr]['stackHeight'] > non_transfer_ix_stack[-1]['stackHeight']):  # ensures call stack is maintained
                        non_transfer_ix_stack.pop()
                    non_transfer_ix_stack.append(program_ixs[right_ptr])
                    right_ptr += 1
            left_ptr = right_ptr
    return potential_swaps

async def parse_block_for_potential_sandwiches(block_number: int, rpc_url: str):
    block = await get_block(rpc_url, block_number)
    transactions: list[TransactionResponse] = block["transactions"]

    tx_list: list[PotentialSwapWithTxContext] = []
    for tx_resp in transactions:
        potential_swaps = extract_potential_swaps(tx_resp)
        if is_transaction_successful(tx_resp):
            for potential_swap in potential_swaps:
                tx_list.append(PotentialSwapWithTxContext(tx_resp, potential_swap, len(potential_swaps)))

    potential_sandwiches: list[PotentialSandwich] = []
    i = 0
    attacker_tx_set: set[str] = set()
    for i in range(len(tx_list)):
        entry_tx = tx_list[i]
        entry_signer = get_signer(entry_tx.tx_resp)
        entry_signature = get_signature(entry_tx.tx_resp)
        if entry_signature in attacker_tx_set or entry_tx.number_of_tx_swaps != 1:
            continue
        
        # Look ahead for potential exit transaction
        for j in range(i + 2, len(tx_list)):
            exit_tx = tx_list[j]
            exit_signer = get_signer(exit_tx.tx_resp)
            exit_signature = get_signature(exit_tx.tx_resp)
            if exit_signature in attacker_tx_set:
                continue
            if exit_signer == entry_signer:
                entry_dex = entry_tx.potential_swap.exchange_instruction["programId"]
                exit_dex = exit_tx.potential_swap.exchange_instruction["programId"]
                if entry_dex != exit_dex:
                    continue

                entry_transfer_infos = list(TransferInfo.from_ix(ix) for ix in entry_tx.potential_swap.transfer_instructions[0:2])
                exit_transfer_infos = list(TransferInfo.from_ix(ix) for ix in exit_tx.potential_swap.transfer_instructions[0:2])

                entry_potential_source_vaults = set(transfer_info.source for transfer_info in entry_transfer_infos)
                entry_potential_destination_vaults = set(transfer_info.destination for transfer_info in entry_transfer_infos)
                exit_potential_source_vaults = set(transfer_info.source for transfer_info in exit_transfer_infos)
                exit_potential_destination_vaults = set(transfer_info.destination for transfer_info in exit_transfer_infos)

                if not ((entry_potential_source_vaults & exit_potential_destination_vaults) and (entry_potential_destination_vaults & exit_potential_source_vaults)):
                    continue

                target_txs: list[PotentialSwapWithTxContext] = []
                valid_sequence = True
                
                for k in range(i + 1, j):
                    target_tx = tx_list[k]
                    if get_signer(target_tx.tx_resp) == entry_signer:
                        valid_sequence = False
                        break

                    current_dex = target_tx.potential_swap.exchange_instruction["programId"]
                    if current_dex == entry_dex:
                        target_transfer_infos = list(TransferInfo.from_ix(ix) for ix in target_tx.potential_swap.transfer_instructions[0:2])
                        target_potential_source_vaults = set(transfer_info.source for transfer_info in target_transfer_infos)
                        target_potential_destination_vaults = set(transfer_info.destination for transfer_info in target_transfer_infos)
                        
                        if (entry_potential_source_vaults & target_potential_source_vaults) and (entry_potential_destination_vaults & target_potential_destination_vaults):
                            target_txs.append(target_tx)
                
                if valid_sequence and target_txs:
                    attacker_tx_set.update(entry_signature, exit_signature)
                    potential_sandwiches.append(PotentialSandwich(entry_tx, target_txs, exit_tx))
                    print(f"Potential sandwich found:")
                    print(f"Bot: {None if entry_tx.potential_swap.is_top_level else entry_tx.potential_swap.top_level_ix['programId']}")
                    print(f"Signer: {entry_signer}")
                    print(f"Entry tx: {entry_signature}")
                    print(f"Target txs:")
                    for tx in target_txs:
                        print(f"    {get_signature(tx.tx_resp)} signer: {get_signer(tx.tx_resp)}")
                    print(f"Exit tx: {exit_signature}")
                    print(f"DEX: {entry_dex}")
                    print("---")
    return potential_sandwiches, int(block["blockTime"])


async def main():
    pools_map = await get_pools_map()
    print(len(pools_map.keys()))
    cslot = 336_902_506  # NOTE: Block 336454917: embedded sandwhiches?
    for block_number in range(cslot, cslot + 1):
        print(f"Processing block {block_number}")
        potential_sandwiches, block_time = await parse_block_for_potential_sandwiches(block_number, RPC_URL)
        for potential_sandwich in potential_sandwiches:
            dex = potential_sandwich.entry_tx.potential_swap.exchange_instruction["programId"]
            if dex not in EXCHANGES_INFO:
                print(f"Unknown dex with sandwhich: {dex}")
                continue
            exchange_info = EXCHANGES_INFO[dex]
            if len(potential_sandwich.entry_tx.potential_swap.exchange_instruction["accounts"]) <= exchange_info.pool_index:
                print(f"Invalid pool index for dex: {dex}")
                continue
            pool_address = potential_sandwich.entry_tx.potential_swap.exchange_instruction["accounts"][exchange_info.pool_index]
            if pool_address not in pools_map:
                print(f"Unknown pool: {pool_address}")
                continue
            pool_info = pools_map[pool_address]
            for transfer_ix in potential_sandwich.entry_tx.potential_swap.transfer_instructions:
                transfer_info = TransferInfo.from_ix(transfer_ix)
                if transfer_info.destination == pool_info.token_a_vault:
                    profit_token = pool_info.token_a
                    targeted_token = pool_info.token_b
                    break
                elif transfer_info.destination == pool_info.token_b_vault:
                    profit_token = pool_info.token_b
                    targeted_token = pool_info.token_a
                    break
                elif transfer_info.source == pool_info.token_a_vault:
                    profit_token = pool_info.token_b
                    targeted_token = pool_info.token_a
                    break
                elif transfer_info.source == pool_info.token_b_vault:
                    profit_token = pool_info.token_a
                    targeted_token = pool_info.token_b
                    break
            else:
                print(f"Unmatchable trade direction")
                continue

            sandwhich = Sandwich(
                block=block_number,
                block_time=block_time,
                dex=dex,
                pool=pool_info.id,
                bot=potential_sandwich.entry_tx.potential_swap.top_level_ix["programId"],
                attacker=get_signer(potential_sandwich.entry_tx.tx_resp),
                profit_token=profit_token,
                targeted_token=targeted_token,
                entry_tx=AttackerTx.from_potential_swap(potential_sandwich.entry_tx, pool_info.token_a_vault, pool_info.token_b_vault),
                target_txs=[TargetTx.from_potential_swap(tx, pool_info.token_a_vault, pool_info.token_b_vault) for tx in potential_sandwich.target_txs],
                exit_tx=AttackerTx.from_potential_swap(potential_sandwich.exit_tx, pool_info.token_a_vault, pool_info.token_b_vault)
            )
            print(sandwhich)
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
