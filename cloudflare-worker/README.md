# REDPET 看板中转 Worker 部署说明

作用：前端不再直连 `api.github.com`（国内网络经常连不上），而是把填写数据发到这个 Cloudflare Worker，由它用藏在后端环境变量里的 GitHub 令牌写回仓库。

## 1. 准备 Cloudflare 账号
- 打开 https://dash.cloudflare.com/sign-up 用邮箱免费注册（无需信用卡）。

## 2. 准备 GitHub 令牌
- 去 https://github.com/settings/tokens 新建一个 **classic token**（或 fine-grained）。
- 只勾 `repo` 整组（或 fine-grained 的 Contents: Read and write）。
- 复制生成的 `ghp_...` / `github_pat_...` 令牌备用。
- ⚠️ 这个令牌只存在 Cloudflare 后端，不会出现在网页源码，所以不会被 GitHub 自动撤销。

## 3. 在本机安装并登录 wrangler
```bash
npm install -g wrangler
wrangler login        # 浏览器弹窗授权 Cloudflare 账号
```

## 4. 部署
进入本目录（cloudflare-worker/）后执行：
```bash
wrangler secret put GITHUB_TOKEN    # 粘贴上面的 GitHub 令牌
wrangler deploy
```
部署成功后会输出类似：
`https://redpet-worker.<subdomain>.workers.dev`

把这个地址发给李胜利，他会填回前端 `docs/index.html` 的 `WORKER_URL` 常量并推送。

## 5. 验证
- 浏览器打开 `https://<你的worker地址>` 应返回一份 JSON（即 daily.json 内容）。
- 看板里「每日填写 → 保存」即可经此中转写回 GitHub。
