"""
文件上传和下载 API
支持私聊和群聊文件传输
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from auth import get_current_user
from models import User, Contact, Message, Group, GroupMessage
from config import get_settings

router = APIRouter(prefix="/files", tags=["文件"])

# 上传目录
UPLOAD_DIR = Path("/opt/portal/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 允许的文件类型
ALLOWED_TYPES = {
    "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
    "document": ["application/pdf", "text/plain", "application/msword",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "audio": ["audio/mpeg", "audio/wav", "audio/ogg"],
    "video": ["video/mp4", "video/webm"]
}

# 最大文件大小 (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024


def get_file_type(content_type: str) -> str:
    """根据 content_type 判断文件类型"""
    for file_type, types in ALLOWED_TYPES.items():
        if content_type in types:
            return file_type
    return "other"


def generate_file_path(original_filename: str) -> tuple[str, str]:
    """生成文件存储路径和 URL
    返回: (文件路径, 访问 URL)
    """
    # 生成 UUID 文件名
    ext = Path(original_filename).suffix
    filename = f"{uuid.uuid4()}{ext}"
    
    # 按日期分目录
    now = datetime.now()
    date_dir = f"{now.year}/{now.month:02d}/{now.day:02d}"
    
    # 完整路径
    file_dir = UPLOAD_DIR / date_dir
    file_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = file_dir / filename
    
    # 访问 URL
    file_url = f"/uploads/{date_dir}/{filename}"
    
    return str(file_path), file_url


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    上传文件
    返回文件信息，用于发送文件消息
    """
    # 检查文件大小
    content = await file.read()
    file_size = len(content)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过限制 ({MAX_FILE_SIZE / 1024 / 1024}MB)"
        )
    
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件不能为空"
        )
    
    # 生成文件路径
    file_path, file_url = generate_file_path(file.filename)
    
    # 保存文件
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件保存失败: {str(e)}"
        )
    
    return {
        "file_url": file_url,
        "file_name": file.filename,
        "file_size": file_size,
        "file_type": get_file_type(file.content_type),
        "content_type": file.content_type
    }


@router.get("/download/{file_path:path}")
async def download_file(
    file_path: str,
    current_user: User = Depends(get_current_user)
):
    """
    下载文件（需要认证）
    验证用户权限后返回文件
    """
    return await serve_file(file_path)


@router.get("/public/{file_path:path}")
async def public_download_file(file_path: str):
    """
    公开下载文件（无需认证）
    用于聊天中的文件链接直接访问
    """
    return await serve_file(file_path)


async def serve_file(file_path: str):
    """提供文件下载的通用函数"""
    # 安全检查：防止目录遍历
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的文件路径"
        )
    
    full_path = UPLOAD_DIR / file_path
    
    # 检查文件是否存在
    if not full_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在"
        )
    
    # 返回文件
    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream"
    )
