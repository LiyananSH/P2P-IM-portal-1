"""
迁移脚本 004: 添加 db_id 字段到 group_member_cache

执行方式:
    python migrations/004_add_db_id_to_group_member_cache.py
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
    cursor.execute("PRAGMA table_info(group_member_cache)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'db_id' in columns:
        print("ℹ️  db_id 列已存在")
    else:
        print("📝 添加 db_id 列...")
        cursor.execute("ALTER TABLE group_member_cache ADD COLUMN db_id INTEGER")
        print("✅ db_id 列已添加")
    
    if 'group_name' in columns:
        print("ℹ️  group_name 列已存在")
    else:
        print("📝 添加 group_name 列...")
        cursor.execute("ALTER TABLE group_member_cache ADD COLUMN group_name TEXT")
        print("✅ group_name 列已添加")
    
    conn.commit()
    conn.close()
    
    print("✅ 迁移完成")
