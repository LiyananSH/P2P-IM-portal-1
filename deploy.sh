#!/bin/bash
# P2P Portal 一键部署脚本
# 使用方法: sudo ./deploy.sh

set -e  # 遇到错误立即退出

echo "========================================"
echo "  P2P Portal 部署脚本"
echo "========================================"
echo ""

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then 
    echo "❌ 请使用 sudo 运行此脚本"
    exit 1
fi

# 配置
PORTAL_DIR="/opt/portal"
DB_FILE="$PORTAL_DIR/portal.db"
SERVICE_NAME="portal"

echo "[1/5] 更新代码..."
cd $PORTAL_DIR
sudo -u ubuntu git pull origin master
echo "✅ 代码更新完成"
echo ""

echo "[2/5] 检查并更新数据库结构..."
# 检查 sender_portal 列是否存在
if sqlite3 $DB_FILE ".schema messages" | grep -q "sender_portal"; then
    echo "✅ sender_portal 列已存在"
else
    echo "📝 添加 sender_portal 列..."
    sqlite3 $DB_FILE "ALTER TABLE messages ADD COLUMN sender_portal VARCHAR(255);"
    echo "✅ 数据库更新完成"
fi
echo ""

echo "[3/5] 清除 Python 缓存..."
rm -rf $PORTAL_DIR/__pycache__
rm -rf $PORTAL_DIR/api/__pycache__
find $PORTAL_DIR -name "*.pyc" -delete 2>/dev/null || true
echo "✅ 缓存清除完成"
echo ""

echo "[4/5] 重启服务..."
systemctl restart $SERVICE_NAME
sleep 2
echo "✅ 服务重启完成"
echo ""

echo "[5/5] 检查服务状态..."
if systemctl is-active --quiet $SERVICE_NAME; then
    echo "✅ 服务运行正常"
else
    echo "❌ 服务启动失败，请检查日志:"
    echo "   sudo journalctl -u $SERVICE_NAME -n 20"
    exit 1
fi
echo ""

echo "========================================"
echo "  部署完成！"
echo "========================================"
echo ""
echo "验证接口:"
echo "  curl http://localhost:8000/api/health"
echo ""
echo "查看日志:"
echo "  sudo journalctl -u $SERVICE_NAME -f"
