from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Portal 配置"""
    
    # 应用配置
    APP_NAME: str = "Agent Portal"
    DEBUG: bool = True
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./portal.db"
    
    # JWT 配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7天
    
    # 文件存储
    UPLOAD_DIR: str = "./storage/uploads"
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    
    # Agent Channel 配置
    AGENT_CHANNEL_ENABLED: bool = True
    OPENCLAW_GATEWAY_URL: str = "http://127.0.0.1:18789"
    OPENCLAW_HOOKS_TOKEN: str = ""
    
    # 跨 Portal 通信
    PORTAL_URL: str = "https://your-portal.com"  # 自己的 Portal 地址
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
