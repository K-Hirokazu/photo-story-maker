import streamlit as st
import google.generativeai as genai
from PIL import Image
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

# --- タイトル ---
st.title("📸 AI Photo Story Curator")
st.markdown("あなたの写真フォルダから、AIが「最高の4枚」をセレクトし、ストーリーを紡ぎます。")

# --- サイドバー：設定 ---
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini API Key", type="password", help="Google AI Studioで取得したキーを入力してください")
    st.markdown("[🔑 APIキーの取得はこちら](https://aistudio.google.com/app/apikey)")
    st.divider()
    st.info("※キーは保存されず、この場でのみ使用されます。")

# --- メイン：アップロード ---
uploaded_files = st.file_uploader(
    "1. 写真をアップロード (20枚以上推奨)", 
    accept_multiple_files=True, 
    type=['jpg', 'jpeg', 'png', 'heic', 'webp']
)

if uploaded_files:
    st.success(f"{len(uploaded_files)} 枚の写真を読み込みました！")
    file_names = [f.name for f in uploaded_files]
    
    st.subheader("2. 「核」となる写真を選ぶ")
    target_name = st.selectbox("この写真を軸にします", options=file_names)
    
    # プレビュー
    selected_file = next((f for f in uploaded_files if f.name == target_name), None)
    if selected_file:
        st.image(selected_file, width=300)

    # --- 実行ボタン ---
    if st.button("🚀 3つのパターンで作る", type="primary"):
        if not api_key:
            st.error("⚠️ 左のサイドバーでAPIキーを入力してください")
            st.stop()
            
        genai.configure(api_key=api_key)
        
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        try:
            # --- 1. モデル診断（ここを追加！） ---
            status_text.text("🔑 最適なAIモデルを探しています...")
            model_name = None
            try:
                available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                # 優先順位: Flash -> Pro -> その他
                if any('gemini-1.5-flash' in m for m in available): 
                    model_name = 'gemini-1.5-flash'
                elif any('gemini-1.5-pro' in m for m in available): 
                    model_name = 'gemini-1.5-pro'
                elif available: 
                    model_name = available[0].replace('models/', '')
            except Exception as e:
                st.error(f"モデル検索エラー: {e}")
                st.stop()
                
            if not model_name:
                st.error("使えるAIモデルが見つかりませんでした。APIキーを確認してください。")
                st.stop()
            
            # --- 2. 処理開始 ---
            with tempfile.TemporaryDirectory() as temp_dir:
                status_text.text(f"🤖 モデル {model_name} で画像を処理中...")
                
                # 画像準備
                local_paths = {}
                seed_file = selected_file
                other_files = [f for f in uploaded_files if f.name != target_name]
                random.shuffle(other_files)
                target_files = [seed_file] + other_files[:24] # 計25枚
                
                gemini_files = []
                total = len(target_files)
                
                for i, file_obj in enumerate(target_files):
                    progress = (i / total) * 0.5
                    progress_bar.progress(progress)
                    
                    # 一時保存
                    file_path = os.path.join(temp_dir, file_obj.name)
                    with open(file_path, "wb") as f:
                        f.write(file_obj.getbuffer())
                    
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

                # --- 3. 生成 ---
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
                    st.write(response.text)
                    st.stop()
                
                progress_bar.progress(1.0)
                status_text.empty()

                # --- 結果表示 ---
                st.divider()
                st.subheader("🎉 3つのプラン")
                
                tabs = st.tabs(["🎨 Visual", "💧 Emotional", "📖 Story"])
                
                for i, tab in enumerate(tabs):
                    if i < len(patterns):
                        pat = patterns[i]
                        with tab:
                            st.caption(f"テーマ: {pat.get('theme')}")
                            st.write(f"**{pat.get('story')}**")
                            with st.expander("選定理由"):
                                st.write(pat.get('reason'))
                            
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
                                    type="primary"
                                )

        except Exception as e:
            st.error(f"エラー: {e}")
