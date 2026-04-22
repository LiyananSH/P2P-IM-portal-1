from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ========== 用户相关 ==========

class UserBase(BaseModel):
    portal_url: str = Field(..., description="Portal URL 作为身份标识")
    display_name: Optional[str] = Field(None, max_length=100)


class UserCreate(BaseModel):
    portal_url: str
    password: str = Field(..., min_length=6)
    display_name: Optional[str] = None


class UserLogin(BaseModel):
    portal_url: str = Field(..., description="你的 Portal URL")
    password: str = Field(..., min_length=6)


class UserResponse(BaseModel):
    id: int
    portal_url: str
    display_name: Optional[str]
    avatar: Optional[str]
    is_active: bool
    is_initialized: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


# ========== 联系人相关 ==========

class ContactBase(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    portal_url: str = Field(..., min_length=1, max_length=255)


class ContactCreate(ContactBase):
    shared_key: Optional[str] = None


class ContactUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=100)
    avatar: Optional[str] = None


class ContactResponse(ContactBase):
    id: int
    avatar: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ========== 群组相关 ==========

class GroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class GroupCreate(GroupBase):
    member_ids: Optional[List[int]] = []  # 初始成员联系人 ID 列表


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    avatar: Optional[str] = None


class GroupMemberAdd(BaseModel):
    contact_ids: List[int]


class GroupInvite(BaseModel):
    """发送群邀请"""
    group_id: int  # 本地数据库 group.id
    contact_id: int  # 被邀请的联系人ID


class GroupInviteResponse(BaseModel):
    """群邀请响应"""
    id: int
    group_id: int
    inviter_portal: str
    group_name: str
    shared_key: str  # 用于验证群消息
    status: str  # pending, accepted, rejected
    created_at: datetime


class GroupJoin(BaseModel):
    """接受群邀请"""
    invite_id: int
    group_name: str
    shared_key: str


class GroupResponse(GroupBase):
    id: int
    group_id: str  # 全局唯一 group_id
    owner_id: int
    avatar: Optional[str]
    is_active: bool
    created_at: datetime
    members: List[ContactResponse] = []
    
    class Config:
        from_attributes = True


# ========== 消息相关 ==========

class MessageBase(BaseModel):
    content: str = Field(..., min_length=1)
    message_type: str = Field(default="text", pattern="^(text|file|image)$")


class MessageCreate(MessageBase):
    contact_id: Optional[int] = None  # 私聊联系人 ID
    group_id: Optional[int] = None    # 群聊群组 ID
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None


class MessageResponse(MessageBase):
    id: int
    sender_id: int
    sender_name: Optional[str] = None
    contact_id: Optional[int] = None
    group_id: Optional[int] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    is_from_owner: bool = False
    is_read: bool = False
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class GroupMessageCreate(BaseModel):
    group_id: int
    content: str
    message_type: str = "text"
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None


class GroupMessageResponse(BaseModel):
    id: int
    group_id: Optional[int] = None
    group_uuid: Optional[str] = None
    sender_id: int
    sender_name: Optional[str]
    content: str
    message_type: str
    file_url: Optional[str]
    file_name: Optional[str]
    file_size: Optional[int]
    is_from_owner: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# ========== 文件相关 ==========

class FileUploadResponse(BaseModel):
    id: int
    original_name: str
    file_url: str
    file_size: int
    file_type: Optional[str]
    created_at: datetime


class FileInfo(BaseModel):
    id: int
    original_name: str
    stored_name: str
    file_size: int
    file_type: Optional[str]
    download_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ========== WebSocket 消息格式 ==========

class WSMessage(BaseModel):
    type: str = Field(..., pattern="^(message|group_message|notification|ping|pong)$")
    data: dict
    timestamp: Optional[datetime] = None


class WSMessageSend(BaseModel):
    type: str = "message"
    contact_id: Optional[int] = None
    group_id: Optional[int] = None
    content: str
    message_type: str = "text"
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None


# ========== 跨 Portal 通信 ==========

class CrossPortalMessage(BaseModel):
    """跨 Portal 消息格式"""
    from_portal: str
    to_portal: str
    sender_name: str
    content: str
    message_type: str = "text"
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    timestamp: datetime
    signature: Optional[str] = None  # 用于验证


class CrossPortalVerify(BaseModel):
    """跨 Portal 验证请求"""
    portal_url: str
    challenge: str
    response: str


# ========== 联系人请求 ==========

class ContactRequestCreate(BaseModel):
    """创建联系人请求 - 申请方提供 shared_key"""
    target_portal: str = Field(..., description="目标 Portal URL")
    requester_name: str = Field(..., min_length=1, max_length=100, description="申请者显示名称")
    requester_portal: str = Field(..., description="申请者自己的 Portal URL")
    requester_public_key: Optional[str] = Field(None, description="申请者公钥（可选）")
    shared_key: str = Field(..., description="申请方生成的共享密钥，用于双方通信认证")
    message: Optional[str] = Field(None, max_length=500, description="留言")


class ContactRequestResponse(BaseModel):
    """联系人请求响应"""
    id: int
    requester_name: str
    requester_portal: str
    requester_public_key: Optional[str]
    message: Optional[str]
    status: str
    shared_key: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class ContactRequestAction(BaseModel):
    """联系人请求操作"""
    action: str = Field(..., pattern="^(approve|reject)$")
    shared_key: Optional[str] = None
