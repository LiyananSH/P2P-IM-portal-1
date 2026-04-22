#!/bin/bash
# P2P-IM Portal 部署脚本
# 使用方法: ./deploy.sh

set -e

echo "===== P2P-IM Portal 部署 ====="

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查是否是 Git 仓库
if [ ! -d ".git" ]; then
    echo "错误: 当前目录不是 Git 仓库"
    exit 1
fi

# 拉取最新代码
echo "1. 拉取最新代码..."
git pull origin master

# 安装依赖
echo "2. 安装依赖..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi

# 重启服务
echo "3. 重启服务..."
sudo systemctl restart portal

echo "===== 部署完成 ====="
echo "服务状态:"
sudo systemctl status portal --no-pager | head -5
