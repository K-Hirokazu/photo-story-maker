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
import uuid
import base64

# --- ページ設定 ---
st.set_page_config(
    page_title="AI Photo Story Curator",
    page_icon="📸",
    layout="wide"
)

# --- 画像をbase64（文字列）に変換する関数 ---
def img_to_base64(img_path):
    with open(img_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

# --- カスタムCSS（見た目の調整） ---
st.markdown("""
<style>
    /* ボタンデザイン */
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

    /* --- X（Twitter）風 2x2グリッド --- */
    .twitter-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr 1fr;
        gap: 2px;
        width: 100%;
        max-width: 600px; /* PCでも大きくなりすぎないように制限 */
        margin: 0 auto;   /* 中央寄せ */
        aspect-ratio: 16 / 9; /* 全体の比率 */
        border-radius: 12px;
        overflow: hidden;
    }
    
    /* スマホ表示の調整 */
    @media (max-width: 640px) {
        .twitter-grid {
            aspect-ratio: 3 / 2; /* スマホでは少し高さを出す */
            width: 100% !important;
        }
    }

    /* 画像のトリミング設定 */
    .grid-item {
        width: 100%;
        height: 100%;
        position: relative;
    }
    .grid-item img {
        width: 100%;
        height: 100%;
        object-fit: cover; /* 枠いっぱいにトリミング */
        display: block;
    }
</style>
""", unsafe_allow_html=True)

# --- セッション状態の管理 ---
if 'patterns' not in st.session_state:
    st.session_state.patterns = None
if 'target_name' not in st.session_state:
    st.session_state.target_name = None
if 'gen_id' not in st.session_state:
    st.session_state.gen_id = str(uuid.uuid4())
if 'local_paths' not in st.session_state:
    st.session_state.local_paths = {}
# 一時ディレクトリをセッションで保持する（消えないように）
if 'temp_dir_obj' not in st.session_state:
    st.session_state.temp_dir_obj = None

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
    is_random = False

    result_area = st.empty()

    with col1:
        if st.button(f"🚀 選択した写真で作る\n({manual_target_file.name})", type="primary"):
            selected_target = manual_target_file
            start_generation = True
            is_random = False
            result_area.empty()

    with col2:
        if st.button("🎲 おまかせ (ランダム) で作る"):
            selected_target = random.choice(uploaded_files)
            start_generation = True
            is_random = True
            result_area.empty()

    # --- 生成ロジック ---
    if start_generation and selected_target:
        
        target_name = selected_target.name

        if not api_key:
            st.error("⚠️ 左のサイドバーでAPIキーを入力してください")
            st.stop()

        if is_random:
            st.info(f"🎲 おまかせ抽選の結果... **{target_name}** が選ばれました！")
            selected_target.seek(0)
            st.image(selected_target, width=300, caption="運命の1枚")
        else:
            st.success(f"✅ 選択された写真: **{target_name}**")

        genai.configure(api_key=api_key)
        
        status_text = st.empty()
        progress_bar = st.progress(0)

        try:
            status_text.text("🔑 AIモデルに接続中...")
            # モデル診断
            model_name = 'gemini-1.5-flash' # デフォルト
            try:
                available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                if any('gemini-1.5-flash' in m for m in available): model_name = 'gemini-1.5-flash'
                elif any('gemini-1.5-pro' in m for m in available): model_name = 'gemini-1.5-pro'
            except: pass
            
            # ディレクトリ管理
            if st.session_state.temp_dir_obj:
                st.session_state.temp_dir_obj.cleanup()
            st.session_state.temp_dir_obj = tempfile.TemporaryDirectory()
            temp_dir = st.session_state.temp_dir_obj.name
            
            st.session_state.local_paths = {} # パス辞書リセット

            status_text.text(f"📤 写真を解析中... (Core: {target_name})")
            
            seed_file = selected_target
            other_files = [f for f in uploaded_files if f.name != target_name]
            random.shuffle(other_files)
            target_files = [seed_file] + other_files[:24]
            
            gemini_files = []
            total = len(target_files)
            
            # --- 画像処理ループ ---
            for i, file_obj in enumerate(target_files):
                progress = (i / total) * 0.5
                progress_bar.progress(progress)
                
                file_obj.seek(0)
                
                # 1. オリジナル保存（表示・DL用）
                orig_path = os.path.join(temp_dir, file_obj.name)
                with open(orig_path, "wb") as f:
                    f.write(file_obj.read())
                st.session_state.local_paths[file_obj.name] = orig_path

                # 2. AI用リサイズ
                resized_path = os.path.join(temp_dir, f"resized_{file_obj.name}")
                img = Image.open(orig_path)
                img.thumbnail((1024, 1024))
                if img.mode != "RGB": img = img.convert("RGB")
                img.save(resized_path, "JPEG")
                
                # 3. アップロード
                g_file = genai.upload_file(resized_path, mime_type="image/jpeg")
                gemini_files.append(g_file)
                gemini_files.append(f"↑ ファイル名: {file_obj.name}")

            status_text.text("🧠 AIがストーリーを構想中...")
            progress_bar.progress(0.7)

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
            
            try:
                clean_json = re.search(r'\[.*\]', response.text, re.DOTALL).group()
                st.session_state.gen_id = str(uuid.uuid4())
                st.session_state.patterns = json.loads(clean_json)
                st.session_state.target_name = target_name
            except:
                st.error("AIの応答エラー。もう一度試してください。")
                st.stop()

            progress_bar.progress(1.0)
            status_text.empty()

        except Exception as e:
            st.error(f"エラー: {e}")


    # --- 4. 結果表示エリア ---
    if st.session_state.patterns and st.session_state.local_paths:
        with result_area.container():
            st.divider()
            st.subheader(f"🎉 「{st.session_state.target_name}」から生まれた物語")
            
            patterns = st.session_state.patterns
            tabs = st.tabs(["🎨 Visual", "💧 Emotional", "📖 Story"])
            unique_id = st.session_state.gen_id
            local_paths = st.session_state.local_paths

            for i, tab in enumerate(tabs):
                if i < len(patterns):
                    pat = patterns[i]
                    with tab:
                        st.markdown(f"**{pat.get('story')}**")
                        st.caption(f"テーマ: {pat.get('theme')} | 理由: {pat.get('reason')}")
                        
                        # パス解決
                        target_paths = []
                        seed_path = local_paths.get(st.session_state.target_name)
                        
                        for name in pat.get('files', []):
                            for fname, fpath in local_paths.items():
                                if name in fname or fname in name:
                                    if fname != st.session_state.target_name:
                                        target_paths.append(fpath)
                                        break
                        
                        if seed_path: target_paths.insert(0, seed_path)
                        target_paths = target_paths[:4]

                        # --- ★ X風 2x2 グリッド表示 ---
                        if len(target_paths) == 4:
                            st.markdown("#### 📱 プレビュー (2x2)")
                            b64_imgs = [img_to_base64(p) for p in target_paths]
                            
                            html_grid = f"""
                            <div class="twitter-grid">
                                <div class="grid-item"><img src="data:image/jpeg;base64,{b64_imgs[0]}"></div>
                                <div class="grid-item"><img src="data:image/jpeg;base64,{b64_imgs[1]}"></div>
                                <div class="grid-item"><img src="data:image/jpeg;base64,{b64_imgs[2]}"></div>
                                <div class="grid-item"><img src="data:image/jpeg;base64,{b64_imgs[3]}"></div>
                            </div>
                            """
                            st.markdown(html_grid, unsafe_allow_html=True)
                        
                        st.divider()

                        # --- 従来の一覧表示（サイズ調整済み） ---
                        st.markdown("#### 🖼️ 全体表示")
                        cols = st.columns(4)
                        for idx, fpath in enumerate(target_paths):
                            img_prev = Image.open(fpath)
                            # use_container_width=True でスマホ対応、PCでは自動調整
                            cols[idx].image(img_prev, use_container_width=True)

                        # --- ダウンロード ---
                        st.divider()
                        st.markdown("#### 📥 ダウンロード")
                        col_dl1, col_dl2 = st.columns(2)
                        text_content = f"テーマ: {pat.get('theme')}\n\nストーリー:\n{pat.get('story')}\n\n理由:\n{pat.get('reason')}"

                        if target_paths:
                            # 1. オリジナル
                            buf_orig = io.BytesIO()
                            with zipfile.ZipFile(buf_orig, "w") as z:
                                for fpath in target_paths:
                                    z.write(fpath, os.path.basename(fpath))
                                z.writestr("story.txt", text_content)
                            
                            col_dl1.download_button(
                                f"📦 オリジナル画質\n(元サイズ)",
                                data=buf_orig.getvalue(),
                                file_name=f"orig_{i+1}.zip",
                                mime="application/zip",
                                key=f"dl_orig_{i}_{unique_id}"
                            )

                            # 2. SNS用
                            buf_sns = io.BytesIO()
                            with zipfile.ZipFile(buf_sns, "w") as z:
                                for fpath in target_paths:
                                    img = Image.open(fpath)
                                    img.thumbnail((2048, 2048))
                                    img_byte_arr = io.BytesIO()
                                    if img.mode != "RGB": img = img.convert("RGB")
                                    img.save(img_byte_arr, format='JPEG', quality=90)
                                    z.writestr(os.path.basename(fpath), img_byte_arr.getvalue())
                                z.writestr("story.txt", text_content)

                            col_dl2.download_button(
                                f"📱 SNS用サイズ\n(軽量版)",
                                data=buf_sns.getvalue(),
                                file_name=f"sns_{i+1}.zip",
                                mime="application/zip",
                                type="primary",
                                key=f"dl_sns_{i}_{unique_id}"
                            )
else:
    st.info("👆 上のボックスに写真をドラッグ＆ドロップしてください")
