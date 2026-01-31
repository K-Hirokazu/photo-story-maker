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

# --- セッション状態の初期化（これをしないとダウンロード時に消える） ---
if 'patterns' not in st.session_state:
    st.session_state.patterns = None
if 'target_name' not in st.session_state:
    st.session_state.target_name = None

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

# --- 便利な関数：ファイル名からアップロードされたファイル実体を探す ---
def get_file_by_name(name, file_list):
    for f in file_list:
        if f.name == name:
            f.seek(0) # 読み込み位置をリセット
            return f
    return None

# --- メイン処理 ---
if uploaded_files:
    # --- 2. ギャラリー選択 ---
    st.markdown("### 2. 「核」となる写真を選ぶ（またはおまかせ）")
    
    # プレビュー画像の準備
    preview_imgs = []
    display_limit = 100 
    
    # 画像リストを保持
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
    
    # 生成フラグ
    start_generation = False
    selected_target = None
    is_random = False

    with col1:
        if st.button(f"🚀 選択した写真で作る\n({manual_target_file.name})", type="primary"):
            selected_target = manual_target_file
            start_generation = True
            is_random = False

    with col2:
        if st.button("🎲 おまかせ (ランダム) で作る"):
            selected_target = random.choice(uploaded_files)
            start_generation = True
            is_random = True

    # --- 生成ロジック（ボタンが押された時だけ走る） ---
    if start_generation and selected_target:
        
        # エラーチェック
        if not api_key:
            st.error("⚠️ 左のサイドバーでAPIキーを入力してください")
            st.stop()

        target_name = selected_target.name
        
        # UI表示
        if is_random:
            st.info(f"🎲 運命の1枚: **{target_name}**")
        else:
            st.success(f"✅ 選択中: **{target_name}**")

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
                st.error("AIモデルが見つかりません。")
                st.stop()

            # 一時処理
            with tempfile.TemporaryDirectory() as temp_dir:
                status_text.text(f"📤 写真を解析中... (Core: {target_name})")
                
                # リスト作成
                seed_file = selected_target
                other_files = [f for f in uploaded_files if f.name != target_name]
                random.shuffle(other_files)
                target_files = [seed_file] + other_files[:24]
                
                gemini_files = []
                total = len(target_files)
                
                for i, file_obj in enumerate(target_files):
                    progress = (i / total) * 0.5
                    progress_bar.progress(progress)
                    
                    file_obj.seek(0)
                    
                    # 保存とリサイズ
                    temp_path = os.path.join(temp_dir, file_obj.name)
                    img = Image.open(file_obj)
                    img.thumbnail((1024, 1024))
                    if img.mode != "RGB": img = img.convert("RGB")
                    img.save(temp_path, "JPEG")
                    
                    # アップロード
                    g_file = genai.upload_file(temp_path, mime_type="image/jpeg")
                    gemini_files.append(g_file)
                    gemini_files.append(f"↑ ファイル名: {file_obj.name}")

                status_text.text("🧠 AIがストーリーを構想中...")
                progress_bar.progress(0.7)

                # プロンプト
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
                
                # 結果をセッションに保存（これが重要！）
                try:
                    clean_json = re.search(r'\[.*\]', response.text, re.DOTALL).group()
                    st.session_state.patterns = json.loads(clean_json)
                    st.session_state.target_name = target_name
                except:
                    st.error("AIの応答エラー。もう一度試してください。")
                    st.stop()

                progress_bar.progress(1.0)
                status_text.empty()

        except Exception as e:
            st.error(f"エラー: {e}")


    # --- 4. 結果表示エリア（セッション情報があれば常に表示） ---
    if st.session_state.patterns:
        
        st.divider()
        st.subheader(f"🎉 「{st.session_state.target_name}」から生まれた物語")
        
        patterns = st.session_state.patterns
        tabs = st.tabs(["🎨 Visual", "💧 Emotional", "📖 Story"])
        
        for i, tab in enumerate(tabs):
            if i < len(patterns):
                pat = patterns[i]
                with tab:
                    st.markdown(f"**{pat.get('story')}**")
                    st.caption(f"テーマ: {pat.get('theme')} | 理由: {pat.get('reason')}")
                    
                    # ファイル実体を探す
                    target_files = []
                    # 核となる写真を追加（先頭に）
                    seed_obj = get_file_by_name(st.session_state.target_name, uploaded_files)
                    
                    # AIが選んだファイル（核以外）
                    chosen_names = pat.get('files', [])
                    for name in chosen_names:
                        # 名前が含まれているかチェック（部分一致対応）
                        found = False
                        for up_file in uploaded_files:
                            if name in up_file.name or up_file.name in name:
                                if up_file.name != st.session_state.target_name: # 核写真は重複させない
                                    target_files.append(up_file)
                                    found = True
                                    break
                    
                    # リスト結合（核 + 選ばれたもの）
                    if seed_obj:
                        target_files.insert(0, seed_obj)
                    
                    # 4枚に調整
                    target_files = target_files[:4]

                    # プレビュー表示
                    cols = st.columns(4)
                    for idx, f_obj in enumerate(target_files):
                        f_obj.seek(0)
                        img_prev = Image.open(f_obj)
                        img_prev.thumbnail((800, 800))
                        cols[idx].image(img_prev, use_container_width=True)

                    # --- ダウンロード処理 ---
                    st.markdown("#### 📥 ダウンロード")
                    col_dl1, col_dl2 = st.columns(2)
                    text_content = f"テーマ: {pat.get('theme')}\n\nストーリー:\n{pat.get('story')}\n\n理由:\n{pat.get('reason')}"

                    # ダウンロードボタン用データ作成
                    # 1. オリジナル
                    if target_files:
                        buf_orig = io.BytesIO()
                        with zipfile.ZipFile(buf_orig, "w") as z:
                            for f_obj in target_files:
                                f_obj.seek(0)
                                z.writestr(f_obj.name, f_obj.read())
                            z.writestr("story.txt", text_content)
                        
                        col_dl1.download_button(
                            f"📦 オリジナル画質\n(元サイズ)",
                            data=buf_orig.getvalue(),
                            file_name=f"orig_plan_{i+1}.zip",
                            mime="application/zip",
                            key=f"dl_orig_{i}_{st.session_state.target_name}"
                        )

                    # 2. SNS用
                    if target_files:
                        buf_sns = io.BytesIO()
                        with zipfile.ZipFile(buf_sns, "w") as z:
                            for f_obj in target_files:
                                f_obj.seek(0)
                                img = Image.open(f_obj)
                                img.thumbnail((2048, 2048))
                                
                                img_byte_arr = io.BytesIO()
                                if img.mode != "RGB": img = img.convert("RGB")
                                img.save(img_byte_arr, format='JPEG', quality=90)
                                
                                z.writestr(f_obj.name, img_byte_arr.getvalue())
                            z.writestr("story.txt", text_content)

                        col_dl2.download_button(
                            f"📱 SNS用サイズ\n(軽量版)",
                            data=buf_sns.getvalue(),
                            file_name=f"sns_plan_{i+1}.zip",
                            mime="application/zip",
                            type="primary",
                            key=f"dl_sns_{i}_{st.session_state.target_name}"
                        )

else:
    st.info("👆 上のボックスに写真をドラッグ＆ドロップしてください")
