#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RedPet 社群助手 —— 数据同步入口（统一管线）

职责：
  把「数据来源」转换成 build_dashboard_data.py 需要的输入文件
  （work/wecom-sync/input/daily-counts.csv、sizes.csv，均为 JSON 包裹的 CSV），
  然后调用 build_dashboard_data.py 重新生成 dist/dashboard-data.json。

两种来源（mode）：
  local  从本机桌面的两份 xlsx 读取（当前可用，无需额外授权）
  wecom  从企业微信在线表格读取（需要机器人具备表格读取权限 + 两张表的 docid）

判定规则、四档汇总、低活预警等逻辑全部在 build_dashboard_data.py 中实现，
本脚本只负责「取数 + 落盘输入文件」，不改动任何业务判定。

用法：
  python sync.py local
  python sync.py wecom
  python sync.py local --check        # 仅生成输入并校验，不覆盖 dist
"""
import csv
import io
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = Path(__file__).resolve().parent / "input"
BUILD = Path(__file__).resolve().parent / "build_dashboard_data.py"

DESKTOP = Path.home() / "Desktop"
ACTIVITY_XLSX = DESKTOP / "每日活跃数量整理【内】.xlsx"
SIZES_XLSX = DESKTOP / "社群活跃度每日记录.xlsx"

ACTIVITY_SHEET = "工作表1"
SIZES_SHEET = "规模"

def _find_node():
    """定位 node 可执行文件。子进程里裸命令 node 可能解析不到，这里优先用绝对路径。"""
    import os as _os
    import shutil as _sh
    for cand in (_os.environ.get("WECOM_NODE"),
                 r"C:\Users\21894\.workbuddy\binaries\node\versions\22.22.2\node.exe",
                 r"C:\Node\node.exe"):
        if cand and _os.path.exists(cand):
            return cand
    return _sh.which("node") or "node"


WECOM_CLI = [
    _find_node(),
    str(ROOT / "work" / "wecom-cli-runtime" / "node_modules" / "@wecom" / "cli" / "bin" / "wecom.js"),
]


# ---------- 文本 / 日期 / 数字 归一化 ----------
def norm_text(value):
    return unicodedata.normalize("NFKC", str(value if value is not None else "")).strip()


def norm_date(value):
    text = norm_text(value).replace("-", ".")
    match = re.search(r"(\d{1,2})\s*\.\s*(\d{1,2})", text)
    if not match:
        return None
    try:
        return (int(match.group(1)), int(match.group(2)))
    except ValueError:
        return None


def parse_num(value):
    text = norm_text(value).replace(",", "")
    if not text or text in {"、", "\\"}:
        return None
    match = re.fullmatch(r"-?\d+(?:\.\d+)?", text)
    return float(text) if match else None


# ---------- 读取本机 xlsx ----------
def load_xlsx(path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import inspect_xlsx
    return inspect_xlsx.inspect(str(path))


def xlsx_sheet_rows(path, sheet_title):
    data = load_xlsx(path)
    sheet = next((s for s in data["sheets"] if s["title"] == sheet_title), None)
    if sheet is None:
        raise SystemExit(f"未找到工作表「{sheet_title}」：{path.name}")
    return sheet["rows"]


def xlsx_to_input(path, sheet_title, out_name):
    rows = xlsx_sheet_rows(path, sheet_title)
    if not rows:
        raise SystemExit(f"{path.name} 的「{sheet_title}」没有任何数据行")
    header = rows[0]["values"]
    date_cols = []
    for idx, h in enumerate(header):
        if idx == 0:
            continue
        dd = norm_date(h)
        if dd:
            date_cols.append((idx, f"{dd[0]}.{dd[1]}"))

    out_rows = [["群名"] + [label for _, label in date_cols]]
    count = 0
    for r in rows[1:]:
        vals = r["values"]
        name = norm_text(vals[0]) if vals else ""
        if not name:
            continue
        row = [name]
        for idx, _ in date_cols:
            v = vals[idx] if idx < len(vals) else None
            n = parse_num(v)
            row.append("" if n is None else int(n))
        out_rows.append(row)
        count += 1

    content = "\n".join(",".join(str(c) for c in row) for row in out_rows)
    (INPUT / out_name).write_text(
        json.dumps({"content": content}, ensure_ascii=False), encoding="utf-8"
    )
    return count


# ---------- 从企业微信在线表格读取 ----------
def wecom_run(args, out_path=None):
    cmd = WECOM_CLI + args
    # ⚠️ 必须显式指定 utf-8：Windows 计划任务环境下默认编码是 GBK，
    #    不指定会把 CLI 的 UTF-8 输出读成乱码/空串，导致下游 json.loads(None) 崩溃。
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise SystemExit(f"wecom 命令失败：{' '.join(cmd)}\n{res.stderr.strip()}")
    if out_path:
        Path(out_path).write_text(res.stdout, encoding="utf-8")
    return res.stdout


def wecom_sheet_id(doc_id, sheet_title):
    meta = json.loads(wecom_run(["sheet", "get", "--docid", doc_id]))
    for s in meta.get("sheets", []):
        if s.get("title") == sheet_title:
            return s["sheet_id"]
    raise SystemExit(f"在线表格 {doc_id} 中未找到工作表「{sheet_title}」")


def wecom_to_input(doc_id, sheet_title, out_name):
    sheet_id = wecom_sheet_id(doc_id, sheet_title)
    tmp = INPUT / f"_{out_name}.csv"
    wecom_run(
        ["sheet", "ranges", "get", "--docid", doc_id, "--sheet-id", sheet_id,
         "--mode", "csv"],
        out_path=str(tmp),
    )
    text = tmp.read_text(encoding="utf-8-sig")
    # 企微 CLI 返回的是 JSON 包裹的 CSV，需要先把 content 取出来
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and isinstance(obj.get("content"), str):
            text = obj["content"]
    except Exception:
        pass
    reader = list(csv.reader(io.StringIO(text)))
    try:
        tmp.unlink(missing_ok=True)  # 临时文件，删不掉也不影响流程
    except OSError:
        pass
    if not reader:
        raise SystemExit(f"在线表格 {doc_id} 读取为空")
    header = reader[0]
    date_cols = []
    for idx, h in enumerate(header):
        if idx == 0:
            continue
        dd = norm_date(h)
        if dd:
            date_cols.append((idx, f"{dd[0]}.{dd[1]}"))
    out_rows = [["群名"] + [label for _, label in date_cols]]
    count = 0
    for vals in reader[1:]:
        name = norm_text(vals[0]) if vals else ""
        if not name:
            continue
        row = [name]
        for idx, _ in date_cols:
            n = parse_num(vals[idx]) if idx < len(vals) else None
            row.append("" if n is None else int(n))
        out_rows.append(row)
        count += 1
    content = "\n".join(",".join(str(c) for c in row) for row in out_rows)
    (INPUT / out_name).write_text(
        json.dumps({"content": content}, ensure_ascii=False), encoding="utf-8"
    )
    return count


# ---------- 构建 + 校验 ----------
def run_build():
    res = subprocess.run(
        [sys.executable, str(BUILD)], capture_output=True, text=True, cwd=str(ROOT)
    )
    if res.returncode != 0:
        raise SystemExit(f"build_dashboard_data.py 执行失败：\n{res.stderr.strip()}")
    return res.stdout


def verify():
    data = json.loads((ROOT / "dist" / "dashboard-data.json").read_text(encoding="utf-8"))
    tiers = data["tierCounts"]
    total = sum(tiers.values())
    groups = data["dataQuality"]["groupCount"]
    ok = total == groups
    print(f"校验：四档汇总={total}  社群总数={groups}  {'OK' if ok else '不一致！'}")
    if not ok:
        raise SystemExit("四档总数与社群总数不一致，请检查输入数据")
    return data


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "local"
    check_only = "--check" in sys.argv

    if mode == "local":
        n1 = xlsx_to_input(ACTIVITY_XLSX, ACTIVITY_SHEET, "daily-counts.csv")
        n2 = xlsx_to_input(SIZES_XLSX, SIZES_SHEET, "sizes.csv")
        print(f"local 取数完成：活跃表 {n1} 个群，规模表 {n2} 个群")
    elif mode == "wecom":
        doc_activity = os.environ.get("WECHAT_DOC_ACTIVITY")
        doc_sizes = os.environ.get("WECHAT_DOC_SIZES")
        if not doc_activity or not doc_sizes:
            raise SystemExit(
                "wecom 模式需要环境变量 WECHAT_DOC_ACTIVITY 与 WECHAT_DOC_SIZES（两张在线表格的 docid 或链接）"
            )
        n1 = wecom_to_input(doc_activity, ACTIVITY_SHEET, "daily-counts.csv")
        n2 = wecom_to_input(doc_sizes, SIZES_SHEET, "sizes.csv")
        print(f"wecom 取数完成：活跃表 {n1} 个群，规模表 {n2} 个群")
    else:
        raise SystemExit(f"未知 mode：{mode}（应为 local 或 wecom）")

    if check_only:
        print("check 模式：跳过 dist 生成")
        return

    summary = run_build()
    print(summary)
    verify()
    print("同步完成，dist/dashboard-data.json 已更新。")


import os  # noqa: E402  (used by wecom mode env lookup)


if __name__ == "__main__":
    main()
