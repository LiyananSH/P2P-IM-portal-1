"""
迁移脚本 006: 添加 group_uuid 字段到 group_messages

执行方式:
    python migrations/006_add_group_uuid_to_messages.py
"""

import sqlite3
import sys
import os

def migrate(db_path=None):
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), '..', 'portal.db')
    
    print(f"🔄 迁移数据库: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查列是否存在
    cursor.execute("PRAGMA table_info(group_messages)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'group_uuid' in columns:
        print("ℹ️  group_uuid 列已存在")
    else:
        print("📝 添加 group_uuid 列...")
        
        # 创建新表
        cursor.execute("""
            CREATE TABLE group_messages_new (
                id INTEGER PRIMARY KEY,
                group_id INTEGER,
                group_uuid TEXT,
                sender_id INTEGER NOT NULL,
                sender_name TEXT,
                sender_portal TEXT,
                content TEXT NOT NULL,
                message_type TEXT DEFAULT 'text',
                file_url TEXT,
                file_name TEXT,
                file_size INTEGER,
                is_from_owner INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 复制数据
        cursor.execute("""
            INSERT INTO group_messages_new (id, group_id, sender_id, sender_name, sender_portal, 
                content, message_type, file_url, file_name, file_size, is_from_owner, created_at)
            SELECT id, group_id, sender_id, sender_name, sender_portal, 
                content, message_type, file_url, file_name, file_size, is_from_owner, created_at
            FROM group_messages
        """)
        
        # 删除旧表并重命名
        cursor.execute("DROP TABLE group_messages")
        cursor.execute("ALTER TABLE group_messages_new RENAME TO group_messages")
        print("✅ group_uuid 列已添加（并重建表）")
    
    conn.commit()
    conn.close()
    
    print("✅ 迁移完成")
