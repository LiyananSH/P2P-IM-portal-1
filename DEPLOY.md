# P2P Portal 部署指南

## 快速部署（推荐）

```bash
cd /opt/portal
sudo ./deploy.sh
```

### deploy.sh 会自动完成：
1. ✅ 更新代码（git pull）
2. ✅ 检查并添加缺失的数据库列（自动迁移）
3. ✅ 清除 Python 缓存
4. ✅ 重启服务

### 支持的版本：
- ✅ 从任意版本平滑升级
- ✅ 自动检测并添加缺失的数据库列
- ✅ 不影响现有数据

## 手动部署（不推荐）

如果一键部署脚本失败，可以手动执行：

```bash
# 1. 进入目录
cd /opt/portal

# 2. 备份数据库
cp portal.db portal.db.backup.$(date +%Y%m%d)

# 3. 更新代码
git pull origin master

# 4. 手动迁移数据库（如果需要）
python3 init_db.py

# 5. 重启服务
sudo systemctl restart portal

# 6. 检查状态
sudo systemctl status portal
```

## 数据库迁移说明

`init_db.py` 会自动检查并添加以下列：

### messages 表
| 列名 | 类型 | 说明 |
|-----|------|------|
| sender_portal | VARCHAR(255) | 发送者 Portal URL（跨 Portal 消息追踪）|

如果这些列已存在，会自动跳过，不会重复添加。

## 常见问题

### 1. 部署脚本报错 "sqlite3: command not found"
**问题**：服务器没有安装 sqlite3 命令行工具  
**解决**：使用一键部署脚本 `sudo ./deploy.sh`，它会自动使用 Python 方式迁移

### 2. 服务启动失败
```bash
# 查看错误日志
sudo journalctl -u portal -n 50

# 检查配置文件
cat /opt/portal/config.py
```

### 3. 数据库迁移失败
```bash
# 手动备份数据库
cp /opt/portal/portal.db /opt/portal/portal.db.backup

# 手动运行迁移脚本并查看详细输出
python3 /opt/portal/init_db.py
```

## 版本历史

### v2 (2026-04-23)
- 支持从任意版本平滑升级
- 自动检测并添加缺失的数据库列
- 使用 Python 代替 sqlite3 命令

### v1 (2026-04-22)
- 初始版本
- 需要手动执行数据库迁移

## 验证部署成功

```bash
# 检查服务状态
curl http://localhost:8000/api/health

# 或
curl http://localhost:8000/api/auth/me
```

如果返回 JSON 响应，说明部署成功。
