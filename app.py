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

# --- タイトルと説明 ---
st.title("📸 AI Photo Story Curator")
st.markdown("""
あなたの写真フォルダから、AIが「最高の4枚」をセレクトし、ストーリーを紡ぎます。
100枚の候補からでも、一瞬で組み写真を作成します。
""")

# --- サイドバー：設定 ---
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini API Key", type="password", help="Google AI Studioで取得したキーを入力してください")
    st.markdown("[🔑 APIキーの取得はこちら](https://aistudio.google.com/app/apikey)")
    
    st.divider()
    st.info("※入力されたキーは保存されず、このセッションでのみ使用されます。")

# --- メインエリア：画像アップロード ---
uploaded_files = st.file_uploader(
    "1. 写真をアップロード (複数選択可)", 
    accept_multiple_files=True, 
    type=['jpg', 'jpeg', 'png', 'heic', 'webp']
)

if uploaded_files:
    st.success(f"{len(uploaded_files)} 枚の写真を読み込みました！")
    
    # ファイル名リスト作成
    file_names = [f.name for f in uploaded_files]
    
    # --- 核となる写真の選択 ---
    st.subheader("2. 「核」となる写真を選ぶ")
    target_name = st.selectbox(
        "この写真を軸にストーリーを作ります",
        options=file_names,
        index=0
    )
    
    # 選択された画像のプレビュー
    selected_file = next((f for f in uploaded_files if f.name == target_name), None)
    if selected_file:
        st.image(selected_file, caption="核となる写真", width=300)

    # --- 実行ボタン ---
    if st.button("🚀 3つのパターンで組み写真を作る", type="primary"):
        if not api_key:
            st.error("⚠️ 左のサイドバーでAPIキーを入力してください！")
            st.stop()
            
        # API設定
        genai.configure(api_key=api_key)
        
        # --- 処理開始 ---
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        try:
            # 一時フォルダの作成（Streamlitクラウド上での処理用）
            with tempfile.TemporaryDirectory() as temp_dir:
                status_text.text("⏳ 画像を処理しています...")
                
                # 画像を一時保存 & Geminiへアップロード
                upload_candidates = [] # AIに渡すリスト
                local_paths = {}       # 後でZIPにするためのパス辞書
                
                # 核となる写真 + ランダム24枚 (計25枚)
                seed_file = selected_file
                other_files = [f for f in uploaded_files if f.name != target_name]
                random.shuffle(other_files)
                
                # 処理対象リスト作成
                target_files = [seed_file] + other_files[:24]
                
                gemini_files = [] # AIへのプロンプト用
                
                total = len(target_files)
                
                for i, file_obj in enumerate(target_files):
                    # 進捗表示
                    progress = (i / total) * 0.5
                    progress_bar.progress(progress)
                    status_text.text(f"📤 Googleサーバーへ転送中... ({i+1}/{total})")

                    # 一時ファイルとして保存
                    file_path = os.path.join(temp_dir, file_obj.name)
                    with open(file_path, "wb") as f:
                        f.write(file_obj.getbuffer())
                    
                    # リサイズして軽量化（API用）
                    img = Image.open(file_path)
                    img.thumbnail((1024, 1024))
                    if img.mode != "RGB": img = img.convert("RGB")
                    img.save(file_path, "JPEG")
                    
                    local_paths[file_obj.name] = file_path # パスを記憶
                    
                    # アップロード
                    g_file = genai.upload_file(file_path, mime_type="image/jpeg")
                    gemini_files.append(g_file)
                    gemini_files.append(f"↑ ファイル名: {file_obj.name}")

                # --- AI生成 ---
                status_text.text("🤖 AIが3つのストーリーを構想中...")
                progress_bar.progress(0.6)

                prompt = [
                    f"あなたは世界的な写真編集者です。写真リストから、1枚目の「{target_name}」を核として、全く異なる視点の『4枚組の写真』を3パターン作成してください。",
                    "【重要】写真は必ずリストにあるものから選び、ファイル名は正確に記述すること。",
                    "",
                    "## 作成する3つのパターン",
                    "1. 【Visual Harmony】: 色彩、光、構図の美しさ、視覚的な統一感を最優先したセレクト。",
                    "2. 【Emotional Flow】: 温度、匂い、ノスタルジー、静寂など、感覚的・感情的な流れを重視したセレクト。",
                    "3. 【Narrative Story】: 時間の経過、起承転結、意味的な繋がりを重視した物語的なセレクト。",
                    "",
                    "## 出力形式 (以下のJSON形式のみを出力してください)",
                    """
                    [
                        {
                            "id": 1,
                            "theme": "Visual Harmony",
                            "files": ["file1", "file2", "file3", "file4"],
                            "story": "視覚的解説(100字)",
                            "reason": "選定理由"
                        },
                        {
                            "id": 2,
                            "theme": "Emotional Flow",
                            "files": ["file1", "file2", "file3", "file4"],
                            "story": "感情的解説(100字)",
                            "reason": "選定理由"
                        },
                        {
                            "id": 3,
                            "theme": "Narrative Story",
                            "files": ["file1", "file2", "file3", "file4"],
                            "story": "物語的解説(100字)",
                            "reason": "選定理由"
                        }
                    ]
                    """,
                    "\n--- 写真リスト ---"
                ]
                prompt.extend(gemini_files)

                # モデル自動選択ロジック
                model_name = 'gemini-1.5-flash'
                try:
                    models = [m.name for m in genai.list_models()]
                    if 'models/gemini-1.5-pro' in models: model_name = 'gemini-1.5-pro'
                    if 'models/gemini-1.5-flash' in models: model_name = 'gemini-1.5-flash'
                except: pass
                
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                
                progress_bar.progress(0.9)
                status_text.text("✨ 完成しました！")

                # JSON解析
                text_res = response.text
                try:
                    clean_json = re.search(r'\[.*\]', text_res, re.DOTALL).group()
                    patterns = json.loads(clean_json)
                except:
                    st.error("AIからの応答形式が崩れました。もう一度お試しください。")
                    st.write(text_res)
                    st.stop()
                
                progress_bar.progress(1.0)
                status_text.empty() # テキスト消去

                # --- 結果表示 (タブで切り替え) ---
                st.divider()
                st.subheader("🎉 提案された3つのプラン")
                
                tabs = st.tabs(["🎨 1. Visual Harmony", "💧 2. Emotional Flow", "📖 3. Narrative Story"])
                
                for i, tab in enumerate(tabs):
                    if i < len(patterns):
                        pat = patterns[i]
                        with tab:
                            st.markdown(f"### テーマ: {pat.get('theme')}")
                            st.info(f"**ストーリー:** {pat.get('story')}")
                            with st.expander("選定理由を見る"):
                                st.write(pat.get('reason'))
                            
                            # 画像特定
                            selected_paths = []
                            cols = st.columns(4)
                            
                            for fname in pat.get('files', []):
                                # 名前からパスを探す
                                match_name = next((n for n in local_paths.keys() if fname in n or n in fname), None)
                                if match_name:
                                    selected_paths.append(local_paths[match_name])
                            
                            # 核画像保証
                            seed_path = local_paths.get(target_name)
                            if seed_path and seed_path not in selected_paths:
                                selected_paths.insert(0, seed_path)
                            
                            # 4枚表示
                            selected_paths = selected_paths[:4]
                            
                            for idx, path in enumerate(selected_paths):
                                img = Image.open(path)
                                cols[idx].image(img, use_container_width=True, caption=f"{idx+1}")
                            
                            # ZIP作成（メモリ上で作成）
                            if selected_paths:
                                zip_buffer = io.BytesIO()
                                with zipfile.ZipFile(zip_buffer, "w") as zf:
                                    for path in selected_paths:
                                        zf.write(path, os.path.basename(path))
                                    # テキストファイル
                                    story_txt = f"テーマ: {pat.get('theme')}\n\nストーリー:\n{pat.get('story')}\n\n理由:\n{pat.get('reason')}"
                                    zf.writestr("story.txt", story_txt)
                                
                                st.download_button(
                                    label=f"📦 プラン{i+1}をダウンロード",
                                    data=zip_buffer.getvalue(),
                                    file_name=f"photo_story_plan_{i+1}.zip",
                                    mime="application/zip",
                                    type="primary"
                                )
                            else:
                                st.warning("画像が見つかりませんでした。")

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

else:
    st.info("👆 まずは上のボタンから写真をアップロードしてください（20枚〜100枚推奨）")
