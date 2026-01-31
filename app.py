import streamlit as st
import google.generativeai as genai
from PIL import Image
from streamlit_image_select import image_select
import os
import shutil
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
    /* ダウンロードボタンのスタイル調整 */
    div[data-testid="column"] button {
        height: auto;
        min_height: 3em;
    }
</style>
""", unsafe_allow_html=True)

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

# --- メイン処理 ---
if uploaded_files:
    # --- 2. ギャラリー選択 ---
    st.markdown("### 2. 「核」となる写真を選ぶ（またはおまかせ）")
    
    preview_imgs = []
    display_limit = 100 
    
    for f in uploaded_files[:display_limit]:
        f.seek(0)
        img = Image.open(f)
        img.thumbnail((150, 150))
        preview_imgs.append(img)

    selected_index = image_select(
        label="",
        images=preview_imgs,
        captions=[f.name for f in uploaded_files[:display_limit]],
        index=0,
        return_value="index",
        use_container_width=False
    )
    
    manual_target_file = uploaded_files[selected_index]

    # --- 3. アクションボタン ---
    st.markdown("### 3. 生成スタート")
    col1, col2 = st.columns(2)
    
    target_file = None
    run_generation = False
    is_random_mode = False

    with col1:
        if st.button(f"🚀 選択した写真で作る\n({manual_target_file.name})", type="primary"):
            target_file = manual_target_file
            run_generation = True

    with col2:
        if st.button("🎲 おまかせ (ランダム) で作る"):
            target_file = random.choice(uploaded_files)
            run_generation = True
            is_random_mode = True

    # --- 生成ロジック ---
    if run_generation and target_file:
        target_name = target_file.name
        
        if is_random_mode:
            st.info(f"🎲 運命の1枚が選ばれました: **{target_name}**")
            target_file.seek(0)
            st.image(target_file, width=300, caption="AIが選んだ核となる写真")
        else:
            st.success(f"✅ 選択中: **{target_name}**")

        if not api_key:
            st.error("⚠️ 左のサイドバーでAPIキーを入力してください")
            st.stop()
            
        genai.configure(api_key=api_key)
        
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        try:
            status_text.text("🔑 AIモデルに接続中...")
            model_name = None
            try:
                available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                if any('gemini-1.5-flash' in m for m in available): model_name = 'gemini-1.5-flash'
                elif any('gemini-1.5-pro' in m for m in available): model_name = 'gemini-1.5-pro'
                elif available: model_name = available[0].replace('models/', '')
            except: pass
            
            if not model_name:
                st.error("AIモデルが見つかりません。APIキーを確認してください。")
                st.stop()
            
            with tempfile.TemporaryDirectory() as temp_dir:
                status_text.text(f"📤 写真を解析中... (Core: {target_name})")
                
                local_paths_original = {} 
                
                seed_file = target_file
                other_files = [f for f in uploaded_files if f.name != target_name]
                random.shuffle(other_files)
                target_files = [seed_file] + other_files[:24] 
                
                gemini_files = []
                total = len(target_files)
                
                for i, file_obj in enumerate(target
