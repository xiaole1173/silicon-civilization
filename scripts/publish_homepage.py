#!/usr/bin/env python3
"""发布个人主页到 GitHub Pages（用本机 GCM 里已保存的凭据，全程不打印任何令牌）。

流程：确认仓库 -> 没有就创建(Public) -> git push(main) -> 开启 Pages -> 轮询线上地址
用法：python scripts/publish_homepage.py [--yes]
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

OWNER = "xiaole1173"
REPO = "xiaole1173.github.io"
SITE_DIR = r"D:\classvibecoding\github_homepage"
SITE_URL = f"https://{OWNER}.github.io/"
GIT_PROXY = "http://127.0.0.1:7897"


def git(*args, **kw):
    return subprocess.run(["git", "-C", SITE_DIR, *args], capture_output=True, text=True, **kw)


def token():
    p = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
    )
    info = dict(line.split("=", 1) for line in p.stdout.strip().splitlines() if "=" in line)
    tok = info.get("password", "")
    if not tok:
        sys.exit("没有拿到 GitHub 凭据（GCM 里没有 github.com 的登录信息）")
    return tok


TOK = None


def api(path, method="GET", data=None):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        method=method,
        data=(json.dumps(data).encode() if data is not None else None),
        headers={
            "Authorization": "Bearer " + TOK,
            "User-Agent": "dsh",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except Exception:
            body = {}
        return e.code, body


def step(msg):
    print("[*] " + msg, flush=True)


def main():
    global TOK
    TOK = token()

    st, body = api(f"/repos/{OWNER}/{REPO}")
    if st == 200:
        step(f"仓库已存在：{OWNER}/{REPO}（private={body.get('private')}）")
        if body.get("private"):
            sys.exit("仓库是私有的 —— GitHub Pages 需要 Public，请先在 Settings 里改成公开")
    elif st == 404:
        step(f"创建公开仓库 {OWNER}/{REPO} …")
        st, body = api("/user/repos", "POST", {
            "name": REPO,
            "private": False,
            "description": "个人主页 · Personal homepage (GitHub Pages)",
            "has_issues": False,
            "has_wiki": False,
            "has_projects": False,
            "auto_init": False,
        })
        if st not in (200, 201):
            sys.exit(f"创建仓库失败：HTTP {st} {body.get('message', '')} —— 可能是凭据没有 repo 权限，改为手动创建同名公开仓库即可")
        step("仓库已创建")
    else:
        sys.exit(f"查询仓库失败：HTTP {st}")

    step("推送 main …")
    git("remote", "remove", "origin")
    git("remote", "add", "origin", f"https://github.com/{OWNER}/{REPO}.git")
    r = git("-c", f"http.proxy={GIT_PROXY}", "-c", f"https.proxy={GIT_PROXY}",
            "push", "-u", "origin", "main", "--force")
    if r.returncode != 0:
        sys.exit("推送失败：\n" + r.stdout + r.stderr)

    step("开启 Pages（main / root）…")
    st, body = api(f"/repos/{OWNER}/{REPO}/pages")
    payload = {"source": {"branch": "main", "path": "/"}}
    if st == 200:
        st, body = api(f"/repos/{OWNER}/{REPO}/pages", "PUT", payload)
        step(f"更新 Pages 设置：HTTP {st}")
    else:
        st, body = api(f"/repos/{OWNER}/{REPO}/pages", "POST", payload)
        step(f"创建 Pages 站点：HTTP {st}")
    if st not in (200, 201, 204):
        print("  Pages API 未成功（可能凭据没有 Pages 权限）：", json.dumps(body, ensure_ascii=False)[:300])

    step("等待线上生效（最多 10 分钟）…")
    for i in range(40):
        time.sleep(15)
        try:
            req = urllib.request.Request(SITE_URL, headers={"User-Agent": "dsh"})
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", "ignore")
            ok = "蔡朝彬" in html
            print(f"  {SITE_URL} -> HTTP 200，内容校验：{'通过' if ok else '页面已通但内容待确认'}")
            if ok:
                print("发布完成")
                return
        except Exception as e:
            print(f"  第 {i + 1} 次：还没好（{type(e).__name__}）")
    print("超时：站点可能仍在构建，稍后手动打开看看")


if __name__ == "__main__":
    main()
