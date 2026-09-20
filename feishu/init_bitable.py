# -*- coding: utf-8 -*-
"""REDPET 看板 · 飞书多维表格自动初始化脚本

作用：自动建好两张表 + 19 个群的字段 + 19 行社群配置，并把 3 个关键 ID 打印出来。
用法：
  1) 把下面的 APP_ID / APP_SECRET 填上；
  2) APP_TOKEN：如果已经在飞书里手动建过一个空多维表格，把地址栏里的 appXXXX 填进来；
     留空则脚本尝试自动新建一个多维表格（若报权限不足，就手动建一个空的再把 token 填进来）；
  3) 运行：
     C:\\Users\\21894\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe feishu\\init_bitable.py
"""
import json
import sys
import urllib.request
import urllib.error

APP_ID = "在这里填 App ID"
APP_SECRET = "在这里填 App Secret"
APP_TOKEN = ""  # 已有空多维表格的 appXXXX，留空则尝试自动新建

GROUPS = [
    ("猫猫托儿所1群", 499), ("猫猫托儿所2群", 434), ("猫猫托儿所3群", 0),
    ("猫猫总裁办1群", 500), ("猫猫总裁办2群", 500), ("猫猫总裁办3群", 472),
    ("猫猫总裁办4群", 487), ("猫猫总裁办5群", 310), ("猫猫总裁办6群", 0),
    ("猫猫养老院1群", 483),
    ("狗狗托儿所", 431), ("狗狗托儿所2群", 0), ("狗狗总裁办1群", 499),
    ("狗狗总裁办2群", 500), ("狗狗养老院", 294),
    ("科学养宠社1群", 497), ("户外遛宠社", 424), ("户外遛宠社2群", 0),
    ("萌宠美颜社", 322),
]

BASE = "https://open.feishu.cn/open-apis"


def req(method, path, body=None, token=None):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": -1, "msg": str(e)}


def add_field(app_token, table_id, name, ftype, prop=None):
    body = {"field_name": name, "type": ftype}
    if prop:
        body["property"] = prop
    rr = req("POST", "/bitable/v1/apps/%s/tables/%s/fields" % (app_token, table_id), body, token)
    if rr.get("code") != 0:
        print("   [警告] 字段 %s 创建失败：%s" % (name, rr.get("msg")))
    return rr


def clear_default_fields(app_token, table_id, token):
    fd = req("GET", "/bitable/v1/apps/%s/tables/%s/fields" % (app_token, table_id), None, token)
    for f in fd.get("data", {}).get("items", []):
        req("DELETE", "/bitable/v1/apps/%s/tables/%s/fields/%s" % (app_token, table_id, f["field_id"]), None, token)


def main():
    global token
    t = req("POST", "/auth/v3/tenant_access_token/internal", {"app_id": APP_ID, "app_secret": APP_SECRET})
    if t.get("code") != 0:
        print("取 token 失败：", t)
        sys.exit(1)
    token = t["tenant_access_token"]
    print("[OK] 已取得访问凭证\n")

    app_token = APP_TOKEN.strip()
    if not app_token:
        c = req("POST", "/bitable/v1/apps", {"name": "REDPET社群数据"}, token)
        if c.get("code") != 0:
            print("自动新建多维表格失败：", c)
            print(">>> 请先在飞书里手动新建一个空多维表格，把地址栏 appXXXX 填到脚本的 APP_TOKEN，再跑一次。")
            sys.exit(1)
        app_token = c["data"]["app"]["app_token"]
        print("[OK] 已自动创建多维表格：%s\n" % app_token)

    r1 = req("POST", "/bitable/v1/apps/%s/tables" % app_token, {"table": {"name": "每日活跃数据"}}, token)
    if r1.get("code") != 0:
        print("建表1失败：", r1)
        sys.exit(1)
    t1 = r1["data"]["table_id"]
    print("[OK] 表1「每日活跃数据」 table_id = %s" % t1)
    clear_default_fields(app_token, t1, token)
    add_field(app_token, t1, "日期", 5)
    for g, _ in GROUPS:
        add_field(app_token, t1, g, 2, {"formatter": "0"})
    add_field(app_token, t1, "更新时间", 5)
    add_field(app_token, t1, "填写人", 1)
    print("[OK] 表1 字段完成：日期 + 19 个群(数字) + 更新时间 + 填写人\n")

    r2 = req("POST", "/bitable/v1/apps/%s/tables" % app_token, {"table": {"name": "社群配置"}}, token)
    if r2.get("code") != 0:
        print("建表2失败：", r2)
        sys.exit(1)
    t2 = r2["data"]["table_id"]
    print("[OK] 表2「社群配置」 table_id = %s" % t2)
    clear_default_fields(app_token, t2, token)
    add_field(app_token, t2, "群名", 1)
    add_field(app_token, t2, "规模", 2, {"formatter": "0"})

    records = [{"fields": {"群名": g, "规模": s}} for g, s in GROUPS]
    rr = req("POST", "/bitable/v1/apps/%s/tables/%s/records/batch_create" % (app_token, t2), {"records": records}, token)
    if rr.get("code") != 0:
        print("[警告] 写入社群配置失败：", rr)
    else:
        print("[OK] 社群配置已写入 19 行\n")

    print("=" * 46)
    print("把这三个值填进 EdgeOne 环境变量：")
    print("FEISHU_BITABLE_APP_TOKEN = %s" % app_token)
    print("FEISHU_TABLE_ID          = %s" % t1)
    print("FEISHU_GROUPS_TABLE_ID   = %s" % t2)
    print("=" * 46)


if __name__ == "__main__":
    main()
