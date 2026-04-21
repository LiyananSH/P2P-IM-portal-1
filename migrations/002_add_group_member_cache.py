"""
迁移脚本 002: 添加群成员本地缓存表

执行方式:
    python migrations/002_add_group_member_cache.py
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
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='group_member_cache'")
    if cursor.fetchone():
        print("ℹ️  group_member_cache 表已存在")
    else:
        print("📝 创建 group_member_cache 表...")
        cursor.execute("""
            CREATE TABLE group_member_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT UNIQUE NOT NULL,
                owner_portal TEXT NOT NULL,
                group_key TEXT NOT NULL,
                members_json TEXT,
                list_version INTEGER DEFAULT 1,
                list_signature TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ group_member_cache 表已创建")
    
    conn.commit()
    conn.close()
    
    print("✅ 迁移完成")

if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    migrate(db_path)
