from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, String, Integer, ForeignKey, Table, select, Enum, UniqueConstraint, BigInteger, func, PrimaryKeyConstraint, case, distinct
from sqlalchemy.orm import relationship
from typing import AsyncGenerator
import enum
from config import POOLS_DATABASE_URL, DATABASE_URL
from tx_types import PoolInfo, Sandwich as SandwichType
from utils import get_signer

pools_engine = create_async_engine(POOLS_DATABASE_URL, connect_args={"server_settings": {"search_path": "solana"}})
pools_async_session = sessionmaker(pools_engine, class_=AsyncSession, expire_on_commit=False)

engine = create_async_engine(DATABASE_URL, connect_args={"server_settings": {"search_path": "solana"}})
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


Base = declarative_base()


class AttackerTxType(enum.Enum):
    ENTRY = "entry"
    EXIT = "exit"


class PoolsMap(Base):
    __tablename__ = "pools_map"

    id = Column(String, primary_key=True, index=True)
    DEX = Column(String)
    token_a = Column(String)
    token_b = Column(String)
    token_a_vault = Column(String)
    token_b_vault = Column(String)


class AttackerTx(Base):
    __tablename__ = "attacker_txs"

    signature = Column(String, primary_key=True)
    profit_token_amount = Column(BigInteger)
    targeted_token_amount = Column(BigInteger)
    jito_tip = Column(BigInteger)
    priority_fee = Column(BigInteger)
    type = Column(Enum(AttackerTxType))
    sandwich_id = Column(String, ForeignKey("sandwiches.id"))
    sandwich = relationship("Sandwich", back_populates="attacker_txs")

    __table_args__ = (
        UniqueConstraint('sandwich_id', 'type', name='uix_sandwich_type'),
    )


class TargetTx(Base):
    __tablename__ = "target_txs"

    signature = Column(String)
    sandwich_id = Column(String, ForeignKey("sandwiches.id"))
    signer = Column(String)
    profit_token_amount = Column(BigInteger)
    targeted_token_amount = Column(BigInteger)
    sandwich = relationship("Sandwich", back_populates="target_txs")

    __table_args__ = (
        PrimaryKeyConstraint('signature', 'sandwich_id', name='pk_signature_sandwich'),
    )


class Sandwich(Base):
    __tablename__ = "sandwiches"

    id = Column(String, primary_key=True)  # Will be a UUID or similar unique identifier
    block = Column(Integer)
    block_time = Column(Integer)
    dex = Column(String)
    pool = Column(String)
    bot = Column(String)
    attacker = Column(String)
    profit_token = Column(String)
    targeted_token = Column(String)
    
    attacker_txs = relationship("AttackerTx", back_populates="sandwich")
    target_txs = relationship("TargetTx", back_populates="sandwich")

    @property
    def entry_tx(self):
        return next((tx for tx in self.attacker_txs if tx.type == AttackerTxType.ENTRY), None)

    @property
    def exit_tx(self):
        return next((tx for tx in self.attacker_txs if tx.type == AttackerTxType.EXIT), None)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_pools_map() -> dict[str, PoolInfo]:
    async with pools_async_session() as session:
        pools = await session.execute(select(PoolsMap))
        return {pool.id: PoolInfo(pool.id, pool.token_a, pool.token_b, pool.token_a_vault, pool.token_b_vault) for pool in pools.scalars().all()}


async def store_sandwich(sandwich: SandwichType) -> None:
    """
    Store a sandwich instance in the database.
    
    Args:
        sandwich: The Sandwich instance to store
    """
    async with async_session() as session:
        db_sandwich = Sandwich(
            id=sandwich.entry_tx.signature,
            block=sandwich.block,
            block_time=sandwich.block_time,
            dex=sandwich.dex,
            pool=sandwich.pool,
            bot=sandwich.bot,
            attacker=sandwich.attacker,
            profit_token=sandwich.profit_token,
            targeted_token=sandwich.targeted_token
        )
        entry_tx = AttackerTx(
            signature=sandwich.entry_tx.signature,
            profit_token_amount=sandwich.entry_tx.profit_token_amount,
            targeted_token_amount=sandwich.entry_tx.targeted_token_amount,
            jito_tip=sandwich.entry_tx.jito_tip,
            priority_fee=sandwich.entry_tx.priority_fee,
            type=AttackerTxType.ENTRY,
            sandwich_id=db_sandwich.id
        )
        exit_tx = AttackerTx(
            signature=sandwich.exit_tx.signature,
            profit_token_amount=sandwich.exit_tx.profit_token_amount,
            targeted_token_amount=sandwich.exit_tx.targeted_token_amount,
            jito_tip=sandwich.exit_tx.jito_tip,
            priority_fee=sandwich.exit_tx.priority_fee,
            type=AttackerTxType.EXIT,
            sandwich_id=db_sandwich.id
        )

        target_txs = [
            TargetTx(
                signature=target.signature,
                signer=target.signer,
                profit_token_amount=target.profit_token_amount,
                targeted_token_amount=target.targeted_token_amount,
                sandwich_id=db_sandwich.id
            )
            for target in sandwich.target_txs
        ]
        session.add(db_sandwich)
        session.add(entry_tx)
        session.add(exit_tx)
        for target_tx in target_txs:
            session.add(target_tx)

        await session.commit()


