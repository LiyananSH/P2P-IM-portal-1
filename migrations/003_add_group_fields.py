"""
迁移脚本 003: 添加 group.version 和 group_member_cache.group_name

执行方式:
    python migrations/003_add_group_fields.py
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
    
    # 检查 groups.version 是否存在
    cursor.execute("PRAGMA table_info(groups)")
    groups_cols = [col[1] for col in cursor.fetchall()]
    
    if 'version' not in groups_cols:
        print("📝 添加 groups.version 列...")
        cursor.execute("ALTER TABLE groups ADD COLUMN version INTEGER DEFAULT 1")
        print("✅ groups.version 列已添加")
    else:
        print("ℹ️  groups.version 列已存在")
    
    # 检查 group_member_cache.group_name 是否存在
    cursor.execute("PRAGMA table_info(group_member_cache)")
    cache_cols = [col[1] for col in cursor.fetchall()]
    
    if 'group_name' not in cache_cols:
        print("📝 添加 group_member_cache.group_name 列...")
        cursor.execute("ALTER TABLE group_member_cache ADD COLUMN group_name TEXT")
        print("✅ group_member_cache.group_name 列已添加")
    else:
        print("ℹ️  group_member_cache.group_name 列已存在")
    
    conn.commit()
    conn.close()
    
    print("✅ 迁移完成")

if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    migrate(db_path)
