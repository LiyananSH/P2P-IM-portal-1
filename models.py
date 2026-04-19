from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

# 群组成员关联表
group_members = Table(
    'group_members',
    Base.metadata,
    Column('group_id', Integer, ForeignKey('groups.id'), primary_key=True),
    Column('contact_id', Integer, ForeignKey('contacts.id'), primary_key=True)
)


class User(Base):
    """用户表 - 去中心化身份，portal_url 是唯一标识"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    portal_url = Column(String(255), unique=True, index=True, nullable=False)  # Portal URL 作为身份标识
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(100))
    avatar = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_initialized = Column(Boolean, default=False)  # 是否已完成首次设置
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    contacts = relationship("Contact", back_populates="owner", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="sender", foreign_keys="Message.sender_id")
    groups = relationship("Group", back_populates="owner", cascade="all, delete-orphan")


class Contact(Base):
    """联系人表"""
    __tablename__ = "contacts"
    
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    display_name = Column(String(100), nullable=False)
    portal_url = Column(String(255), nullable=False)  # 对方 Portal 地址
    shared_key = Column(String(255))  # 共享密钥，用于跨 Portal 认证
    avatar = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    owner = relationship("User", back_populates="contacts")
    messages = relationship("Message", back_populates="contact", foreign_keys="Message.contact_id")
    groups = relationship("Group", secondary=group_members, back_populates="members")


class Group(Base):
    """群组表"""
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    owner = relationship("User", back_populates="groups")
    members = relationship("Contact", secondary=group_members, back_populates="groups")
    messages = relationship("GroupMessage", back_populates="group", cascade="all, delete-orphan")


class Message(Base):
    """私聊消息表"""
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(20), default="text")  # text, file, image
    file_url = Column(String(500))  # 文件/图片 URL
    file_name = Column(String(255))  # 原始文件名
    file_size = Column(Integer)  # 文件大小（字节）
    is_from_owner = Column(Boolean, default=False)  # 是否来自主人（决定是否转发给 Agent）
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    sender = relationship("User", back_populates="messages", foreign_keys=[sender_id])
    contact = relationship("Contact", back_populates="messages", foreign_keys=[contact_id])


class GroupMessage(Base):
    """群聊消息表"""
    __tablename__ = "group_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 本地用户 ID
    sender_name = Column(String(100))  # 发送者显示名（用于跨 Portal 显示）
    content = Column(Text, nullable=False)
    message_type = Column(String(20), default="text")
    file_url = Column(String(500))
    file_name = Column(String(255))
    file_size = Column(Integer)
    is_from_owner = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    group = relationship("Group", back_populates="messages")


class FileRecord(Base):
    """文件记录表"""
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True, index=True)
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    original_name = Column(String(255), nullable=False)
    stored_name = Column(String(255), nullable=False)  # 存储文件名（UUID）
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String(100))
    is_public = Column(Boolean, default=False)
    download_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ContactRequest(Base):
    """联系人请求表 - 用于去中心化添加联系人"""
    __tablename__ = "contact_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 被添加者（本机用户）
    
    # 申请者信息
    requester_name = Column(String(100), nullable=False)  # 申请者显示名称
    requester_portal = Column(String(255), nullable=False)  # 申请者 Portal URL
    requester_public_key = Column(String(255))  # 申请者公钥（可选）
    
    # 请求内容
    message = Column(Text)  # 留言/验证信息
    status = Column(String(20), default="pending")  # pending, approved, rejected
    
    # 验证信息
    shared_key = Column(String(255))  # 生成的共享密钥
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    owner = relationship("User", foreign_keys=[owner_id])
