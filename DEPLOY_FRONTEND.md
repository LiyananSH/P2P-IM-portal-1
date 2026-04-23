# P2P Portal 前端部署指南

## 目录结构说明

```
/opt/portal/                    # 后端主目录
├── api/                       # 后端 API 代码
├── models.py                  # 数据模型
├── main.py                    # 主入口
├── portal.db                  # 数据库
├── static/                    # ⚠️ 前端文件目录（Nginx/后端从这里提供）
│   ├── index.html
│   ├── app.js
│   └── style.css
└── ...
```

**重要**：前端文件必须放在 `/opt/portal/static/` 目录，后端服务会从这个目录提供静态文件。

## 部署步骤

### 方法一：使用部署脚本（推荐）

```bash
cd /opt/portal
sudo ./deploy.sh
```

### 方法二：手动部署前端

如果前端需要单独更新：

```bash
# 1. 进入前端代码目录
cd /opt/portal/static

# 2. 更新代码
git pull origin master

# 3. 或者手动复制文件
cp /path/to/new/app.js /opt/portal/static/
cp /path/to/new/style.css /opt/portal/static/
cp /path/to/new/index.html /opt/portal/static/
```

### 方法三：从 GitHub 克隆部署

```bash
# 1. 克隆前端仓库
cd /opt/portal
git clone https://github.com/yananli199307-dev/P2P-IM-portal-web.git temp_web

# 2. 复制文件到 static 目录
cp temp_web/*.html /opt/portal/static/
cp temp_web/*.js /opt/portal/static/
cp temp_web/*.css /opt/portal/static/

# 3. 清理
rm -rf temp_web

# 4. 重启服务
sudo systemctl restart portal
```

## 常见问题

### 1. 前端更新后没变化

可能的原因：
- 浏览器缓存 - 尝试 Ctrl+Shift+R 强制刷新
- 文件没有复制到正确位置 - 检查 `/opt/portal/static/` 目录

```bash
# 确认文件存在
ls -la /opt/portal/static/

# 确认文件是最新的
grep "version" /opt/portal/static/app.js
```

### 2. 404 错误

Nginx 或后端可能没有正确配置静态文件目录。检查：

```bash
# 检查 Nginx 配置
cat /etc/nginx/sites-enabled/your-config

# 检查后端静态文件配置
grep -A 5 "static" /opt/portal/main.py
```

### 3. 目录不存在

如果 `/opt/portal/static/` 目录不存在，创建它：

```bash
sudo mkdir -p /opt/portal/static
sudo chown -R ubuntu:ubuntu /opt/portal/static
```

## 验证部署成功

1. 刷新浏览器页面
2. 打开开发者工具 (F12) -> Network
3. 确认 `app.js` 等文件的响应状态是 200
4. 检查文件内容是否是最新的

## 一键部署脚本（前后端）

```bash
#!/bin/bash
# frontend_deploy.sh - 前端一键部署脚本

FRONTEND_DIR="/opt/portal/static"
REPO_URL="https://github.com/yananli199307-dev/P2P-IM-portal-web.git"
BACKUP_DIR="/opt/portal/frontend_backup.$(date +%Y%m%d_%H%M%S)"

echo "=== P2P Portal 前端部署 ==="

# 1. 备份现有文件
if [ -d "$FRONTEND_DIR" ]; then
    echo "备份现有前端文件到: $BACKUP_DIR"
    cp -r $FRONTEND_DIR $BACKUP_DIR
fi

# 2. 创建目录
sudo mkdir -p $FRONTEND_DIR
sudo chown -R ubuntu:ubuntu $FRONTEND_DIR

# 3. 拉取最新代码（如果有 Git 仓库）
cd $FRONTEND_DIR
if [ -d ".git" ]; then
    git pull origin master
else
    echo "不是 Git 仓库，手动复制文件"
fi

# 4. 重启服务
sudo systemctl restart portal

echo "=== 前端部署完成 ==="
echo "请刷新浏览器 (Ctrl+Shift+R)"
```
