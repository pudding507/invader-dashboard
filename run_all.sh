#!/bin/bash
# Invader 看板一键刷新(需连 VPN):抓数 → 渲染。渲染完再用 Claude 把 preview_artifact.html 发布到同一个链接。
set -e
cd "$(dirname "$0")"
python3 fetch_db.py
python3 render_dashboard.py
echo "完成。线上:https://claude.ai/artifact/WWgs4prtcmJz6rfuoBaXmt(发布 preview_artifact.html 到该链接)"
