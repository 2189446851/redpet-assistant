# REDPET 小助手 · 社群数据看板

纯前端社群活跃度看板 + 每日填写，数据存到**飞书多维表格**，通过**同域的小后端接口**中转（飞书密钥只在后端，前端零密钥）。

## 功能
- 社群活跃度看板：高活 / 活跃 / 普通 / 低活分层、趋势分析、社群明细。
- 每日填写 19 个群的发言人数 → 保存到飞书多维表格。
- 换手机 / 换电脑打开看板，从飞书加载最新数据。
- 内置 AI 小助手（扣子）。

## 架构
```
浏览器 index.html（静态）
   │  GET /api/data    POST /api/daily    POST /api/groups
   ▼
EdgeOne Makers 同域函数（edge-functions/）
   │  飞书开放 API（密钥只在后端环境变量）
   ▼
飞书多维表格（两张表：每日活跃数据 / 社群配置）
```
- 前端**永远不出现**飞书 App Secret / App ID / 写密码。
- 网页只和同域 `/api/*` 说话，无跨域问题。

## 目录
- `index.html`（仓库根，EdgeOne 部署入口）/ `docs/index.html`（GitHub Pages 过渡副本，内容相同）
- `edge-functions/api/data.js` — 读飞书 → 前端格式
- `edge-functions/api/daily.js` — 每日填写 upsert（校验密码/日期/群名/人数，按日期更新或新建）
- `edge-functions/api/groups.js` — 社群管理（增删群，改飞书表结构）
- `feishu/setup.md` — 飞书应用与建表指南
- `MINIMAL_TEST.md` — 最小测试清单
- `HANDOVER.md` — 交接文档（一页）

## 部署（摘要，详见 feishu/setup.md）
1. 按 `feishu/setup.md` 用公司账号建飞书应用 + 两张表，拿到 5 个飞书参数。
2. EdgeOne 建 Makers 项目，静态根设为 `docs`（或仓库根 `index.html`），函数目录 `edge-functions`。
3. 配置 6 个环境变量（飞书 5 个 + 写密码 1 个）。
4. 推送代码或 `edgeone makers deploy`，拿到看板域名。
5. 手机微信打开域名 → 首次保存输密码 → 完成。

## 说明
- **GitHub 仅作代码备份**，不再存储每日数据。
- 若公司无备案域名，EdgeOne 默认域名在大陆可能不稳；此时飞书网页/App 为正式数据入口，看板尝试提交，后续由公司决定买域名备案或接受 CloudBase。
- 飞书不可用时，看板自动降级为「离线数据」（内嵌备份 + 本机缓存），保存失败可用「导出备份」存本地。
