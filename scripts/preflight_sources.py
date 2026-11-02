"""Probe the official sources from the machine that will publish the feeds.

GitHub-hosted runners sit in Azure datacentres, and both formula1.com and fia.com
apply bot protection that can reject a datacentre IP while allowing a home
connection. Whether the pipeline can scrape from CI is therefore measured, never
assumed: this script is the first step of the workflow and reports a table.

By default it only reports. ``--strict`` turns a failure into a non-zero exit for
callers that want a hard gate.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MINIMUM_BODY_BYTES = 2000
# 机房 IP 被风控时通常返回一个「人机校验」页，状态码可能仍是 200。
CHALLENGE_MARKERS = (
    b"Just a moment",
    b"cf-challenge",
    b"Attention Required",
    b"Enable JavaScript and cookies to continue",
    b"Checking your browser",
)


@dataclass(frozen=True, slots=True)
class Probe:
    """One source the pipeline depends on."""

    label: str
    url: str


PROBES: tuple[Probe, ...] = (
    Probe("Formula 1 官方赛历", "https://www.formula1.com/en/racing/2026"),
    Probe("Formula 1 成绩索引", "https://www.formula1.com/en/results/2026/races"),
    Probe("FIA 文件库", "https://www.fia.com/documents"),
)


def probe(client: httpx.Client, item: Probe) -> tuple[bool, str]:
    """Return whether the page looks genuine, plus a short reason."""
    try:
        response = client.get(item.url)
    except httpx.HTTPError as error:
        return False, f"网络不可达（{type(error).__name__}）"
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}"
    size = len(response.content)
    if size < MINIMUM_BODY_BYTES:
        return False, f"响应仅 {size} 字节，疑似风控/拦截页"
    for marker in CHALLENGE_MARKERS:
        if marker in response.content:
            return False, "命中风控校验页（人机验证）"
    return True, f"HTTP {response.status_code}，{size} 字节"


def main() -> int:
    """Run every probe and print a Markdown table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Append the table to this file (usually $GITHUB_STEP_SUMMARY)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any source is unreachable",
    )
    args = parser.parse_args()

    rows: list[tuple[str, bool, str]] = []
    with httpx.Client(
        timeout=httpx.Timeout(25.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    ) as client:
        for item in PROBES:
            ok, detail = probe(client, item)
            rows.append((item.label, ok, detail))
            print(f"[{'PASS' if ok else 'FAIL'}] {item.label}: {detail}")

    failed = [label for label, ok, _ in rows if not ok]
    print(f"RESULT: {'READY' if not failed else 'BLOCKED ' + ', '.join(failed)}")

    summary_path = args.summary or os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = ["| 数据源 | 结果 | 详情 |", "| --- | --- | --- |"]
        lines += [f"| {label} | {'✅' if ok else '❌'} | {detail} |" for label, ok, detail in rows]
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    if args.strict and failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
