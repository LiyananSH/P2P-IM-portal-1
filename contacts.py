from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

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
        # 查询与该联系人的最后消息
        last_msg = await db.execute(
            select(func.max(Message.created_at)).where(
                or_(
                    and_(
                        Message.sender_id == current_user.id,
                        Message.recipient_portal == contact.portal_url
                    ),
                    and_(
                        Message.sender_portal == contact.portal_url,
                        Message.recipient_portal == current_user.portal_url
                    )
                )
            )
        )
        contact.last_message_at = last_msg.scalar()
    
    return contacts


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    contact_data: ContactCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """添加联系人"""
    # 检查是否已存在
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.owner_id == current_user.id,
                Contact.portal_url == contact_data.portal_url
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contact with this portal URL already exists"
        )
    
    # 创建联系人
    new_contact = Contact(
        owner_id=current_user.id,
        display_name=contact_data.display_name,
        portal_url=contact_data.portal_url,
        shared_key=contact_data.shared_key
    )
    
    db.add(new_contact)
    await db.flush()
    
    return new_contact


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取单个联系人"""
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.id == contact_id,
                Contact.owner_id == current_user.id,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )
    
    return contact


@router.put("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int,
    contact_data: ContactUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新联系人"""
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
    
    # 更新字段
    if contact_data.display_name is not None:
        contact.display_name = contact_data.display_name
    if contact_data.avatar is not None:
        contact.avatar = contact_data.avatar
    
    await db.flush()
    return contact


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除联系人（软删除）"""
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
    
    contact.is_active = False
    await db.flush()
    
    return None
