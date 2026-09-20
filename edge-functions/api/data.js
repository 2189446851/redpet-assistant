// GET /api/data
// 从飞书读取「社群配置表(groups)」+「每日活跃数据表(records)」，合并成前端 computeModel() 能用的格式：
// { updatedAt, groups:[{name,size}], records:{ "2026-09-20":{ "群名": 人数 } } }
//
// 飞书密钥只在 EdgeOne 后端环境变量里（context.env），本文件不会被打包进前端。
// 运行环境：EdgeOne Makers Edge Functions（V8 运行时，非 Node.js）。

const API_BASE = "https://open.feishu.cn/open-apis";
const RESERVED = ["日期", "更新时间", "填写人"]; // 活跃数据表中非「群」的列

// 获取 tenant_access_token（应用维度，用 app_id + app_secret，无需用户授权）
async function getToken(env) {
  const r = await fetch(API_BASE + "/auth/v3/tenant_access_token/internal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_id: env.FEISHU_APP_ID, app_secret: env.FEISHU_APP_SECRET }),
  });
  const j = await r.json();
  if (j.code !== 0) throw new Error("feishu token " + j.code + " " + j.msg);
  return j.tenant_access_token;
}

// 带 token 的飞书请求 + 429/5xx 有限重试
async function feishuCall(env, method, path, body) {
  const token = await getToken(env);
  const tries = 3;
  let lastErr;
  for (let i = 0; i < tries; i++) {
    try {
      const opts = {
        method: method,
        headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      };
      if (body !== undefined) opts.body = JSON.stringify(body);
      const r = await fetch(API_BASE + path, opts);
      const j = await r.json();
      if (j.code === 0) return j.data;
      if (j.code === 99991663 || j.code === 99991664) {
        // token 失效，强制重取一次
        if (i < tries - 1) continue;
      }
      throw new Error("feishu " + path + " " + j.code + " " + j.msg);
    } catch (e) {
      lastErr = e;
      if (i < tries - 1) await new Promise((res) => setTimeout(res, 300 * (i + 1)));
    }
  }
  throw lastErr;
}

function toDateStr(v) {
  if (v == null) return "";
  if (typeof v === "number") {
    // 飞书日期有时返回时间戳（毫秒）
    const d = new Date(v);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  return String(v).slice(0, 10);
}

// 读取两张表并合并成前端格式
async function buildFullData(env) {
  // 社群配置表 -> groups
  const gData = await feishuCall(
    env,
    "GET",
    "/bitable/v1/apps/" + env.FEISHU_BITABLE_APP_TOKEN + "/tables/" + env.FEISHU_GROUPS_TABLE_ID + "/records?page_size=100"
  );
  const groups = (gData.items || [])
    .map((it) => ({
      name: it.fields["群名"] != null ? it.fields["群名"] : it.fields["name"],
      size: Number(it.fields["规模"] != null ? it.fields["规模"] : it.fields["size"]) || 0,
    }))
    .filter((g) => g.name);

  // 每日活跃数据表 -> records
  const dData = await feishuCall(
    env,
    "GET",
    "/bitable/v1/apps/" + env.FEISHU_BITABLE_APP_TOKEN + "/tables/" + env.FEISHU_TABLE_ID + "/records?page_size=200"
  );
  const records = {};
  let maxDate = "";
  for (const it of dData.items || []) {
    const f = it.fields || {};
    const date = toDateStr(f["日期"]);
    if (!date) continue;
    const values = {};
    for (const k of Object.keys(f)) {
      if (RESERVED.indexOf(k) >= 0) continue;
      if (typeof f[k] === "number") values[k] = f[k];
      else if (typeof f[k] === "string" && f[k].trim() !== "" && !isNaN(Number(f[k]))) values[k] = Number(f[k]);
    }
    records[date] = values;
    if (date > maxDate) maxDate = date;
  }

  return {
    updatedAt: maxDate ? new Date(maxDate + "T00:00:00").toISOString() : new Date().toISOString(),
    groups: groups,
    records: records,
  };
}

export async function onRequest(context) {
  const env = context.env;
  try {
    const out = await buildFullData(env);
    return new Response(JSON.stringify(out), {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e.message || e) }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
}
