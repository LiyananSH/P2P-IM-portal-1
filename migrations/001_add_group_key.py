"""
迁移脚本 001: 添加 group_key 列到 groups 表

执行方式:
    python migrations/001_add_group_key.py
"""

import sqlite3
import secrets
import sys
import os

def migrate(db_path=None):
    if db_path is None:
        # 默认路径
        db_path = os.path.join(os.path.dirname(__file__), '..', 'portal.db')
    
    print(f"🔄 迁移数据库: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查列是否存在
    cursor.execute("PRAGMA table_info(groups)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'group_key' not in columns:
        print("📝 添加 group_key 列...")
        cursor.execute('ALTER TABLE groups ADD COLUMN group_key TEXT')
        print("✅ group_key 列已添加")
    else:
        print("ℹ️  group_key 列已存在")
    
    # 为现有群组生成密钥
    print("🔑 生成 group_key...")
    cursor.execute('SELECT id FROM groups WHERE group_key IS NULL')
    rows = cursor.fetchall()
    
    for row in rows:
        key = 'gk_' + secrets.token_hex(32)
        cursor.execute('UPDATE groups SET group_key = ? WHERE id = ?', (key, row[0]))
    
    conn.commit()
    conn.close()
    
    print(f"✅ 迁移完成，为 {len(rows)} 个群组生成了密钥")

if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    migrate(db_path)
