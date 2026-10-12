"""受保护的轻量演示入口；仅合成数据，不读取本机历史或调用模型。"""
from pathlib import Path

import streamlit as st

from frontend.share_access import require_share_access

st.set_page_config(page_title='低空安全可信研判', page_icon='🛰', layout='wide')
st.markdown('''<style>
[data-testid="stHeader"] {display:none;}
.block-container {padding-top:2rem;padding-bottom:3rem;max-width:1400px;}
[data-testid="stElementToolbar"] {display:none;}
div[data-testid="stMetric"] {background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:14px 18px;}
.pill {display:inline-block;padding:2px 12px;border-radius:999px;font-size:13px;font-weight:700;margin-right:6px;}
.honest {border:1px dashed #cbd5e1;border-radius:10px;padding:12px 16px;background:#f8fafc;line-height:1.7;}
h1,h2,h3 {line-height:1.5;overflow:visible;}
@media(max-width:768px) {.block-container {padding:1.25rem 1rem;}}
</style>''', unsafe_allow_html=True)

# Fail closed before importing any application data or audit views.
require_share_access()

from frontend.public_demo_view import render_public_demo

project_root = Path(__file__).resolve().parent
demo_root = project_root / 'deploy/public_demo'
if not demo_root.is_dir():
    demo_root = project_root
render_public_demo(demo_root, project_root / 'rules')
