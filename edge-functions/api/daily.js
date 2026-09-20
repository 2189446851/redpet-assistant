// POST /api/daily
// body: { "date": "2026-09-20", "values": { "群名": 人数 }, "password": "内部密码", "writer": "可选" }
//
// 处理要求：
// 1. 验证内部密码
// 2. 验证日期格式 YYYY-MM-DD
// 3. 只接受预先配置的群名（从社群配置表读取）
// 4. 人数必须是 0~2000 的整数
// 5. 按日期查找飞书记录
// 6. 有记录就更新，没有就创建
// 7. 返回保存后的完整数据（同 /api/data 格式）
// 8. 对飞书 429/临时错误有限重试
//
// 飞书密钥只在后端环境变量，前端不出现。

const API_BASE = "https://open.feishu.cn/open-apis";
const RESERVED = ["日期", "更新时间", "填写人"];

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
      throw new Error("feishu " + path + " " + j.code + " " + j.msg);
    } catch (e) {
      lastErr = e;
      if (i < tries - 1) await new Promise((res) => setTimeout(res, 300 * (i + 1)));
    }
  }
  throw lastErr;
}

// 读取社群配置表，返回允许的群名集合 + [{name,size}]
async function loadGroups(env) {
  const gData = await feishuCall(
    env,
    "GET",
    "/bitable/v1/apps/" + env.FEISHU_BITABLE_APP_TOKEN + "/tables/" + env.FEISHU_GROUPS_TABLE_ID + "/records?page_size=100"
  );
  return (gData.items || [])
    .map((it) => ({
      name: it.fields["群名"] != null ? it.fields["群名"] : it.fields["name"],
      size: Number(it.fields["规模"] != null ? it.fields["规模"] : it.fields["size"]) || 0,
    }))
    .filter((g) => g.name);
}

// 按日期查找活跃数据表记录，返回 {record_id, fields}
async function findRecordByDate(env, date) {
  const d = await feishuCall(
    env,
    "GET",
    "/bitable/v1/apps/" + env.FEISHU_BITABLE_APP_TOKEN + "/tables/" + env.FEISHU_TABLE_ID + "/records?page_size=200"
  );
  for (const it of d.items || []) {
    const f = it.fields || {};
    let fd = f["日期"];
    if (typeof fd === "number") {
      const dt = new Date(fd);
      fd = dt.getFullYear() + "-" + String(dt.getMonth() + 1).padStart(2, "0") + "-" + String(dt.getDate()).padStart(2, "0");
    } else {
      fd = String(fd).slice(0, 10);
    }
    if (fd === date) return { record_id: it.record_id, fields: f };
  }
  return { record_id: null, fields: {} };
}

function nowStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}

async function buildFullData(env) {
  const groups = await loadGroups(env);
  const dData = await feishuCall(
    env,
    "GET",
    "/bitable/v1/apps/" + env.FEISHU_BITABLE_APP_TOKEN + "/tables/" + env.FEISHU_TABLE_ID + "/records?page_size=200"
  );
  const records = {};
  let maxDate = "";
  for (const it of dData.items || []) {
    const f = it.fields || {};
    let date = f["日期"];
    if (typeof date === "number") {
      const dt = new Date(date);
      date = dt.getFullYear() + "-" + String(dt.getMonth() + 1).padStart(2, "0") + "-" + String(dt.getDate()).padStart(2, "0");
    } else {
      date = String(date).slice(0, 10);
    }
    if (!date) continue;
    const values = {};
    for (const k of Object.keys(f)) {
      if (RESERVED.indexOf(k) >= 0) continue;
      if (typeof f[k] === "number") values[k] = f[k];
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
  const request = context.request;
  if (request.method === "OPTIONS") return new Response(null, { status: 204 });
  if (request.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return new Response(JSON.stringify({ error: "bad json" }), { status: 400, headers: { "Content-Type": "application/json" } });
  }

  // 1. 验证内部密码
  if (!body.password || body.password !== env.REDPET_WRITE_PASSWORD) {
    return new Response(JSON.stringify({ error: "密码错误" }), { status: 401, headers: { "Content-Type": "application/json" } });
  }
  // 2. 验证日期
  if (!/^\d{4}-\d{2}-\d{2}$/.test(body.date || "")) {
    return new Response(JSON.stringify({ error: "日期格式错误，应为 YYYY-MM-DD" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  // 3 & 4. 群名与人数校验
  const groups = await loadGroups(env);
  const allowed = {};
  groups.forEach((g) => (allowed[g.name] = true));
  const values = {};
  for (const k of Object.keys(body.values || {})) {
    if (!allowed[k]) {
      return new Response(JSON.stringify({ error: "未知群名：" + k }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }
    const n = Math.round(Number(body.values[k]));
    if (!Number.isInteger(n) || n < 0 || n > 2000) {
      return new Response(JSON.stringify({ error: "人数超出范围(0~2000整数)：" + k }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }
    values[k] = n;
  }

  const table = env.FEISHU_TABLE_ID;
  const app = env.FEISHU_BITABLE_APP_TOKEN;
  const base = "/bitable/v1/apps/" + app + "/tables/" + table;

  // 5 & 6. upsert
  const found = await findRecordByDate(env, body.date);
  const fields = { 日期: body.date, 更新时间: nowStr(), 填写人: body.writer || "" };
  Object.keys(values).forEach((k) => (fields[k] = values[k]));

  try {
    if (found.record_id) {
      await feishuCall(env, "PUT", base + "/records/" + found.record_id, { fields: fields });
    } else {
      await feishuCall(env, "POST", base + "/records", { fields: fields });
    }
  } catch (e) {
    return new Response(JSON.stringify({ error: "飞书写入失败：" + (e.message || e) }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  // 7. 返回完整数据
  try {
    const full = await buildFullData(env);
    return new Response(JSON.stringify({ ok: true, data: full }), {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch (e) {
    return new Response(JSON.stringify({ ok: true, error: "保存成功但读取回显失败：" + (e.message || e) }), {
      headers: { "Content-Type": "application/json" },
    });
  }
}
