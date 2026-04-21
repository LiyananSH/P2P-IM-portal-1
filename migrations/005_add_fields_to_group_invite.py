"""
迁移脚本 005: 添加 group_db_id 和 invitee_portal 字段到 group_invites

执行方式:
    python migrations/005_add_fields_to_group_invite.py
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
    cursor.execute("PRAGMA table_info(group_invites)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'group_db_id' in columns:
        print("ℹ️  group_db_id 列已存在")
    else:
        print("📝 添加 group_db_id 列...")
        cursor.execute("ALTER TABLE group_invites ADD COLUMN group_db_id INTEGER")
        print("✅ group_db_id 列已添加")
    
    if 'invitee_portal' in columns:
        print("ℹ️  invitee_portal 列已存在")
    else:
        print("📝 添加 invitee_portal 列...")
        cursor.execute("ALTER TABLE group_invites ADD COLUMN invitee_portal TEXT")
        print("✅ invitee_portal 列已添加")
    
    conn.commit()
    conn.close()
    
    print("✅ 迁移完成")
