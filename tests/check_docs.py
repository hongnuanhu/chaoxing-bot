#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档自检：相对链接是否都存在、页内锚点是否能解析到标题。

跑法：python tests/check_docs.py
CI 的 docs job 会调用它。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def slug(title: str) -> str:
    """近似 GitHub 的标题锚点生成规则：小写、去标点、空格转连字符。"""
    t = title.replace("`", "").strip().lower()
    t = re.sub(r"[^\w\s-]", "", t)          # \w 含中文
    return re.sub(r"\s+", "-", t)


def main() -> int:
    mds = sorted(ROOT.glob("*.md")) + sorted(ROOT.glob("docs/*.md"))
    errors = []

    for md in mds:
        text = md.read_text(encoding="utf-8")
        rel = md.relative_to(ROOT)

        heads = {slug(h) for h in re.findall(r"^#{1,6}\s+(.+)$", text, flags=re.M)}

        for label, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text):
            t = target.strip()
            if t.startswith(("http://", "https://", "mailto:")):
                continue
            if t.startswith("#"):
                if t[1:] and t[1:] not in heads:
                    errors.append(f"{rel}: 锚点失效 [{label}] -> {t}")
                continue
            path_part = t.split("#")[0]
            if not path_part:
                continue
            if not (md.parent / path_part).exists():
                errors.append(f"{rel}: 文件不存在 [{label}] -> {t}")

        # README 里的 <img src="..."> 也要检查
        for src in re.findall(r'<img[^>]+src="([^"]+)"', text):
            if src.startswith(("http://", "https://")):
                continue
            if not (md.parent / src).exists():
                errors.append(f"{rel}: 图片不存在 -> {src}")

    print(f"检查 {len(mds)} 个 markdown 文件")
    for p in mds:
        print(f"  · {p.relative_to(ROOT)}")

    if errors:
        print(f"\n✖ 发现 {len(errors)} 个问题：")
        for e in errors:
            print("  ", e)
        return 1

    print("\n✔ 相对链接、图片、页内锚点全部有效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
