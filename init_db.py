#!/usr/bin/env python3
"""
数据库迁移脚本
检查并添加所有缺失的列，确保数据库结构与代码同步
支持从任意版本平滑升级到最新版本
"""

import sqlite3
import sys
from datetime import datetime

def get_table_columns(cursor, table_name):
    """获取表的列信息"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}

def migrate_contacts_table(cursor):
    """迁移 contacts 表，添加缺失的列"""
    columns = get_table_columns(cursor, "contacts")
    
    migrations = {
        'remote_display_name': 'VARCHAR(100)',  # 对方自称什么（对方的 User.display_name）
    }
    
    print(f"[DB] contacts 表当前列: {sorted(columns)}")
    
    for col_name, col_type in migrations.items():
        if col_name not in columns:
            print(f"[DB] 添加列: {col_name} ({col_type})...")
            cursor.execute(f"ALTER TABLE contacts ADD COLUMN {col_name} {col_type}")
            print(f"[DB] ✅ {col_name} 列添加成功")
        else:
            print(f"[DB] ✅ {col_name} 列已存在")


def migrate_messages_table(cursor):
    """迁移 messages 表，添加缺失的列"""
    columns = get_table_columns(cursor, "messages")
    
    migrations = {
        'sender_portal': 'VARCHAR(255)',  # 发送者 Portal URL（用于跨 Portal 消息追踪）
    }
    
    print(f"[DB] messages 表当前列: {sorted(columns)}")
    
    for col_name, col_type in migrations.items():
        if col_name not in columns:
            print(f"[DB] 添加列: {col_name} ({col_type})...")
            cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
            print(f"[DB] ✅ {col_name} 列添加成功")
        else:
            print(f"[DB] ✅ {col_name} 列已存在")

def migrate_group_messages_table(cursor):
    """迁移 group_messages 表，添加缺失的列"""
    columns = get_table_columns(cursor, "group_messages")
    
    migrations = {
        # 根据需要添加更多迁移
    }
    
    print(f"[DB] group_messages 表当前列: {sorted(columns)}")
    
    for col_name, col_type in migrations.items():
        if col_name not in columns:
            print(f"[DB] 添加列: {col_name} ({col_type})...")
            cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
            print(f"[DB] ✅ {col_name} 列添加成功")
        else:
            print(f"[DB] ✅ {col_name} 列已存在")


def migrate_contact_requests_table(cursor):
    """迁移 contact_requests 表，添加/重命名列"""
    columns = get_table_columns(cursor, "contact_requests")
    
    # 添加新列 requester_display_name（如果不存在）
    if 'requester_display_name' not in columns:
        print(f"[DB] 添加列: requester_display_name (VARCHAR(100))...")
        cursor.execute("ALTER TABLE contact_requests ADD COLUMN requester_display_name VARCHAR(100)")
        # 如果有旧的 requester_name 列，数据迁移到新列
        if 'requester_name' in columns:
            cursor.execute("UPDATE contact_requests SET requester_display_name = requester_name")
            print(f"[DB] ✅ 数据从 requester_name 迁移到 requester_display_name")
        print(f"[DB] ✅ requester_display_name 列添加成功")
    else:
        print(f"[DB] ✅ requester_display_name 列已存在")


def migrate_all(db_path="/opt/portal/portal.db"):
    """执行所有迁移"""
    print(f"[DB] 连接到数据库: {db_path}")
    print(f"[DB] 迁移时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 50)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 迁移 contacts 表
        print("[DB] 检查 contacts 表...")
        migrate_contacts_table(cursor)
        
        # 迁移 messages 表
        print("[DB] 检查 messages 表...")
        migrate_messages_table(cursor)
        
        # 迁移 group_messages 表
        print("[DB] 检查 group_messages 表...")
        migrate_group_messages_table(cursor)
        
        # 迁移 contact_requests 表
        print("[DB] 检查 contact_requests 表...")
        migrate_contact_requests_table(cursor)
        
        conn.commit()
        print("-" * 50)
        print("[DB] ✅ 所有迁移完成！")
        
    except Exception as e:
        print(f"[DB] ❌ 迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "/opt/portal/portal.db"
    
    print("=" * 50)
    print("  P2P Portal 数据库迁移脚本")
    print("=" * 50)
    
    try:
        migrate_all(db_path)
        print("\n[DB] 可以安全退出")
    except Exception as e:
        print(f"\n[DB] 迁移异常退出: {e}")
        sys.exit(1)
