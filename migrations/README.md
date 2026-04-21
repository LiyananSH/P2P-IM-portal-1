# 数据库迁移

## 迁移列表

| 编号 | 名称 | 说明 |
|------|------|------|
| 001 | add_group_key | 添加 group_key 列到 groups 表 |

## 使用方法

### 执行单个迁移
```bash
python migrations/001_add_group_key.py
```

### 执行所有迁移
```bash
python migrations/run_all.py
```

### 指定数据库路径
```bash
python migrations/001_add_group_key.py /path/to/portal.db
```

## 添加新迁移

1. 在 `migrations/` 目录创建新文件，编号递增
2. 实现 `migrate()` 函数
3. 在 `run_all.py` 中添加调用
