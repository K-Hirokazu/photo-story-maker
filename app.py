import streamlit as st
import google.generativeai as genai
from PIL import Image
from streamlit_image_select import image_select
import os
import json
import re
import zipfile
import io
import random
import tempfile

# --- ページ設定 ---
st.set_page_config(
    page_title="AI Photo Story Curator",
    page_icon="📸",
    layout="wide"
)

# --- カスタムCSS ---
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        border-radius: 20px;
        font-weight: bold;
        height: 3em;
    }
    div[data-testid="column"] button {
        height: auto;
        min_height: 3em;
    }
</style>
""", unsafe_allow_html=True)

# --- セッション状態の初期化 ---
if 'patterns' not in st.session_state:
    st.session_state.patterns = None
if 'target_name' not in st.session_state:
    st.session_state.target_name = None
if 'generated_mode' not in st.session_state:
    st.session_state.generated_mode = None # "manual" or "random"

# --- タイトル ---
st.title("📸 AI Photo Story Curator")
st.caption("アップロードした写真群から、AIが「最高の4枚」を選び出し、物語を紡ぎます。")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini API Key", type="password", help="Google AI Studioで取得したキー")
    st.markdown("[🔑 APIキー取得](https://aistudio.google.com/app/apikey)")
    st.divider()
    st.info("💡 写真を一度アップロードすれば、何度でも生成できます。")

# --- メインエリア：アップロード ---
uploaded_files = st.file_uploader(
    "1. 写真をまとめてアップロード (20枚〜100枚推奨)", 
    accept_multiple_files=True, 
    type=['jpg', 'jpeg', 'png', 'heic', 'webp']
)

# --- 関数: 名前からファイルオブジェクトを取得 ---
def get_file_by_name(name, file_list):
    for f in file_list:
        if f.name == name:
            f.seek(0)
            return f
    return None

# --- メイン処理 ---
if uploaded_files:
    # --- 2. ギャラリー選択 ---
    st.markdown("### 2. 「核」となる写真を選ぶ（またはおまかせ）")
    
    preview_imgs = []
    display_limit = 100 
    file_names = [f.name for f in uploaded_files[:display_limit]]

    for f in uploaded_files[:display_limit]:
        f.seek(0)
        img = Image.open(f)
        img.thumbnail((150, 150))
        preview_imgs.append(img)

    # ギャラリー表示
    selected_index = image_select(
        label="",
        images=preview_imgs,
        captions=file_names,
        index=0,
        return_value="index",
        use_container_width=False
    )
    
    manual_target_file = uploaded_files[selected_index]

    # --- 3. アクションボタン ---
    st.markdown("### 3. 生成スタート")
    col1, col2 = st.columns(2)
    
    start_generation = False
    selected_target = None
    is
