import csv
import io
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
INPUT = Path(__file__).resolve().parent / "input"
OUTPUT = ROOT / "dist" / "dashboard-data.json"
YEAR = 2026


def load_cli_csv(path):
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    content = payload.get("content")
    if not isinstance(content, str):
        raise ValueError(f"{path.name} does not contain CSV content")
    return list(csv.DictReader(io.StringIO(content)))


def normalize_text(value):
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def normalize_date(value):
    text = normalize_text(value).replace("-", ".")
    match = re.search(r"(\d{1,2})\s*\.\s*(\d{1,2})", text)
    if not match:
        return None
    month, day = map(int, match.groups())
    try:
        return date(YEAR, month, day)
    except ValueError:
        return None


def parse_number(value):
    text = normalize_text(value).replace(",", "")
    if not text or text in {"、", "\\"}:
        return None
    match = re.fullmatch(r"-?\d+(?:\.\d+)?", text)
    return float(text) if match else None


def date_key(value):
    return f"{value.month}.{value.day}"


def display_date(value):
    return f"{value.month}月{value.day}日"


def week_bounds(value):
    start = value - timedelta(days=value.weekday())
    return start, start + timedelta(days=6)


def classify(values, complete):
    if sum(value >= 20 for value in values) >= 3:
        return "高活"
    if sum(value >= 10 for value in values) >= 3:
        return "活跃"
    if complete and values and all(value < 5 for value in values):
        return "低活"
    return "普通"


def longest_low_streak(values):
    longest = current = 0
    for value in values:
        if value < 5:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


daily_rows = load_cli_csv(INPUT / "daily-counts.csv")
size_rows = load_cli_csv(INPUT / "sizes.csv")

if not daily_rows:
    raise ValueError("The daily activity table is empty")

date_columns = []
for column in daily_rows[0].keys():
    parsed = normalize_date(column)
    if column and parsed and parsed not in [item[1] for item in date_columns]:
        date_columns.append((column, parsed))
date_columns.sort(key=lambda item: item[1])

groups = []
for row in daily_rows:
    name = normalize_text(row.get("群名"))
    if not name:
        continue
    history = {parsed: parse_number(row.get(column)) for column, parsed in date_columns}
    groups.append({"name": name, "history": history})

if not groups:
    raise ValueError("No community rows were found")

size_columns = []
if size_rows:
    for column in size_rows[0].keys():
        parsed = normalize_date(column)
        if column and parsed:
            size_columns.append((column, parsed))
    size_columns.sort(key=lambda item: item[1], reverse=True)

sizes = {}
for row in size_rows:
    name = normalize_text(row.get("群名"))
    if not name:
        continue
    size = None
    for column, _ in size_columns:
        value = parse_number(row.get(column))
        if value is not None:
            size = int(value)
            break
    sizes[name] = size

daily_totals = {}
effective_dates = []
for _, current_date in date_columns:
    values = [group["history"].get(current_date) for group in groups]
    numeric = [value for value in values if value is not None]
    total = sum(numeric)
    daily_totals[current_date] = total
    if numeric and total > 0:
        effective_dates.append(current_date)

if not effective_dates:
    raise ValueError("No effective statistical dates were found")

latest_date = max(effective_dates)
earliest_date = min(effective_dates)

period_map = {}
for current_date in effective_dates:
    half = 1 if current_date.day <= 15 else 2
    period_map.setdefault((current_date.year, current_date.month, half), []).append(current_date)
period_keys = sorted(period_map)

periods = []
for year, month, half in period_keys:
    dates = sorted(period_map[(year, month, half)])
    daily = [daily_totals[current_date] for current_date in dates]
    periods.append({
        "key": f"{year}-{month:02d}-H{half}",
        "label": f"{month}月{'上' if half == 1 else '下'}半月",
        "dates": [date_key(current_date) for current_date in dates],
        "effectiveDays": len(dates),
        "dailyAverage": round(sum(daily) / len(daily), 1),
    })

latest_window_dates = effective_dates[-5:]
previous_window_dates = effective_dates[-10:-5]
if len(latest_window_dates) < 5:
    raise ValueError("At least 5 effective statistical dates are required")

def window_label(dates):
    return f"{dates[0].month}/{dates[0].day}—{dates[-1].month}/{dates[-1].day}"

