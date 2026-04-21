#!/usr/bin/env python3
"""
迁移脚本：为现有群组添加全局 group_id
"""
import sqlite3
import time

def migrate():
    conn = sqlite3.connect('portal.db')
    c = conn.cursor()
    
    # 检查是否已有 group_id 列
    c.execute("PRAGMA table_info(groups)")
    columns = [col[1] for col in c.fetchall()]
    
    if 'group_id' not in columns:
        print("添加 group_id 列...")
        c.execute("ALTER TABLE groups ADD COLUMN group_id TEXT")
        
        # 为现有群组生成 group_id
        c.execute("SELECT id, name FROM groups WHERE group_id IS NULL")
        groups = c.fetchall()
        
        # 获取 portal_url
        c.execute("SELECT portal_url FROM users WHERE is_active = 1 LIMIT 1")
        row = c.fetchone()
        portal_url = row[0] if row else 'unknown'
        portal_domain = portal_url.replace('https://', '').replace('http://', '').replace('/', '_')
        
        for i, group in enumerate(groups):
            group_id, name = group
            # 使用时间戳 + 序号确保唯一
            global_id = f"group-{int(time.time())}-{i}-{portal_domain}"
            c.execute("UPDATE groups SET group_id = ? WHERE id = ?", (global_id, group_id))
            print(f"  Group {group_id} ({name}) -> {global_id}")
        
        conn.commit()
        print(f"迁移完成，共 {len(groups)} 个群组")
    else:
        print("group_id 列已存在，跳过迁移")
    
    # 检查 group_invites 表的 group_id 列类型
    c.execute("PRAGMA table_info(group_invites)")
    columns = c.fetchall()
    group_id_col = next((col for col in columns if col[1] == 'group_id'), None)
    
    if group_id_col and group_id_col[2] == 'INTEGER':
        print("\n注意：group_invites.group_id 是 INTEGER 类型，需要改为 TEXT")
        print("建议：删除并重新创建 group_invites 表")
    
    # 检查 group_messages 表是否需要添加 sender_portal 列
    c.execute("PRAGMA table_info(group_messages)")
    gm_columns = [col[1] for col in c.fetchall()]
    if 'sender_portal' not in gm_columns:
        print("\n添加 sender_portal 列到 group_messages...")
        c.execute("ALTER TABLE group_messages ADD COLUMN sender_portal TEXT")
        conn.commit()
        print("添加成功")
    
    conn.close()

if __name__ == '__main__':
    migrate()
