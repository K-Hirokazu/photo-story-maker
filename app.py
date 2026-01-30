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

# --- カスタムCSS（ギャラリーを見やすく） ---
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        border-radius: 20px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# --- タイトル ---
st.title("📸 AI Photo Story Curator")
st.caption("アップロードした写真群から、AIが「最高の4枚」を選び出し、物語を紡ぎます。")

# --- サイドバー：設定 ---
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini API Key", type="password", help="Google AI Studioで取得したキー")
    st.markdown("[🔑 APIキー取得](https://aistudio.google.com/app/apikey)")
    st.divider()
    
    # ファイルアップローダーをサイドバーではなくメインに置くことも可能ですが、
    # 連続作成しやすくするため、アップロードは「常駐」させます。
    st.info("💡 写真を一度アップロードすれば、核となる写真を変えて何度でも生成できます。")

# --- メインエリア：アップロード ---
uploaded_files = st.file_uploader(
    "1. 写真をまとめてアップロード (20枚〜100枚推奨)", 
    accept_multiple_files=True, 
    type=['jpg', 'jpeg', 'png', 'heic', 'webp']
)

# --- メイン処理 ---
if uploaded_files:
    # --- 2. ギャラリーで核を選ぶ ---
    st.markdown("### 2. 「核」となる写真をクリックで選択")
    st.caption("この写真を中心にストーリーが構成されます。選び直せば何度でも作れます。")

    # プレビュー用画像の準備（軽量化）
    preview_imgs = []
    file_indices = []
    
    # 全部の画像を表示すると重いので、最初の30枚または全てを表示
    # ※多すぎる場合はユーザー体験を損なうため、適宜調整
    display_limit = 100 
    
    for i, f in enumerate(uploaded_files[:display_limit]):
        f.seek(0) # ファイルポインタを先頭に
        img = Image.open(f)
        img.thumbnail((150, 150)) # サムネイルサイズ
        preview_imgs.append(img)
        file_indices.append(i)

    # ★ ここが新機能：画像をクリックして選べるギャラリー ★
    selected_index = image_select(
        label="",
        images=preview_imgs,
        captions=[f.name for f in uploaded_files[:display_limit]],
        index=0,
        return_value="index",
        use_container_width=False
    )
    
    # 選ばれたファイルを取得
    target_file = uploaded_files[selected_index]
    target_name = target_file.name

    st.success(f"✅ 選択中: **{target_name}**")

    # --- 3. 生成ボタン ---
    st.markdown("### 3. ストーリー生成")
    
    if st.button("🚀 この写真で組み写真を作る", type="primary"):
        if not api_key:
            st.error("⚠️ 左のサイドバーでAPIキーを入力してください")
            st.stop()
            
        genai.configure(api_key=api_key)
        
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        try:
            # --- モデル診断 ---
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
            
            # --- 処理開始 ---
            with tempfile.TemporaryDirectory() as temp_dir:
                status_text.text(f"📤 写真を解析中... (Model: {model_name})")
                
                # 画像準備
                local_paths = {}
                seed_file = target_file
                other_files = [f for f in uploaded_files if f.name != target_name]
                random.shuffle(other_files)
                target_files = [seed_file] + other_files[:24] # 核 + ランダム24枚
                
                gemini_files = []
                total = len(target_files)
                
                for i, file_obj in enumerate(target_files):
                    progress = (i / total) * 0.5
                    progress_bar.progress(progress)
                    
                    # 毎回シークをリセットして読み込み
                    file_obj.seek(0)
                    
                    # 一時保存
                    file_path = os.path.join(temp_dir, file_obj.name)
                    with open(file_path, "wb") as f:
                        f.write(file_obj.read())
                    
                    # リサイズ
                    img = Image.open(file_path)
                    img.thumbnail((1024, 1024))
                    if img.mode != "RGB": img = img.convert("RGB")
                    img.save(file_path, "JPEG")
                    
                    local_paths[file_obj.name] = file_path
                    
                    # アップロード
                    g_file = genai.upload_file(file_path, mime_type="image/jpeg")
                    gemini_files.append(g_file)
                    gemini_files.append(f"↑ ファイル名: {file_obj.name}")

                # --- 生成 ---
                status_text.text("🧠 AIが3つのストーリーを構想中...")
                progress_bar.progress(0.6)

                prompt = [
                    f"あなたは写真編集者です。リストから「{target_name}」を核として、異なる視点の『4枚組』を3パターン作成してください。",
                    "【重要】写真はリストにあるものから選び、ファイル名は正確に記述すること。",
                    "## 作成パターン",
                    "1. 【Visual Harmony】: 色彩・構図重視",
                    "2. 【Emotional Flow】: 感情・空気感重視",
                    "3. 【Narrative Story】: 物語性重視",
                    "## 出力形式 (JSONのみ)",
                    """
                    [
                        {
                            "id": 1,
                            "theme": "Visual Harmony",
                            "files": ["file1", "file2", "file3", "file4"],
                            "story": "解説(100字)",
                            "reason": "理由"
                        },
                        {
                            "id": 2,
                            "theme": "Emotional Flow",
                            "files": ["file1", "file2", "file3", "file4"],
                            "story": "解説(100字)",
                            "reason": "理由"
                        },
                        {
                            "id": 3,
                            "theme": "Narrative Story",
                            "files": ["file1", "file2", "file3", "file4"],
                            "story": "解説(100字)",
                            "reason": "理由"
                        }
                    ]
                    """,
                    "\n--- 写真リスト ---"
                ]
                prompt.extend(gemini_files)

                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                
                progress_bar.progress(0.9)
                status_text.text("✨ 完成！")

                # 解析
                try:
                    clean_json = re.search(r'\[.*\]', response.text, re.DOTALL).group()
                    patterns = json.loads(clean_json)
                except:
                    st.error("AIの応答エラー。もう一度試してください。")
                    st.stop()
                
                progress_bar.progress(1.0)
                status_text.empty()

                # --- 結果表示 ---
                st.divider()
                st.subheader(f"🎉 「{target_name}」から生まれた物語")
                
                tabs = st.tabs(["🎨 Visual", "💧 Emotional", "📖 Story"])
                
                for i, tab in enumerate(tabs):
                    if i < len(patterns):
                        pat = patterns[i]
                        with tab:
                            st.markdown(f"**{pat.get('story')}**")
                            st.caption(f"テーマ: {pat.get('theme')} | 理由: {pat.get('reason')}")
                            
                            # 画像特定
                            paths = []
                            for fname in pat.get('files', []):
                                match = next((n for n in local_paths if fname in n or n in fname), None)
                                if match: paths.append(local_paths[match])
                            
                            if local_paths.get(target_name) and local_paths[target_name] not in paths:
                                paths.insert(0, local_paths[target_name])
                            paths = paths[:4]
                            
                            # 表示
                            cols = st.columns(4)
                            for idx, p in enumerate(paths):
                                cols[idx].image(p, use_container_width=True)
                            
                            # ダウンロード
                            if paths:
                                buf = io.BytesIO()
                                with zipfile.ZipFile(buf, "w") as z:
                                    for p in paths:
                                        z.write(p, os.path.basename(p))
                                    txt = f"テーマ: {pat.get('theme')}\n\nストーリー:\n{pat.get('story')}\n\n理由:\n{pat.get('reason')}"
                                    z.writestr("story.txt", txt)
                                
                                st.download_button(
                                    f"📦 プラン{i+1}を保存",
                                    data=buf.getvalue(),
                                    file_name=f"plan_{i+1}.zip",
                                    mime="application/zip",
                                    type="primary",
                                    key=f"dl_{i}_{target_name}" # ユニークキーでバグ防止
                                )

        except Exception as e:
            st.error(f"エラー: {e}")

else:
    st.info("👆 上のボックスに写真をドラッグ＆ドロップしてください")
