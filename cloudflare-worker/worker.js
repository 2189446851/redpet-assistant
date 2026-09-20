// REDPET 看板中转 Worker
// 作用：前端把填写数据 POST 到这里，Worker 用藏在环境变量里的 GitHub 令牌写回仓库。
// 令牌不在前端出现，因此不会被 GitHub 自动撤销。
// 数据读取（GET）也走这里，由 Cloudflare 国际节点连 GitHub，比浏览器直连稳。

const REPO = "2189446851/redpet-assistant";
const FILE_PATH = "docs/data/daily.json";
const API = `https://api.github.com/repos/${REPO}/contents/${FILE_PATH}`;

function cors() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function toB64(str) {
  // 支持中文
  return btoa(unescape(encodeURIComponent(str)));
}

async function getFile(token) {
  const res = await fetch(API, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" },
  });
  if (!res.ok) throw new Error("github get " + res.status);
  const j = await res.json();
  return { sha: j.sha, data: JSON.parse(atob(j.content)) };
}

async function putFile(token, sha, data) {
  const res = await fetch(API, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/vnd.github+json",
    },
    body: JSON.stringify({
      message: "daily fill via cloudflare worker",
      content: toB64(JSON.stringify(data, null, 2)),
      sha,
    }),
  });
  if (!res.ok) throw new Error("github put " + res.status);
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors() });
    }
    const token = env.GITHUB_TOKEN;
    if (!token) {
      return new Response("server missing GITHUB_TOKEN", { status: 500, headers: cors() });
    }
    try {
      if (request.method === "GET") {
        const { data } = await getFile(token);
        return new Response(JSON.stringify(data), {
          headers: { ...cors(), "Content-Type": "application/json" },
        });
      }
      if (request.method === "POST") {
        const body = await request.json().catch(() => null);
        if (!body) {
          return new Response("bad body", { status: 400, headers: cors() });
        }
        const { sha, data } = await getFile(token);
        // 每日填写：写 records[date]
        if (body.date && body.values) data.records[body.date] = body.values;
        // 社群管理：替换 groups 列表
        if (Array.isArray(body.groups)) data.groups = body.groups;
        data.updatedAt = body.updatedAt || new Date().toISOString();
        await putFile(token, sha, data);
        return new Response(JSON.stringify({ ok: true }), {
          headers: { ...cors(), "Content-Type": "application/json" },
        });
      }
      return new Response("method not allowed", { status: 405, headers: cors() });
    } catch (e) {
      return new Response("error: " + e.message, { status: 500, headers: cors() });
    }
  },
};
