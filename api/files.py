import os
import uuid
import aiofiles
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import User, FileRecord
from schemas import FileUploadResponse, FileInfo
from auth import get_current_user
from config import get_settings

router = APIRouter(prefix="/files", tags=["文件"])


def ensure_upload_dir():
    """确保上传目录存在"""
    settings = get_settings()
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def get_file_extension(filename: str) -> str:
    """获取文件扩展名"""
    return Path(filename).suffix.lower()


def generate_stored_name(original_name: str) -> str:
    """生成存储文件名（UUID + 扩展名）"""
    ext = get_file_extension(original_name)
    return f"{uuid.uuid4().hex}{ext}"


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """上传文件"""
    settings = get_settings()
    
    # 检查文件大小
    file_size = 0
    content = await file.read()
    file_size = len(content)
    
    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Max size: {settings.MAX_FILE_SIZE / 1024 / 1024}MB"
        )
    
    # 确保上传目录存在
    upload_dir = ensure_upload_dir()
    
    # 生成存储文件名
    stored_name = generate_stored_name(file.filename)
    file_path = upload_dir / stored_name
    
    # 保存文件
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)
    
    # 创建文件记录
    file_record = FileRecord(
        uploader_id=current_user.id,
        original_name=file.filename,
        stored_name=stored_name,
        file_path=str(file_path),
        file_size=file_size,
        file_type=file.content_type
    )
    
    db.add(file_record)
    await db.flush()
    
    # 生成文件 URL
    file_url = f"/api/files/download/{stored_name}"
    
    return FileUploadResponse(
        id=file_record.id,
        original_name=file_record.original_name,
        file_url=file_url,
        file_size=file_record.file_size,
        file_type=file_record.file_type,
        created_at=file_record.created_at
    )


@router.get("/download/{stored_name}")
async def download_file(
    stored_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """下载文件"""
    # 查询文件记录
    result = await db.execute(
        select(FileRecord).where(
            and_(
                FileRecord.stored_name == stored_name,
                or_(
                    FileRecord.uploader_id == current_user.id,
                    FileRecord.is_public == True
                )
            )
        )
    )
    file_record = result.scalar_one_or_none()
    
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # 检查文件是否存在
    file_path = Path(file_record.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk"
        )
    
    # 更新下载次数
    file_record.download_count += 1
    await db.flush()
    
    return FileResponse(
        path=str(file_path),
        filename=file_record.original_name,
        media_type=file_record.file_type or "application/octet-stream"
    )


@router.get("", response_model=List[FileInfo])
async def list_files(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取当前用户的文件列表"""
    result = await db.execute(
        select(FileRecord).where(
            FileRecord.uploader_id == current_user.id
        ).order_by(FileRecord.created_at.desc())
    )
    files = result.scalars().all()
    return files


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除文件"""
    result = await db.execute(
        select(FileRecord).where(
            and_(
                FileRecord.id == file_id,
                FileRecord.uploader_id == current_user.id
            )
        )
    )
    file_record = result.scalar_one_or_none()
    
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # 删除物理文件
    file_path = Path(file_record.file_path)
    if file_path.exists():
        file_path.unlink()
    
    # 删除数据库记录
    await db.delete(file_record)
    await db.flush()
    
    return None


# 导入 or_ 用于上面的查询
from sqlalchemy import or_
