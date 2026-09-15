#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RedPet 社群看板 · 每日自动同步 + 发布

用途：供 Windows 任务计划程序调用，独立于 WorkBuddy 运行。
取数模式由环境变量 SYNC_MODE 决定：
    local  读本机桌面两份 xlsx（默认，当前可用）
    wecom  读企业微信在线表格（需机器人文档权限 + WECHAT_DOC_ACTIVITY / WECHAT_DOC_SIZES）

红线：绝不修改 dist/index.html（看板 UI）与图标文件，只重生成 dashboard-data.json 并发布。
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
DOCS = os.path.join(ROOT, "docs")
LOG = os.path.join(ROOT, "work", "auto_publish.log")
PYEXE = r"C:\Users\21894\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

# 企业微信在线表格（wecom 模式）。留空则回退到 local（读桌面 xlsx）
DEFAULT_DOC_ACTIVITY = "e3_AYoArwaLAKUCNSKpCxDAbSvGbPbav"   # 每日活跃数量整理【内】
DEFAULT_DOC_SIZES = "e3_AYoArwaLAKUCNLArIWOxiQGusD3v9"      # 社群活跃度每日记录

PUBLISH_FILES = [
    "index.html",
    "dashboard-data.json",
    "assistant-icon.jpg",
    "icon-32.png",
    "icon-180.png",
    "icon-192.png",
    "icon-512.png",
    "manifest.webmanifest",
]


GITHUB_REPO = "2189446851/redpet-assistant"
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".config", "redpet", "github_token")


def get_github_token():
    """取推送用的 token：优先独立文件，其次从 git remote URL 里提取。绝不写进仓库。"""
    try:
        if os.path.exists(TOKEN_FILE):
            t = open(TOKEN_FILE, encoding="utf-8").read().strip()
            if t:
                return t
    except Exception:
        pass
    try:
        out = subprocess.run(["git", "remote", "get-url", "origin"],
                             cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout or ""
        m = re.search(r"https://([^@\s]+)@github\.com", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def push_via_api():
    """git 网络不通时的兜底：直接调 GitHub API 推文件（api.github.com 通常可达）。"""
    tok = get_github_token()
    if not tok:
        log("API 兜底失败：找不到 token")
        return False

    def api(path, method="GET", data=None, timeout=45):
        req = urllib.request.Request("https://api.github.com" + path, method=method)
        req.add_header("Authorization", "token " + tok)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "redpet")
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
        if body:
            req.add_header("Content-Type", "application/json")
        try:
            r = urllib.request.urlopen(req, body, timeout=timeout)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode("utf-8", "replace")
            except Exception:
                return e.code, ""
        except Exception as e:
            return -1, str(e)

    base = "/repos/" + GITHUB_REPO + "/contents/"
    msg = "daily sync %s (api fallback)" % datetime.date.today().strftime("%Y-%m-%d")
    ok = True
    for name in PUBLISH_FILES:
        fp = os.path.join(DOCS, name)
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, "rb") as f:
                content = f.read()
        except Exception as e:
            log("  读取失败 %s: %s" % (name, e))
            continue
        rel = "docs/" + name
        st, body = api(base + rel)
        sha = None
        if st == 200:
            try:
                sha = json.loads(body).get("sha")
            except Exception:
                sha = None
        payload = {"message": msg,
                   "content": __import__("base64").b64encode(content).decode("ascii")}
        if sha:
            payload["sha"] = sha
        # 单个文件偶发网络异常(st=-1)，重试 2 次
        st = -1
        for _attempt in range(3):
            st, body = api(base + rel, "PUT", payload)
            if st in (200, 201):
                break
            try:
                import time as _tt
                _tt.sleep(3)
            except Exception:
                pass
        log("  API 推送 %s -> %s" % (rel, st))
        if st not in (200, 201):
            ok = False
    return ok


def log(msg=""):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(cmd):
    env = dict(os.environ)
    # 计划任务的系统环境里可能没有 node（sync.py 用裸命令 node 调企微 CLI）
    for d in (os.path.join(ROOT, "work", "bin"),
              r"C:\Users\21894\.workbuddy\binaries\node\versions\22.22.2",
              r"C:\Node"):
        if os.path.isdir(d) and d not in env.get("PATH", ""):
            env["PATH"] = d + os.pathsep + env.get("PATH", "")
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        cmd, cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", shell=False,
    )


def tail(text, n=600):
    text = (text or "").strip()
    return text[-n:] if len(text) > n else text