async def clear_db():
    """
    Clear all tables in the database and recreate them.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def get_latest_block() -> int:
    async with async_session() as session:
        result = await session.execute(select(func.max(Sandwich.block)))
        latest_block = result.scalar()
        return latest_block if latest_block is not None else 0

async def get_distinct_sandwich_blocks() -> list[int]:
    async with async_session() as session:
        result = await session.execute(select(distinct(Sandwich.block)))
        return [block for block in result.scalars().all()]

async def get_profit_token_stats() -> list[dict]:
    """
    Returns statistics grouped by profit_token including:
    - total_sandwiches: number of sandwiches
    - total_profit: sum of (exit_tx.profit_token_amount - entry_tx.profit_token_amount)
    - unique_victims: count of unique signers in target_txs
    - unique_attackers: count of unique attackers
    """
    async with async_session() as session:
        # Subquery to get entry and exit profit amounts per sandwich
        entry_exit_profit = select(
            Sandwich.profit_token,
            Sandwich.attacker,
            Sandwich.id,
            func.sum(case(
                (AttackerTx.type == AttackerTxType.EXIT, AttackerTx.profit_token_amount),
                (AttackerTx.type == AttackerTxType.ENTRY, -AttackerTx.profit_token_amount),
                else_=0
            )).label('net_profit'),
            func.sum(AttackerTx.jito_tip).label('jito_tip')
        ).join(
            AttackerTx, Sandwich.id == AttackerTx.sandwich_id
        ).where(
            Sandwich.profit_token == 'So11111111111111111111111111111111111111112'  # SOL token address
        ).group_by(
            Sandwich.profit_token,
            Sandwich.attacker,
            Sandwich.id
        ).subquery()

        # Subquery to get unique victims per profit token
        unique_victims = select(
            Sandwich.profit_token,
            func.count(distinct(TargetTx.signer)).label('unique_victims')
        ).join(
            TargetTx, Sandwich.id == TargetTx.sandwich_id
        ).where(
            Sandwich.profit_token == 'So11111111111111111111111111111111111111112'
        ).group_by(
            Sandwich.profit_token
        ).subquery()

        # Main query to aggregate statistics
        result = await session.execute(
            select(
                entry_exit_profit.c.profit_token,
                func.count(distinct(entry_exit_profit.c.id)).label('total_sandwiches'),
                func.sum(entry_exit_profit.c.net_profit).label('total_profit'),
                func.sum(entry_exit_profit.c.jito_tip).label('total_jito_tip'),
                func.count(distinct(entry_exit_profit.c.attacker)).label('unique_attackers'),
                unique_victims.c.unique_victims
            ).join(
                unique_victims, entry_exit_profit.c.profit_token == unique_victims.c.profit_token
            ).group_by(
                entry_exit_profit.c.profit_token,
                unique_victims.c.unique_victims
            )
        )

        # Convert to dictionary format
        stats = [
            {
                'profit_token': row.profit_token,
                'total_sandwiches': row.total_sandwiches,
                'total_profit': int(row.total_profit) / (10**9),
                'total_jito_tip': int(row.total_jito_tip) / (10**9),
                'unique_victims': row.unique_victims,
                'unique_attackers': row.unique_attackers
            } for row in result
        ]
        return stats

async def get_most_targeted_tokens() -> list[dict]:
    """
    Returns statistics about most frequently sandwiched tokens including:
    - token: the token address
    - sandwich_count: number of sandwiches targeting this token
    - total_profit: total profit extracted from sandwiches (exit - entry amounts)
    - unique_attackers: number of unique attackers targeting this token
    """
    async with async_session() as session:
        # First get sandwich-level stats
        sandwich_stats = select(
            Sandwich.targeted_token,
            Sandwich.attacker,
            Sandwich.id,
            func.sum(case(
                (AttackerTx.type == AttackerTxType.EXIT, AttackerTx.profit_token_amount),
                (AttackerTx.type == AttackerTxType.ENTRY, -AttackerTx.profit_token_amount),
                else_=0
            )).label('profit')
        ).join(
            AttackerTx, Sandwich.id == AttackerTx.sandwich_id
        ).where(
            Sandwich.profit_token == 'So11111111111111111111111111111111111111112'  # SOL token address
        ).group_by(
            Sandwich.targeted_token,
            Sandwich.attacker,
            Sandwich.id
        ).subquery()

        # Then aggregate by token
        result = await session.execute(
            select(
                sandwich_stats.c.targeted_token,
                func.count(sandwich_stats.c.id).label('sandwich_count'),
                func.sum(sandwich_stats.c.profit).label('total_profit'),
                func.count(distinct(sandwich_stats.c.attacker)).label('unique_attackers')
            ).group_by(
                sandwich_stats.c.targeted_token
            ).order_by(
                func.count(sandwich_stats.c.id).desc()
            )
        )
        
        return [
            {
                'token': row.targeted_token,
                'sandwich_count': int(row.sandwich_count),
                'total_profit': float(int(row.total_profit) / (10**9)),
                'unique_attackers': int(row.unique_attackers)
            } for row in result
        ]

async def get_most_targeted_programs() -> list[dict]:
    """
    Returns statistics about most targeted DEX programs including:
    - dex: the DEX name
    - sandwich_count: number of sandwiches on this DEX
    - total_profit: total profit extracted from sandwiches (exit - entry amounts)
    - unique_pools: number of unique pools targeted
    """
    async with async_session() as session:
        # First get sandwich-level stats
        sandwich_stats = select(
            Sandwich.dex,
            Sandwich.pool,
            Sandwich.id,
            func.sum(case(
                (AttackerTx.type == AttackerTxType.EXIT, AttackerTx.profit_token_amount),
                (AttackerTx.type == AttackerTxType.ENTRY, -AttackerTx.profit_token_amount),
                else_=0
            )).label('profit')
        ).join(
            AttackerTx, Sandwich.id == AttackerTx.sandwich_id
        ).where(
            Sandwich.profit_token == 'So11111111111111111111111111111111111111112'  # SOL token address
        ).group_by(
            Sandwich.dex,
            Sandwich.pool,
            Sandwich.id
        ).subquery()

        # Then aggregate by DEX
        result = await session.execute(
            select(
                sandwich_stats.c.dex,
                func.count(sandwich_stats.c.id).label('sandwich_count'),
                func.sum(sandwich_stats.c.profit).label('total_profit'),
                func.count(distinct(sandwich_stats.c.pool)).label('unique_pools')
            ).group_by(
                sandwich_stats.c.dex
            ).order_by(
                func.count(sandwich_stats.c.id).desc()
            )
        )
        
        return [
            {
                'dex': row.dex,
                'sandwich_count': int(row.sandwich_count),
                'total_profit': float(int(row.total_profit) / (10**9)),
                'unique_pools': int(row.unique_pools)
            } for row in result
        ]

async def get_most_exploited_pools() -> list[dict]:
    """
    Returns statistics about most exploited liquidity pools including:
    - pool: the pool address
    - dex: the DEX name
    - sandwich_count: number of sandwiches on this pool
    - total_profit: total profit extracted from sandwiches (exit - entry amounts)
    """
    async with async_session() as session:
        # First get sandwich-level stats
        sandwich_stats = select(
            Sandwich.pool,
            Sandwich.dex,
            Sandwich.id,
            func.sum(case(
                (AttackerTx.type == AttackerTxType.EXIT, AttackerTx.profit_token_amount),
                (AttackerTx.type == AttackerTxType.ENTRY, -AttackerTx.profit_token_amount),
                else_=0
            )).label('profit')
        ).join(
            AttackerTx, Sandwich.id == AttackerTx.sandwich_id
        ).where(
            Sandwich.profit_token == 'So11111111111111111111111111111111111111112'  # SOL token address
        ).group_by(
            Sandwich.pool,
            Sandwich.dex,
            Sandwich.id
        ).subquery()

        # Then aggregate by pool
        result = await session.execute(
            select(
                sandwich_stats.c.pool,
                sandwich_stats.c.dex,
                func.count(sandwich_stats.c.id).label('sandwich_count'),
                func.sum(sandwich_stats.c.profit).label('total_profit')
            ).group_by(
                sandwich_stats.c.pool,
                sandwich_stats.c.dex
            ).order_by(
                func.count(sandwich_stats.c.id).desc()
            )
        )
        
        return [
            {
                'pool': row.pool,
                'dex': row.dex,
                'sandwich_count': int(row.sandwich_count),
                'total_profit': float(int(row.total_profit) / (10**9))
            } for row in result
        ]

async def get_bot_cumulative_profits() -> list[dict]:
    """
    Returns cumulative profits per bot including:
    - bot: the bot address
    - total_profit: total profit extracted (exit - entry amounts)
    - sandwich_count: number of sandwiches
    - avg_profit_per_sandwich: average profit per sandwich
    """
    async with async_session() as session:
        # First get sandwich-level stats
        sandwich_stats = select(
            Sandwich.bot,
            Sandwich.id,
            func.sum(case(
                (AttackerTx.type == AttackerTxType.EXIT, AttackerTx.profit_token_amount),
                (AttackerTx.type == AttackerTxType.ENTRY, -AttackerTx.profit_token_amount),
                else_=0
            )).label('profit')
        ).join(
            AttackerTx, Sandwich.id == AttackerTx.sandwich_id
        ).where(
            Sandwich.profit_token == 'So11111111111111111111111111111111111111112'  # SOL token address
        ).group_by(
            Sandwich.bot,
            Sandwich.id
        ).subquery()

        # Then aggregate by bot
        result = await session.execute(
            select(
                sandwich_stats.c.bot,
                func.sum(sandwich_stats.c.profit).label('total_profit'),
                func.count(sandwich_stats.c.id).label('sandwich_count'),
                (func.sum(sandwich_stats.c.profit) / func.count(sandwich_stats.c.id)).label('avg_profit')
            ).group_by(
                sandwich_stats.c.bot
            ).order_by(
                func.sum(sandwich_stats.c.profit).desc()
            )
        )
        
        return [
            {
                'bot': row.bot,
                'total_profit': float(int(row.total_profit) / (10**9)),
                'sandwich_count': int(row.sandwich_count),
                'avg_profit_per_sandwich': float(int(row.avg_profit) / (10**9))
            } for row in result
        ]

async def get_attack_frequency_per_program() -> list[dict]:
    """
    Returns attack frequency per DEX program including:
    - dex: the DEX name
    - total_attacks: total number of sandwiches (attacks) on this DEX
    - unique_attackers: number of unique attackers
    - avg_attacks_per_block: average number of sandwiches per block
    """
    async with async_session() as session:
        # First get sandwich-level stats
        sandwich_stats = select(
            Sandwich.dex,
            Sandwich.block,
            Sandwich.id,
            Sandwich.attacker
        ).where(
            Sandwich.profit_token == 'So11111111111111111111111111111111111111112'  # SOL token address
        ).subquery()

        # Then aggregate by DEX
        result = await session.execute(
            select(
                sandwich_stats.c.dex,
                func.count(distinct(sandwich_stats.c.id)).label('total_attacks'),
                func.count(distinct(sandwich_stats.c.attacker)).label('unique_attackers'),
                (func.count(distinct(sandwich_stats.c.id)) / func.count(distinct(sandwich_stats.c.block))).label('attacks_per_block')
            ).group_by(
                sandwich_stats.c.dex
            ).order_by(
                func.count(distinct(sandwich_stats.c.id)).desc()
            )
        )
        
        return [
            {
                'dex': row.dex,
                'total_attacks': int(row.total_attacks),
                'unique_attackers': int(row.unique_attackers),
                'avg_attacks_per_block': float(row.attacks_per_block)
            } for row in result
        ]
    

async def get_all_stats():
    stats = {}
    stats["profit_token_stats"] = await get_profit_token_stats()
    stats["most_targeted_tokens"] = await get_most_targeted_tokens()
    stats["most_targeted_programs"] = await get_most_targeted_programs()
    stats["most_exploited_pools"] = await get_most_exploited_pools()
    stats["bot_cumulative_profits"] = await get_bot_cumulative_profits()
    stats["attack_frequency_per_program"] = await get_attack_frequency_per_program()
    return stats