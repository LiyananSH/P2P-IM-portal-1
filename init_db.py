#!/usr/bin/env python3
"""
数据库初始化/迁移脚本
确保数据库结构是最新的
"""

import sqlite3
import sys

def init_database(db_path="/opt/portal/portal.db"):
    """初始化数据库，添加缺失的列"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print(f"[DB] 连接到数据库: {db_path}")
    
    # 获取 messages 表的当前结构
    cursor.execute("PRAGMA table_info(messages)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"[DB] 当前 messages 表列: {columns}")
    
    # 添加缺失的列
    required_columns = {
        'sender_portal': 'VARCHAR(255)',
    }
    
    for col, col_type in required_columns.items():
        if col not in columns:
            print(f"[DB] 添加列: {col}")
            cursor.execute(f"ALTER TABLE messages ADD COLUMN {col} {col_type}")
        else:
            print(f"[DB] 列已存在: {col}")
    
    conn.commit()
    conn.close()
    print("[DB] 数据库初始化完成")

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "/opt/portal/portal.db"
    init_database(db_path)
