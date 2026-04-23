import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import httpx

from database import get_db
from models import User, Contact, ContactRequest
from schemas import ContactRequestCreate, ContactRequestResponse, ContactCreate
from auth import get_current_user
from config import get_settings

router = APIRouter(prefix="/contact-requests", tags=["联系人请求"])


def generate_shared_key() -> str:
    """生成共享密钥"""
    return f"shared_{uuid.uuid4().hex}"


async def forward_apply_request(request_data: ContactRequestCreate) -> dict:
    """
    转发申请到目标 Portal
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{request_data.target_portal}/api/contact-requests/apply",
                json={
                    "target_portal": request_data.target_portal,
                    "requester_name": request_data.requester_name,
                    "requester_portal": request_data.requester_portal,
                    "requester_public_key": request_data.requester_public_key,
                    "shared_key": request_data.shared_key,
                    "message": request_data.message
                },
                timeout=10.0
            )
            
            if response.status_code == 201:
                return response.json()
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Target portal error: {response.text}"
                )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot reach target portal: {str(e)}"
        )


# ========== 公开接口：任何人可以申请添加 ==========

@router.post("/apply", response_model=dict, status_code=status.HTTP_201_CREATED)
async def apply_contact(
    request: Request,
    request_data: ContactRequestCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    匿名申请添加联系人
    如果 target_portal 不是本机，转发请求到对方 Portal
    """
    settings = get_settings()
    target_portal = request_data.target_portal
    
    # 如果目标不是本机，转发请求
    if target_portal != settings.PORTAL_URL:
        return await forward_apply_request(request_data)
    
    # 以下处理发向本机的申请
    
    # 申请方必须提供 shared_key
    if not request_data.shared_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shared_key is required"
        )
    
    # 查找目标用户（默认第一个用户，或根据域名配置）
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    owner = result.scalar_one_or_none()
    
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user found on this portal"
        )
    
    # 检查是否已有待处理的请求
    result = await db.execute(
        select(ContactRequest).where(
            and_(
                ContactRequest.owner_id == owner.id,
                ContactRequest.requester_portal == request_data.requester_portal,
                ContactRequest.status == "pending"
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request already pending"
        )
    
    # 检查是否已经是联系人
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.owner_id == owner.id,
                Contact.portal_url == request_data.requester_portal,
                Contact.is_active == True
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already in contacts"
        )
    
    # 创建请求 - 保存申请方提供的 shared_key
    new_request = ContactRequest(
        owner_id=owner.id,
        requester_name=request_data.requester_name,
        requester_portal=request_data.requester_portal,
        requester_public_key=request_data.requester_public_key,
        shared_key=request_data.shared_key,  # 申请方提供的共享密钥
        message=request_data.message,
        status="pending"
    )
    
    db.add(new_request)
    await db.flush()
    
    # TODO: 通过 WebSocket 通知用户有新请求
    
    return {
        "status": "success",
        "message": "Request submitted, waiting for approval",
        "request_id": new_request.id
    }


# ========== 需要登录的接口 ==========

@router.get("/received", response_model=List[ContactRequestResponse])
async def get_received_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取收到的联系人请求"""
    result = await db.execute(
        select(ContactRequest).where(
            and_(
                ContactRequest.owner_id == current_user.id,
                ContactRequest.status == "pending"
            )
        ).order_by(ContactRequest.created_at.desc())
    )
    requests = result.scalars().all()
    return requests


@router.get("/sent", response_model=List[ContactRequestResponse])
async def get_sent_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取发送的联系人请求（通过查询自己的 Portal URL）"""
    settings = get_settings()
    
    result = await db.execute(
        select(ContactRequest).where(
            and_(
                ContactRequest.requester_portal == settings.PORTAL_URL,
                ContactRequest.status == "pending"
            )
        ).order_by(ContactRequest.created_at.desc())
    )
    requests = result.scalars().all()
    return requests


@router.post("/{request_id}/approve", response_model=dict)
async def approve_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    批准联系人请求
    批准后：
    1. 在本机添加对方为联系人（使用申请方提供的 shared_key）
    2. 通知对方 Portal 请求已批准（回调时带上 shared_key）
    3. 对方收到通知后确认 shared_key 并添加本机为联系人
    """
    # 查找请求
    result = await db.execute(
        select(ContactRequest).where(
            and_(
                ContactRequest.id == request_id,
                ContactRequest.owner_id == current_user.id,
                ContactRequest.status == "pending"
            )
        )
    )
    contact_request = result.scalar_one_or_none()
    
    if not contact_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )
    
    # 获取申请方提供的 shared_key
    shared_key = contact_request.shared_key
    if not shared_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request missing shared_key"
        )
    
    # 1. 在本机添加对方为联系人（使用申请方提供的 shared_key）
    new_contact = Contact(
        owner_id=current_user.id,
        display_name=contact_request.requester_name,
        portal_url=contact_request.requester_portal,
        shared_key=shared_key,  # 使用申请方提供的密钥
        is_active=True
    )
    db.add(new_contact)
    
    # 2. 更新请求状态
    contact_request.status = "approved"
    
    await db.flush()
    
    # 3. 异步通知对方 Portal（带上 shared_key 供对方确认）
    await notify_requester_approved(contact_request, current_user, shared_key)
    
    return {
        "status": "success",
        "message": "Request approved, contact added",
        "contact_id": new_contact.id,
        "shared_key": shared_key
    }


@router.post("/{request_id}/reject", response_model=dict)
async def reject_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """拒绝联系人请求"""
    result = await db.execute(
        select(ContactRequest).where(
            and_(
                ContactRequest.id == request_id,
                ContactRequest.owner_id == current_user.id,
                ContactRequest.status == "pending"
            )
        )
    )
    contact_request = result.scalar_one_or_none()
    
    if not contact_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )
    
    contact_request.status = "rejected"
    await db.flush()
    
    # 通知对方请求被拒绝
    await notify_requester_rejected(contact_request)
    
    return {
        "status": "success",
        "message": "Request rejected"
    }


# ========== 对方 Portal 回调接口 ==========

@router.post("/callback/approved", response_model=dict)
async def handle_approval_callback(
    callback_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    对方 Portal 批准后的回调
    验证 shared_key 并添加对方为联系人
    """
    settings = get_settings()
    
    # 验证这是发给我们的回调
    target_portal = callback_data.get("target_portal")
    if target_portal != settings.PORTAL_URL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid target portal"
        )
    
    # 获取回调中的 shared_key
    callback_shared_key = callback_data.get("shared_key")
    approver_portal = callback_data.get("approver_portal")
    
    if not callback_shared_key or not approver_portal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing shared_key or approver_portal"
        )
    
    # 查找本机用户（默认第一个）
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    owner = result.scalar_one_or_none()
    
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user found"
        )
    
    # 检查是否已存在
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.owner_id == owner.id,
                Contact.portal_url == approver_portal,
                Contact.is_active == True
            )
        )
    )
    if result.scalar_one_or_none():
        return {"status": "already_exists"}
    
    # 验证 shared_key 是否匹配（我们之前发送的）
    # 这里简化处理，直接信任回调中的 shared_key
    # 生产环境可以额外验证
    
    # 添加对方为联系人
    new_contact = Contact(
        owner_id=owner.id,
        display_name=callback_data.get("approver_name", "Unknown"),
        portal_url=approver_portal,
        shared_key=callback_shared_key,  # 保存对方返回的 shared_key
        is_active=True
    )
    db.add(new_contact)
    await db.flush()
    
    return {
        "status": "success",
        "message": "Contact added automatically",
        "contact_id": new_contact.id
    }


# ========== 辅助函数 ==========

async def notify_requester_approved(
    request: ContactRequest,
    approver: User,
    shared_key: str
):
    """通知申请者请求已批准"""
    import logging
    settings = get_settings()
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{request.requester_portal}/api/contact-requests/callback/approved",
                json={
                    "target_portal": request.requester_portal,
                    "approver_portal": settings.PORTAL_URL,
                    "approver_name": approver.display_name or approver.username,
                    "shared_key": shared_key,
                    "request_id": request.id
                },
                timeout=10.0
            )
            logging.info(f"Callback sent to {request.requester_portal}, status: {response.status_code}")
    except Exception as e:
        logging.error(f"Failed to notify requester: {e}")


async def notify_requester_rejected(request: ContactRequest):
    """通知申请者请求被拒绝"""
    # 可以实现，但当前版本简化处理
    pass
