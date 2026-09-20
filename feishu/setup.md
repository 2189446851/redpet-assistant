# 飞书多维表格配置指南（由公司账号操作）

> 这一步必须由**公司飞书账号**完成，且至少添加两名正式员工为管理员。不要使用实习生个人账号。

## 一、创建飞书企业自建应用
1. 用公司飞书账号登录飞书开放平台：https://open.feishu.cn
2. 开发者后台 → **企业自建应用** → 创建应用（名称如「REDPET 看板数据」）。
3. 在「凭证与基础信息」里记录：
   - **App ID** → 环境变量 `FEISHU_APP_ID`
   - **App Secret** → 环境变量 `FEISHU_APP_SECRET`
4. **权限管理** → 添加权限：
   - `bitable:app`（多维表格应用读写，核心权限，必须）
5. **版本管理与发布** → 创建版本 → 申请发布；发布后应用在企业内可用。
6. 「可用范围」把使用人/部门加进去（或设为全员可用）。

## 二、创建多维表格与两张表
1. 在飞书里新建一个**多维表格**（如「REDPET 社群数据」）。
2. 表格 URL 形如 `https://bitable.feishu.cn/appXXXX/baseYYYY`：
   - 其中 **appXXXX 即 `FEISHU_BITABLE_APP_TOKEN`**（注意是 app 后面的，不是 base）。
3. 建**第一张表「每日活跃数据」**，字段如下（一行 = 一天）：
   - `日期`：日期类型
   - `猫猫托儿所1群` …… 共 **19 个群，各建一列**：数字类型
   - `更新时间`：日期时间类型
   - `填写人`：文本类型
4. 建**第二张表「社群配置」**，字段：
   - `群名`：文本
   - `规模`：数字
5. 两张表各自记下 **table_id**（在表格设置里，形如 `tbl_xxx`）：
   - 每日活跃数据表的 table_id → `FEISHU_TABLE_ID`
   - 社群配置表的 table_id → `FEISHU_GROUPS_TABLE_ID`

## 三、配置 EdgeOne 后端环境变量（密钥只在这里，绝不进代码）
EdgeOne Makers 控制台 → 项目 → **环境变量** 添加：
- `FEISHU_APP_ID` = 步骤一记录的 App ID
- `FEISHU_APP_SECRET` = App Secret
- `FEISHU_BITABLE_APP_TOKEN` = 多维表格 app_token
- `FEISHU_TABLE_ID` = 每日活跃数据表 table_id
- `FEISHU_GROUPS_TABLE_ID` = 社群配置表 table_id
- `REDPET_WRITE_PASSWORD` = 自定义的内部保存密码（发给填写人）

> ⚠️ 这些密钥只在 EdgeOne 后端，前端永远看不到。切勿写进 `index.html` 或提交到 GitHub。

## 四、初始化（首次）
- 在「社群配置」表里录好 19 个群名 + 规模。
- 在「每日活跃数据」表填一行测试数据，验证后端能读出来。
- 详细测试流程见仓库根 `MINIMAL_TEST.md`。
