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
    
    # 获取每个联系人的最后消息时间
    for contact in contacts:
        last_msg = await db.execute(
            select(func.max(Message.created_at)).where(
                Message.contact_id == contact.id
            )
        )
        contact.last_message_at = last_msg.scalar()
    
    return contacts
