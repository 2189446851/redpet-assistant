#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RedPet 社群助手 —— 企微在线表格读表 → 产出 TSV（供 scripts/sync_build_data.py patch 页面）

mode:
  wecom  从企业微信在线表格读取（GitHub Actions 用，需密钥库凭证）
        产出 work/wecom-sync/output/daily.tsv 与 scale.tsv（tab 分隔，
        首行: 群名\\t8.10\\t8.11...；首列群名，其余列数值），
        交给 scripts/sync_build_data.py 写入 docs/index.html 内嵌变量。

判定规则、四档汇总、趋势等全部在页面端 computeModel 内实现，
本脚本只负责「从企微取数 + 落盘 TSV」，不改动任何业务判定。

用法:
  python sync.py wecom
"""
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "output"

ACTIVITY_SHEET = "工作表1"
SIZES_SHEET = "规模"


def _find_node():
    """定位 node 可执行文件。子进程里裸命令 node 可能解析不到，这里优先用绝对路径。"""
    for cand in (os.environ.get("WECOM_NODE"),
                 r"C:\Users\21894\.workbuddy\binaries\node\versions\22.22.2\node.exe",
                 r"C:\Node\node.exe"):
        if cand and os.path.exists(cand):
            return cand
    return shutil.which("node") or "node"


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
    return (int(match.group(1)), int(match.group(2)))


def parse_num(value):
    text = norm_text(value).replace(",", "")
    if not text or text in {"、", "\\"}:
        return None
    match = re.fullmatch(r"-?\d+(?:\.\d+)?", text)
    return float(text) if match else None


# ---------- 从企业微信在线表格读取 ----------
def wecom_run(args, out_path=None):
    # ⚠️ 必须显式指定 utf-8：Windows/CI 环境下默认编码可能是 GBK，
    #    不指定会把 CLI 的 UTF-8 输出读成乱码/空串，导致下游 json.loads(None) 崩溃。
    res = subprocess.run(WECOM_CLI + args, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise SystemExit(f"wecom 命令失败：{' '.join(WECOM_CLI + args)}\n{res.stderr.strip()}")
    if out_path:
        Path(out_path).write_text(res.stdout, encoding="utf-8")
    return res.stdout


def wecom_sheet_id(doc_id, sheet_title):
    meta = json.loads(wecom_run(["sheet", "get", "--docid", doc_id]))
    for s in meta.get("sheets", []):
        if s.get("title") == sheet_title:
            return s["sheet_id"]
    raise SystemExit(f"在线表格 {doc_id} 中未找到工作表「{sheet_title}」")


def wecom_to_tsv(doc_id, sheet_title, out_name):
    sheet_id = wecom_sheet_id(doc_id, sheet_title)
    tmp = OUT / f"_{out_name}.raw"
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
    try:
        tmp.unlink(missing_ok=True)  # 临时文件，删不掉也不影响流程
    except OSError:
        pass
    reader = list(csv.reader(io.StringIO(text)))
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
    if not date_cols:
        raise SystemExit(f"在线表格 {doc_id} 未识别到任何「月.日」日期列")
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
    OUT.mkdir(parents=True, exist_ok=True)
    content = "\n".join("\t".join(str(c) for c in row) for row in out_rows)
    (OUT / out_name).write_text(content, encoding="utf-8")
    return count


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "wecom"
    if mode != "wecom":
        raise SystemExit(f"仅支持 wecom 模式，收到：{mode}（local 模式已移除，请直接复制 TSV 跑 sync_build_data.py）")

    doc_activity = os.environ.get("WECHAT_DOC_ACTIVITY")
    doc_sizes = os.environ.get("WECHAT_DOC_SIZES")
    if not doc_activity or not doc_sizes:
        raise SystemExit(
            "wecom 模式需要环境变量 WECHAT_DOC_ACTIVITY 与 WECHAT_DOC_SIZES（两张在线表格的 docid 或链接）"
        )
    n1 = wecom_to_tsv(doc_activity, ACTIVITY_SHEET, "daily.tsv")
    n2 = wecom_to_tsv(doc_sizes, SIZES_SHEET, "scale.tsv")
    print(f"wecom 取数完成：活跃表 {n1} 个群，规模表 {n2} 个群 → {OUT}")


if __name__ == "__main__":
    main()