def main():
    log("=" * 46)
    log("auto_publish 开始")
    mode = os.environ.get("SYNC_MODE", "wecom").strip().lower()
    if mode not in ("local", "wecom"):
        mode = "wecom"
    if mode == "wecom":
        os.environ.setdefault("WECHAT_DOC_ACTIVITY", DEFAULT_DOC_ACTIVITY)
        os.environ.setdefault("WECHAT_DOC_SIZES", DEFAULT_DOC_SIZES)
    log("取数模式: %s" % mode)

    # 1) 同步数据（只重生成 dist/dashboard-data.json）
    #    wecom 模式下偶发失败（网络抖动 / 子进程环境差异），失败自动重试 3 次
    max_try = 3 if mode == "wecom" else 1
    r = None
    for attempt in range(1, max_try + 1):
        r = run([PYEXE, os.path.join("work", "wecom-sync", "sync.py"), mode])
        log("第 %d 次取数 rc=%s" % (attempt, r.returncode))
        if r.returncode == 0:
            break
        if attempt < max_try:
            log("取数失败，20 秒后重试（%d/%d）" % (attempt, max_try))
            try:
                import time as _t
                _t.sleep(20)
            except Exception:
                pass
    log("sync 输出尾部: " + tail(r.stdout if r else ""))
    if r is None or r.returncode != 0:
        log("同步失败(rc=%s)，终止发布" % r.returncode)
        log("stderr: " + tail(r.stderr))
        if mode == "wecom":
            node = r"C:\Users\21894\.workbuddy\binaries\node\versions\22.22.2\node.exe"
            if not os.path.exists(node):
                node = "node"
            wjs = os.path.join(ROOT, "work", "wecom-cli-runtime", "node_modules", "@wecom", "cli", "bin", "wecom.js")
            d = run([node, wjs, "sheet", "get", "--docid",
                     os.environ.get("WECHAT_DOC_ACTIVITY", "")])
            log("CLI诊断 rc=%s" % d.returncode)
            log("CLI诊断 stdout: " + tail(d.stdout, 400))
            log("CLI诊断 stderr: " + tail(d.stderr, 400))
        return 1

    # 2) 拷贝到发布目录 docs/（原样拷贝，不编辑内容）
    os.makedirs(DOCS, exist_ok=True)
    copied = []
    for name in PUBLISH_FILES:
        src = os.path.join(DIST, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(DOCS, name))
            copied.append(name)
    log("已拷贝发布文件: %s" % ", ".join(copied))

    # 3) 提交
    add_args = ["git", "add"] + ["dist/dashboard-data.json"] + ["docs/" + n for n in copied]
    r = run(add_args)
    if r.returncode != 0:
        log("git add 失败: " + tail(r.stderr))
        return 1

    r = run(["git", "diff", "--cached", "--quiet"])
    if r.returncode == 0:
        log("数据无变化，今日未提交")
        return 0

    today = datetime.date.today().strftime("%Y-%m-%d")
    r = run(["git", "commit", "-m", "daily sync %s" % today])
    if r.returncode != 0:
        log("git commit 失败: " + tail(r.stderr))
        return 1
    log("已提交")

    # 4) 推送（三级兜底：直连 -> 本机代理 -> GitHub API）
    #    先拉远端：云端 Actions 可能已经推过，不拉会 rejected (fetch first)
    log("先同步远端最新提交...")
    pr = run(["git", "pull", "--rebase", "origin", "main"])
    if pr.returncode != 0:
        log("git pull 失败(rc=%s)，尝试直连推送，失败会走后续兜底" % pr.returncode)
        run(["git", "rebase", "--abort"])

    r = run(["git", "push", "origin", "main"])
    if r.returncode == 0:
        log("已推送（直连），GitHub Pages 将在约 1 分钟内自动重新部署")
        log("auto_publish 完成")
        return 0

    log("直连推送失败，尝试走代理")
    r2 = run(["git", "-c", "http.https://github.com.proxy=http://127.0.0.1:7890",
              "push", "origin", "main"])
    if r2.returncode == 0:
        log("已推送（代理），GitHub Pages 将在约 1 分钟内自动重新部署")
        log("auto_publish 完成")
        return 0

    log("代理推送也失败，改用 GitHub API 兜底推送")
    try:
        if push_via_api():
            log("已推送（API 兜底），GitHub Pages 将在约 1 分钟内自动重新部署")
            log("auto_publish 完成")
            return 0
    except Exception as e:
        log("API 兜底异常: %s" % e)

    log("三种方式均失败，已本地提交，待网络恢复")
    log("stderr: " + tail(r2.stderr))
    return 1
    log("auto_publish 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