result_groups = []
for group in groups:
    period_averages = []
    for key in period_keys:
        dates = period_map[key]
        values = [group["history"].get(current_date) for current_date in dates]
        period_averages.append(round(sum(value or 0 for value in values) / len(dates), 1))

    latest_values = [group["history"].get(current_date) or 0 for current_date in latest_window_dates]
    previous_values = [group["history"].get(current_date) or 0 for current_date in previous_window_dates]
    current_tier = classify(latest_values, True)
    previous_tier = classify(previous_values, True) if len(previous_values) == 5 else None
    low_streak = longest_low_streak(latest_values)
    warning = current_tier == "普通" and low_streak >= 3
    change = round(period_averages[-1] - period_averages[-2], 1) if len(period_averages) >= 2 else 0.0
    result_groups.append({
        "name": group["name"],
        "size": sizes.get(group["name"]),
        "periodAverages": period_averages,
        "change": change,
        "tier": current_tier,
        "warning": warning,
        "previousTier": previous_tier,
        "lowStreak": low_streak,
        "latest": int(group["history"].get(latest_date) or 0),
        "latestWindow": latest_values,
    })

tier_order = ["高活", "活跃", "普通", "低活"]
tier_counts = {tier: sum(group["tier"] == tier for group in result_groups) for tier in tier_order}
warning_count = sum(group["warning"] for group in result_groups)

high_groups = sorted(
    [group for group in result_groups if group["tier"] == "高活"],
    key=lambda group: group["periodAverages"][-1],
    reverse=True,
)
active_targets = sorted(
    [group for group in result_groups if group["tier"] == "活跃"],
    key=lambda group: group["periodAverages"][-1],
    reverse=True,
)
low_groups = sorted(
    [group for group in result_groups if group["tier"] == "低活"],
    key=lambda group: group["periodAverages"][-1],
)
warning_groups = sorted(
    [group for group in result_groups if group["warning"]],
    key=lambda group: (-group["lowStreak"], group["periodAverages"][-1]),
)

comparable = [group for group in result_groups if len(group["periodAverages"]) >= 2]
rising = sorted(comparable, key=lambda group: group["change"], reverse=True)[:4]
falling = sorted(comparable, key=lambda group: group["change"])[:4]

trend_change = None
if len(periods) >= 2 and periods[-2]["dailyAverage"]:
    trend_change = round((periods[-1]["dailyAverage"] / periods[-2]["dailyAverage"] - 1) * 100, 1)

trend_dates = effective_dates[-15:]
trend_daily = [{"label": f"{current_date.month}/{current_date.day}", "value": daily_totals[current_date]} for current_date in trend_dates]

output = {
    "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
    "source": "企业微信在线表格",
    "rangeLabel": f"{display_date(earliest_date)}—{display_date(latest_date)}",
    "effectiveDays": len(effective_dates),
    "latestDate": display_date(latest_date),
    "latestWindow": {
        "label": window_label(latest_window_dates),
        "effectiveDays": len(latest_window_dates),
        "dates": [date_key(current_date) for current_date in latest_window_dates],
    },
    "tierCounts": tier_counts,
    "warningCount": warning_count,
    "periods": periods,
    "trendChangePercent": trend_change,
    "trendDaily": trend_daily,
    "groups": result_groups,
    "focus": {
        "high": [group["name"] for group in high_groups],
        "activeTargets": [group["name"] for group in active_targets[:4]],
        "low": [group["name"] for group in low_groups],
        "warning": [group["name"] for group in warning_groups],
    },
    "changes": {
        "rising": [{"name": group["name"], "change": group["change"]} for group in rising],
        "falling": [{"name": group["name"], "change": group["change"]} for group in falling],
    },
    "dataQuality": {
        "excludedDates": [date_key(current_date) for current_date, total in daily_totals.items() if total == 0],
        "groupCount": len(result_groups),
        "namesMatch": {group["name"] for group in groups}.issubset(set(sizes)),
        "extraSizeOnlyGroups": sorted(set(sizes) - {group["name"] for group in groups}),
    },
}

OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "latestDate": output["latestDate"],
    "effectiveDays": output["effectiveDays"],
    "tierCounts": tier_counts,
    "warningCount": warning_count,
    "high": output["focus"]["high"],
    "low": output["focus"]["low"],
    "warning": output["focus"]["warning"],
    "periods": periods,
    "namesMatch": output["dataQuality"]["namesMatch"],
}, ensure_ascii=False, indent=2))
