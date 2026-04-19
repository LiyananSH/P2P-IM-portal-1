from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from config import get_settings

settings = get_settings()

# 创建异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def get_db() -> AsyncSession:
    """获取数据库会话（依赖注入）"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化数据库（创建表）"""
    from models import Base, User
    from sqlalchemy import select
    from config import get_settings
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # 检查是否需要创建默认用户
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        if not result.scalar_one_or_none():
            settings = get_settings()
            print(f"⚠️ 首次使用，请访问 {settings.PORTAL_URL} 完成初始化设置")
