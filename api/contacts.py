from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from database import get_db
from models import User, Contact, Message
from schemas import ContactCreate, ContactUpdate, ContactResponse
from auth import get_current_user

router = APIRouter(prefix="/contacts", tags=["联系人"])


@router.get("", response_model=List[ContactResponse])
async def list_contacts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取联系人列表"""
    result = await db.execute(
        select(Contact).where(
            and_(Contact.owner_id == current_user.id, Contact.is_active == True)
        )
    )
    contacts = result.scalars().all()
    
    # 获取每个联系人的最后活动时间
    for contact in contacts:
        last_msg = await db.execute(
            select(func.max(Message.created_at)).where(
                Message.contact_id == contact.id
            )
        )
        last_message_at = last_msg.scalar()
        
        # 计算最后活动时间：取消息时间和更新时间/创建时间的最大值
        last_activity_at = last_message_at
        if contact.updated_at and (last_activity_at is None or contact.updated_at > last_activity_at):
            last_activity_at = contact.updated_at
        if contact.created_at and (last_activity_at is None or contact.created_at > last_activity_at):
            last_activity_at = contact.created_at
        
        contact.last_activity_at = last_activity_at
    
    return contacts


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除联系人"""
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.id == contact_id,
                Contact.owner_id == current_user.id
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )
    
    # 软删除
    contact.is_active = False
    await db.flush()
    
    return None
