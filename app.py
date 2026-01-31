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
    
    # プレビュー画像の準備
    preview_imgs = []
    display_limit = 100 
    
    for f in uploaded_files[:display_limit]:
        f.seek(0)
        img = Image.open(f)
        img.thumbnail((150, 150))
        preview_imgs.append(img)

    # ギャラリー表示
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
            # モデル診断
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
            
            # --- 画像処理 ---
            with tempfile.TemporaryDirectory() as temp_dir:
                status_text.text(f"📤 写真を解析中... (Core: {target_name})")
                
                # パス管理用辞書
                local_paths_original = {} # 高画質用（ダウンロード用）
                local_paths_resized = {}  # AI用（アップロード用）
                
                seed_file = target_file
                other_files = [f for f in uploaded_files if f.name != target_name]
                random.shuffle(other_files)
                target_files = [seed_file] + other_files[:24] 
                
                gemini_files = []
                total = len(target_files)
                
                for i, file_obj in enumerate(target_files):
                    progress = (i / total) * 0.5
                    progress_bar.progress(progress)
                    
                    file_obj.seek(0)
                    
                    # 1. まずオリジナル（高画質）を保存
                    original_path = os.path.join(temp_dir, f"original_{file_obj.name}")
                    with open(original_path, "wb") as f:
                        f.write(file_obj.read())
                    
                    local_paths_original[file_obj.name] = original_path # ダウンロード用リストに登録

                    # 2. AI用にリサイズ版を作成
                    resized_path = os.path.join(temp_dir, f"resized_{file_obj.name}")
                    img = Image.open(original_path)
                    img.thumbnail((1024, 1024)) # AIには1024pxで十分
                    if img.mode != "RGB": img = img.convert("RGB")
                    img.save(resized_path, "JPEG")
                    
                    # 3. リサイズ版をアップロード
                    g_file = genai.upload_file(resized_path, mime_type="image/jpeg")
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
                            
                            # 画像特定（ここではオリジナル画質のパスを取得！）
                            paths = []
                            for fname in pat.get('files', []):
                                match = next((n for n in local_paths_original if fname in n or n in fname), None)
                                if match: paths.append(local_paths_original[match])
                            
                            # 核となる写真が抜けていたら追加
                            seed_original_path = local_paths_original.get(target_name)
                            if seed_original_path and seed_original_path not in paths:
                                paths.insert(0, seed_original_path)
                            paths = paths[:4]
                            
                            # プレビュー表示
                            cols = st.columns(4)
                            for idx, p in enumerate(paths):
                                # 表示用には少し軽くして読み込む（ブラウザ負荷軽減）
                                img_preview = Image.open(p)
                                img_preview.thumbnail((800, 800)) 
                                cols[idx].image(img_preview, use_container_width=True)
                            
                            # ダウンロード（ここ重要：オリジナルファイルをZIPにする）
                            if paths:
                                buf = io.BytesIO()
                                with zipfile.ZipFile(buf, "w") as z:
                                    for p in paths:
                                        # 元のファイル名で保存
                                        # ファイルパスは 'temp/original_IMG_123.jpg' だが、
                                        # ZIPの中では 'IMG_123.jpg' に戻す処理
                                        clean_name = os.path.basename(p).replace("original_", "")
                                        z.write(p, clean_name)
                                    
                                    txt = f"テーマ: {pat.get('theme')}\n\nストーリー:\n{pat.get('story')}\n\n理由:\n{pat.get('reason')}"
                                    z.writestr("story.txt", txt)
                                
                                st.download_button(
                                    f"📦 プラン{i+1}を保存 (高画質)",
                                    data=buf.getvalue(),
                                    file_name=f"plan_{i+1}.zip",
                                    mime="application/zip",
                                    type="primary",
                                    key=f"dl_{i}_{target_name}"
                                )

        except Exception as e:
            st.error(f"エラー: {e}")

else:
    st.info("👆 上のボックスに写真をドラッグ＆ドロップしてください")
