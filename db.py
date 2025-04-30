from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, String, select
from typing import AsyncGenerator
from config import DATABASE_URL
from tx_types import PoolInfo

engine = create_async_engine(DATABASE_URL, connect_args={"server_settings": {"search_path": "solana"}})
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


Base = declarative_base()


class PoolsMap(Base):
    __tablename__ = "pools_map"

    id = Column(String, primary_key=True, index=True)
    DEX = Column(String)
    token_a = Column(String)
    token_b = Column(String)
    token_a_vault = Column(String)
    token_b_vault = Column(String)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_pools_map() -> dict[str, PoolInfo]:
    async for session in get_session():
        pools = await session.execute(select(PoolsMap))
        return {pool.id: PoolInfo(pool.id, pool.token_a, pool.token_b, pool.token_a_vault, pool.token_b_vault) for pool in pools.scalars().all()}

