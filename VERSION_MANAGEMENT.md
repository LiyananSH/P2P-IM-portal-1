# 版本管理规范

## 原则

每次代码变更，必须同步更新：
1. ✅ 代码文件
2. ✅ 数据库结构（如有变更）
3. ✅ 部署脚本
4. ✅ 部署指南
5. ✅ API 文档

## 变更类型检查清单

### 类型 A：仅代码逻辑变更（无数据库变更）
- [ ] 更新代码文件
- [ ] 测试验证
- [ ] 提交到 GitHub
- [ ] 更新 DEPLOY.md（如有新步骤）

### 类型 B：API 接口变更
- [ ] 更新后端代码
- [ ] 更新前端代码
- [ ] 更新 API_DOCUMENTATION.md
- [ ] 更新 API_COMPLETE_SPEC.md
- [ ] 测试前后端匹配
- [ ] 提交到 GitHub

### 类型 C：数据库结构变更 ⚠️ 关键
- [ ] 更新 models.py
- [ ] 更新 init_db.py（添加新列/表）
- [ ] 更新 deploy.sh（确保执行 init_db.py）
- [ ] 更新 DEPLOYMENT_GUIDE.md（说明数据库变更）
- [ ] 提供数据迁移脚本（如需要）
- [ ] 测试新旧数据兼容
- [ ] 提交到 GitHub

### 类型 D：配置文件变更
- [ ] 更新配置示例
- [ ] 更新部署文档
- [ ] 通知用户配置变更

## 本次变更记录

### 2026-04-23 私聊消息修复
**变更类型**: B + C（API + 数据库）

**代码变更**:
- ✅ api/messages.py - 添加 /messages/contact/{id} 端点
- ✅ models.py - 添加 sender_portal 列
- ✅ portal_web/app.js - 更新 API 调用

**数据库变更**:
- ✅ init_db.py - 添加 sender_portal 列检查
- ✅ deploy.sh - 自动执行数据库更新

**文档更新**:
- ✅ API_COMPLETE_SPEC.md
- ✅ DEPLOYMENT_GUIDE.md
- ✅ DEPLOY.md

**GitHub 提交**:
- 后端: `31a0ac6`
- 前端: `462c68f`

## 用户通知模板

```
【重要更新】请执行以下步骤：

1. 备份数据库（可选但推荐）
   cp portal.db portal.db.backup.$(date +%Y%m%d)

2. 一键部署
   sudo ./deploy.sh

3. 验证
   curl http://localhost:8000/api/health

变更内容：
- 修复私聊消息获取
- 添加 sender_portal 字段
- 优化 WebSocket 通知

如有问题请反馈！
```

## 自动化建议

未来改进：
1. 使用 Alembic 管理数据库迁移
2. GitHub Actions 自动检查文档更新
3. 版本号管理（Semantic Versioning）
4. 自动生成 CHANGELOG
