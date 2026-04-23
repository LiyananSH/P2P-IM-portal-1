#!/bin/bash
# P2P Portal 一键部署脚本
# 使用方法: sudo ./deploy.sh
# 
# ⚠️ 重要说明：
# - 本脚本不会删除任何数据
# - 本脚本不会删除数据库文件
# - 本脚本自动检查并添加缺失的数据库列
# - 支持从任意版本平滑升级到最新版本
# - 建议先备份数据库：cp portal.db portal.db.backup

set -e  # 遇到错误立即退出

echo "========================================"
echo "  P2P Portal 部署脚本"
echo "========================================"
echo ""
echo "⚠️  本脚本不会删除数据库或数据！"
echo "⚠️  自动检查并添加缺失的数据库列"
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

# 可选：备份数据库
if [ -f "$DB_FILE" ]; then
    BACKUP_FILE="$PORTAL_DIR/portal.db.backup.$(date +%Y%m%d_%H%M%S)"
    echo "💾 备份数据库到: $BACKUP_FILE"
    cp $DB_FILE $BACKUP_FILE
    echo "✅ 备份完成"
    echo ""
fi

echo "[1/5] 更新代码..."
cd $PORTAL_DIR
sudo -u ubuntu git pull origin master
echo "✅ 代码更新完成"
echo ""

echo "[2/5] 迁移数据库..."
# 使用 Python 脚本迁移数据库（兼容不同版本）
python3 $PORTAL_DIR/init_db.py
echo "✅ 数据库迁移完成"
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
