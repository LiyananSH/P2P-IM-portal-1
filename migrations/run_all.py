"""
运行所有迁移脚本
"""

import os
import sys

def run_all(db_path=None):
    migrations_dir = os.path.dirname(__file__)
    
    # 按编号排序
    migration_files = sorted([
        f for f in os.listdir(migrations_dir) 
        if f.endswith('.py') and f != '__init__.py' and f != 'run_all.py'
    ])
    
    print(f"Found {len(migration_files)} migration(s)")
    
    for filename in migration_files:
        module_name = filename[:-3]  # 去掉 .py
        print(f"\n{'='*50}")
        print(f"Running: {module_name}")
        print('='*50)
        
        # 动态导入并执行
        module = __import__(f'migrations.{module_name}', fromlist=['migrate'])
        module.migrate(db_path)

if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_all(db_path)
    print("\n✅ 所有迁移完成")
