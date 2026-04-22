# 数据恢复指南

## 重要声明

**deploy.sh 脚本不会删除数据库！**

脚本只执行以下安全操作：
1. ✅ 更新代码（git pull）
2. ✅ 添加新列（ALTER TABLE ADD COLUMN）
3. ✅ 清除 Python 缓存文件
4. ✅ 重启服务

## 如果不慎删除了数据库

### 1. 检查是否有备份

```bash
# 查看备份文件
ls -la /opt/portal/portal.db.backup*

# 如果有备份，恢复
cp /opt/portal/portal.db.backup.XXXX /opt/portal/portal.db
sudo systemctl restart portal
```

### 2. 如果没有备份

需要重新初始化：

```bash
cd /opt/portal

# 重新创建数据库
python3 -c "
from database import init_db
import asyncio
asyncio.run(init_db())
"

# 重启服务
sudo systemctl restart portal
```

**注意**：重新初始化会丢失所有数据！

## 预防措施

### 1. 定期备份

```bash
# 手动备份
cp /opt/portal/portal.db /opt/portal/portal.db.backup.$(date +%Y%m%d)

# 或使用脚本自动备份
```

### 2. 使用新版本 deploy.sh

新版本的 deploy.sh 会自动备份数据库！

### 3. 不要手动删除数据库

❌ 不要执行：
```bash
rm portal.db  # 危险！
```

✅ 正确做法：
```bash
# 先备份
cp portal.db portal.db.backup

# 然后执行部署脚本
sudo ./deploy.sh
```

## 联系支持

如果数据丢失，请立即：
1. 停止服务：`sudo systemctl stop portal`
2. 检查备份：`ls -la /opt/portal/portal.db*`
3. 联系管理员恢复
