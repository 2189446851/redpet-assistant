# -*- coding: utf-8 -*-
"""
把企微表格复制出来的 TSV 转成看板内嵌数据，并 patch 进 docs/index.html。
用法: python sync_build_data.py <counts_tsv> <scale_tsv> <repo_root>
"""
import json, re, sys, io, datetime, os

FW = str.maketrans("０１２３４５６７８９．", "0123456789.")

def norm_date(h):
    """'8.2４数量' / '9-12数量 ' / '9月18日' / '8.7人数' -> '2026-08-24'"""
    t = h.strip().translate(FW)
    m = re.search(r"(\d{1,2})\s*[.\-月]\s*(\d{1,2})\s*日?", t)
    if not m:
        return None
    return "2026-%02d-%02d" % (int(m.group(1)), int(m.group(2)))

def norm_num(v):
    t = (v or "").strip().translate(FW)
    if t in ("", "\\", "-", "—"):
        return None
    try:
        return int(float(t))
    except ValueError:
        return None

# 用户确认该周为建表时历史堆入、非当日真实数，永久排除（避免每次同步又把 8/7 加回来）
SKIP_DATES = {"2026-08-07"}

def parse_tsv(path, with_size_col=None):
    rows = open(path, encoding="utf-8").read().splitlines()
    rows = [r for r in rows if r.strip()]
    header = rows[0].split("\t")
    dates = [d for d in (norm_date(h) for h in header[1:]) if d and d not in SKIP_DATES]
    groups, records = [], {}
    for line in rows[1:]:
        cells = line.split("\t")
        name = cells[0].strip()
        if not name:
            continue
        groups.append(name)
        for i, dt in enumerate(dates):
            v = norm_num(cells[i + 1] if i + 1 < len(cells) else "")
            if v is None:
                continue
            records.setdefault(dt, {})[name] = v
    return groups, records

def main():
    counts_tsv = sys.argv[1]
    scale_tsv = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    repo = sys.argv[-1]
    act_groups, act_records = parse_tsv(counts_tsv)
    have_scale = bool(scale_tsv and os.path.exists(scale_tsv))
    sc_groups, sc_records = (parse_tsv(scale_tsv) if have_scale else ([], {}))
    # 群列表以活跃度表为准；规模表补充最新人数当 size
    latest_scale_date = sorted(sc_records.keys())[-1] if sc_records else None
    def size_of(name):
        if latest_scale_date:
            for d in sorted(sc_records.keys(), reverse=True):
                if name in sc_records[d]:
                    return sc_records[d][name]
        return None
    groups = [{"name": n, "size": size_of(n)} for n in act_groups]
    daily = {
        "version": 1,
        "updatedAt": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds"),
        "note": "数据来自企微表格「每日活跃数量整理」自动同步；后续每日由面板填写或同步追加。",
        "groups": groups,
        "records": act_records,
    }
    idx_path = repo + "/docs/index.html"
    html = open(idx_path, encoding="utf-8").read()
    html, n1 = re.subn(r"const EMBEDDED_DAILY_DATA=\{.*?\};",
                       "const EMBEDDED_DAILY_DATA=" + json.dumps(daily, ensure_ascii=False, separators=(",", ":")) + ";",
                       html, count=1, flags=re.S)
    if have_scale:
        scale = {
            "version": 1,
            "updatedAt": daily["updatedAt"],
            "note": "数据来自企微表格「社群活跃度每日记录-规模」自动同步。",
            "groups": [{"name": n, "size": size_of(n)} for n in (sc_groups or act_groups)],
            "records": sc_records,
        }
        html, n2 = re.subn(r"const EMBEDDED_SCALE_DATA=\{.*?\};",
                           "const EMBEDDED_SCALE_DATA=" + json.dumps(scale, ensure_ascii=False, separators=(",", ":")) + ";",
                           html, count=1, flags=re.S)
        assert n2 == 1, "scale patch failed"
    else:
        n2 = 0
    assert n1 == 1, "daily patch failed"
    open(idx_path, "w", encoding="utf-8", newline="\n").write(html)
    json.dump(daily, open(repo + "/docs/data/daily.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("groups:", len(groups), "| activity dates:", len(act_records),
          "(%s ~ %s)" % (min(act_records), max(act_records)),
          "| scale:", ("updated %d dates" % len(sc_records)) if have_scale else "未提供，保持不变")

if __name__ == "__main__":
    main()
