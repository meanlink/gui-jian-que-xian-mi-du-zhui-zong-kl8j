# 轨检缺陷密度追踪

密度聚类的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery。
规则版本（RuleVersion）与影子回放（ShadowReplay）保证计算口径可升级且历史可复现：候选口径只对已完成试验做影子回放，逐点列出分组变化，结果不进入批准与简报；负责人确认差异后切换生效。每个 Job 在创建时固定 `rule_version_id`，排队、worker 恢复、版本切换与回退都不会让在途或历史试验换版。


## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18210；后端文档 http://localhost:19210/docs；数据库宿主端口 17710。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；PostgreSQL 16；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=rail-density；FRONTEND_PORT=18210；BACKEND_PORT=19210；DB_PORT=17710；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 计算规则版本与影子回放
- 内置 `v1` 基础一维 DBSCAN 口径（`baseline_1d_dbscan`），与升级前结果逐字段一致；老库迁移自动补建并把历史试验固定到 v1，同时为旧结果补齐逐点快照，原有结果字段不变。
- 候选口径 `severity_core_1d_dbscan` 增加 `core_min_severity`（2~5 整数，默认 4）：只有复核等级不低于下限且密度达标的点能成为核心点；低等级密集点仍可作为边界点归入缺陷带，不参与密度可达扩展。
- 规则生命周期：`candidate`（候选）→ `active`（生效，同时刻仅一个，部分唯一索引兜底）→ `retired`（退役）；可回退到候选或退役版本。同一时刻至多一个 `is_active` 版本，并发切换由数据库先提交者获胜。
- 影子回放复用试验创建时的数据批次快照与参数（固定输入），逐点比较旧分组/角色与候选分组/角色，输出变化统计与逐点明细；回放写 `shadow_replays`，不修改 Job 结果、批准状态与简报。回放中断恢复为 pending 继续，已完成项重试不重复生成，失败只记录原因并保留旧版。
- 接口（前缀 `/api`）：`GET /rules`、`GET /rules/active`、`POST /rules`（analyst/admin 建候选，可带 `job_ids` 直接发起回放）、`GET /rules/{id}`、`POST /rules/{id}/replays`、`GET /rules/{id}/replays`、`POST /rules/{id}/activate`、`POST /rules/{id}/rollback`（后两者仅 admin）。前端「规则版本」页支持回放、切换、回退并查看差异与版本。
- 复现：Job 结果内含 `rule`（code/engine_key/config）与 `point_assignments` 逐点快照；用 Job 固定版本重算即可复现，历史简报的 CSV/JSON 快照不受版本切换影响。


## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1011/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
