#!/usr/bin/env python3
"""Build blog/*.html from blog/posts/*.md via pandoc, then regenerate blog/index.html."""

import html
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BLOG = ROOT / "blog"
POSTS = BLOG / "posts"
TEMPLATE = BLOG / "_template.html"

INDEX = """<!DOCTYPE html>
<html lang="zh-CN">

<head>
    <meta charset="utf-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="Wanqing Chen - 技术博客（Agent / RAG / Flink / JVM）">
    <meta name="author" content="Wanqing Chen">

    <title>博客 - Wanqing Chen</title>

    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet"
        integrity="sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN" crossorigin="anonymous">

    <link href="../navbar.css" rel="stylesheet">
    <link href="../sticky-footer-navbar.css" rel="stylesheet">
</head>

<body id="page-top" data-bs-spy="scroll" data-bs-target="#navbar">

    <nav class="navbar navbar-expand-lg navbar-light bg-light">
        <div class="container">
            <a class="navbar-brand" href="../index.html">@</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbar"
                aria-controls="navbar" aria-expanded="false" aria-label="Toggle navigation">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div id="navbar" class="collapse navbar-collapse">
                <ul class="navbar-nav me-auto mb-2 mb-lg-0">
                    <li class="nav-item"><a class="nav-link" href="../index.html">首页</a></li>
                    <li class="nav-item"><a class="nav-link" href="../publication.html">作品</a></li>
                    <li class="nav-item"><a class="nav-link active" aria-current="page" href="index.html">博客</a></li>
                    <li class="nav-item"><a class="nav-link" href="../technology.html">技术</a></li>
                    <li class="nav-item"><a class="nav-link" href="https://github.com/chenwanqing1024" target="_blank">项目</a></li>
                    <li class="nav-item"><a class="nav-link" href="../about.html">关于</a></li>
                </ul>
                <form class="d-flex" role="search" action="https://www.google.com/search" method="GET" target="_blank">
                    <input type="hidden" name="sitesearch" value="chenwanqing1024.github.io">
                    <input class="form-control me-2" type="search" name="q" placeholder="关键词" aria-label="Search">
                    <button class="btn btn-outline-success" type="submit">搜索</button>
                </form>
                <ul class="navbar-nav">
                    <li class="nav-item"><a class="nav-link active" aria-current="page" href="index.html">中文</a></li>
                    <li class="nav-item"><a class="nav-link" href="../en/blog/index.html">EN</a></li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container">
        <p>
            <i>
                关于 Agent 架构、RAG 流水线、大数据基础设施的工程笔记，以及读到的好文章的摘要与评述。
            </i>
        </p>
    </div>

    <div class="container">

        <div class="card border-info mb-3">
            <div class="card-header">
                <h2>文章</h2>
            </div>
            <div class="card-body">
{entries}
            </div>
        </div>

        <footer class="footer mt-auto py-3 bg-light">
            <div class="container">
                <p class="text-muted">最后更新：{updated}</p>
            </div>
        </footer>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"
        integrity="sha384-C6RzsynM9kWDrMNeT87bh95OGNyZPhcTNXj1NW7RuBCsyN/o0jlpcV2MPK8M2HN" crossorigin="anonymous"></script>

</body>

</html>
"""

EMPTY = '                <p class="text-muted">暂无文章。</p>'


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        sys.exit(f"{path.name}: missing YAML frontmatter")
    _, raw, _ = text.split("---", 2)
    meta = yaml.safe_load(raw) or {}
    for key in ("title", "date"):
        if key not in meta:
            sys.exit(f"{path.name}: frontmatter missing required key '{key}'")
    return meta


def render(meta, slug):
    e = html.escape
    tags = "".join(
        f'<span class="badge bg-secondary">{e(str(t))}</span> ' for t in meta.get("tags", [])
    )
    badge = ' <span class="badge bg-info text-dark">读文笔记</span>' if meta.get("source-url") else ""
    summary = f'<p class="mb-1">{e(meta["summary"])}</p>' if meta.get("summary") else ""
    return (
        '                <div class="mb-4">\n'
        f'                    <h5 class="mb-1"><a href="{slug}.html">{e(meta["title"])}</a>{badge}</h5>\n'
        f'                    <p class="text-muted mb-1"><small>{e(str(meta["date"]))} {tags}</small></p>\n'
        f"                    {summary}\n"
        "                </div>"
    )


def main():
    if not POSTS.is_dir():
        sys.exit(f"missing {POSTS}")

    posts = sorted(POSTS.glob("*.md"), key=lambda p: p.name, reverse=True)
    entries = []

    for post in posts:
        meta = frontmatter(post)
        slug = post.stem
        subprocess.run(
            ["pandoc", str(post), "--from", "markdown", "--to", "html5",
             "--template", str(TEMPLATE), "--standalone",
             "--output", str(BLOG / f"{slug}.html")],
            check=True,
        )
        entries.append(render(meta, slug))
        print(f"built {slug}.html")

    updated = max((str(frontmatter(p)["date"]) for p in posts), default="")
    (BLOG / "index.html").write_text(
        INDEX.format(entries="\n".join(entries) or EMPTY, updated=updated),
        encoding="utf-8",
    )
    print(f"built index.html ({len(posts)} posts)")


if __name__ == "__main__":
    main()
