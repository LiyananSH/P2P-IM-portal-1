from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import User
from schemas import UserCreate, UserLogin, UserResponse, Token
from auth import get_password_hash, verify_password, create_access_token, get_current_user
from config import get_settings

router = APIRouter(prefix="/auth", tags=["认证"])


@router.get("/status", response_model=dict)
async def auth_status(db: AsyncSession = Depends(get_db)):
    """检查认证状态 - 是否有用户已初始化"""
    result = await db.execute(select(User).where(User.is_initialized == True))
    user = result.scalar_one_or_none()
    
    settings = get_settings()
    return {
        "initialized": user is not None,
        "portal_url": settings.PORTAL_URL
    }


class InitAccountRequest(BaseModel):
    password: str
    display_name: Optional[str] = None

@router.post("/init", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def init_account(
    data: InitAccountRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    首次初始化账号
    自动使用当前 Portal 的 URL 作为身份标识
    """
    settings = get_settings()
    
    # 检查是否已初始化
    result = await db.execute(select(User).where(User.is_initialized == True))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account already initialized"
        )
    
    # 检查是否已有该 Portal URL 的用户
    result = await db.execute(select(User).where(User.portal_url == settings.PORTAL_URL))
    existing = result.scalar_one_or_none()
    
    if existing:
        # 更新现有用户
        existing.hashed_password = get_password_hash(data.password)
        existing.display_name = data.display_name or "管理员"
        existing.is_initialized = True
        await db.flush()
        return existing
    
    # 创建新用户
    new_user = User(
        portal_url=settings.PORTAL_URL,
        hashed_password=get_password_hash(data.password),
        display_name=data.display_name or "管理员",
        is_initialized=True,
        is_active=True
    )
    
    db.add(new_user)
    await db.flush()
    
    return new_user


@router.post("/login", response_model=Token)
async def login(login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """
    登录 - 使用 Portal URL + 密码
    """
    # 查询用户
    result = await db.execute(select(User).where(User.portal_url == login_data.portal_url))
    user = result.scalar_one_or_none()
    
    # 验证用户和密码
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect portal URL or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive"
        )
    
    # 创建 Token - 用 portal_url 作为 subject
    access_token_expires = timedelta(weeks=1)
    access_token = create_access_token(
        data={"sub": user.portal_url}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user


@router.post("/change-password", response_model=dict)
async def change_password(
    old_password: str,
    new_password: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """修改密码"""
    if not verify_password(old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect old password"
        )
    
    current_user.hashed_password = get_password_hash(new_password)
    await db.flush()
    
    return {"status": "success", "message": "Password changed successfully"}
