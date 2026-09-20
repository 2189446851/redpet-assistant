// POST /api/groups
// 社群管理：新增 / 移除群。body: { "groups": [{ "name": "群名", "size": 499 }], "password": "内部密码" }
// - 与前端「社群管理」页对应：把最新群列表整体设为 groups。
// - 新增的群：在「社群配置表」加一行 + 在「每日活跃数据表」加一个数字列。
// - 移除的群：在「社群配置表」删对应行 + 在「每日活跃数据表」删该列（历史数据里的该群值随之不再展示）。
//
// 飞书密钥只在后端环境变量，前端不出现。

const API_BASE = "https://open.feishu.cn/open-apis";

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
      const opts = { method: method, headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" } };
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

async function loadGroups(env) {
  const gData = await feishuCall(
    env,
    "GET",
    "/bitable/v1/apps/" + env.FEISHU_BITABLE_APP_TOKEN + "/tables/" + env.FEISHU_GROUPS_TABLE_ID + "/records?page_size=100"
  );
  return (gData.items || []).map((it) => ({
    record_id: it.record_id,
    name: it.fields["群名"] != null ? it.fields["群名"] : it.fields["name"],
    size: Number(it.fields["规模"] != null ? it.fields["规模"] : it.fields["size"]) || 0,
  }));
}

export async function onRequest(context) {
  const env = context.env;
  const request = context.request;
  if (request.method === "OPTIONS") return new Response(null, { status: 204 });
  if (request.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), { status: 405, headers: { "Content-Type": "application/json" } });
  }
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return new Response(JSON.stringify({ error: "bad json" }), { status: 400, headers: { "Content-Type": "application/json" } });
  }
  if (env.REDPET_WRITE_PASSWORD && body.password !== env.REDPET_WRITE_PASSWORD) {
    return new Response(JSON.stringify({ error: "密码错误" }), { status: 401, headers: { "Content-Type": "application/json" } });
  }
  if (!Array.isArray(body.groups)) {
    return new Response(JSON.stringify({ error: "groups 必须是数组" }), { status: 400, headers: { "Content-Type": "application/json" } });
  }

  const app = env.FEISHU_BITABLE_APP_TOKEN;
  const groupsTable = env.FEISHU_GROUPS_TABLE_ID;
  const dataTable = env.FEISHU_TABLE_ID;

  try {
    const current = await loadGroups(env);
    const currentNames = new Set(current.map((g) => g.name));
    const nextNames = new Set(body.groups.map((g) => g.name));

    // 新增的群
    for (const g of body.groups) {
      if (currentNames.has(g.name)) continue;
      // 配置表加一行
      await feishuCall(env, "POST", "/bitable/v1/apps/" + app + "/tables/" + groupsTable + "/records", {
        fields: { 群名: g.name, 规模: Number(g.size) || 0 },
      });
      // 活跃数据表加一个数字列
      await feishuCall(env, "POST", "/bitable/v1/apps/" + app + "/tables/" + dataTable + "/fields", {
        field_name: g.name,
        type: 2,
        property: { formatter: "0" },
      });
    }

    // 移除的群
    for (const g of current) {
      if (nextNames.has(g.name)) continue;
      // 配置表删行
      await feishuCall(env, "DELETE", "/bitable/v1/apps/" + app + "/tables/" + groupsTable + "/records/" + g.record_id, undefined);
      // 活跃数据表删列：先查字段拿到 field_id
      const fieldsData = await feishuCall(env, "GET", "/bitable/v1/apps/" + app + "/tables/" + dataTable + "/fields");
      const target = (fieldsData.items || []).find((f) => f.field_name === g.name);
      if (target) {
        await feishuCall(env, "DELETE", "/bitable/v1/apps/" + app + "/tables/" + dataTable + "/fields/" + target.field_id, undefined);
      }
    }

    // 同步规模（群名不变、size 变了也更新）
    for (const g of body.groups) {
      const match = current.find((c) => c.name === g.name);
      if (match && Number(match.size) !== Number(g.size)) {
        await feishuCall(env, "PUT", "/bitable/v1/apps/" + app + "/tables/" + groupsTable + "/records/" + match.record_id, {
          fields: { 规模: Number(g.size) || 0 },
        });
      }
    }

    return new Response(JSON.stringify({ ok: true }), { headers: { "Content-Type": "application/json" } });
  } catch (e) {
    return new Response(JSON.stringify({ error: "飞书写入失败：" + (e.message || e) }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
