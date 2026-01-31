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
import time

# --- ページ設定 ---
st.set_page_config(
    page_title="AI Photo Story Curator",
    page_icon="📸",
    layout="wide"
)

# --- 画像をbase64に変換する関数 ---
def img_to_base64(img_path):
    try:
        with open(img_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode()
    except:
        return ""

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
    .twitter-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr 1fr;
        gap: 2px;
        width: 100%;
        max-width: 600px;
        margin: 0 auto;
        aspect-ratio: 16 / 9;
        border-radius: 12px;
        overflow: hidden;
    }
    @media (max-width: 640px) {
        .twitter-grid {
            aspect-ratio: 3 / 2;
        }
    }
    .grid-item {
        width: 100%;
        height: 100%;
        position: relative;
    }
    .grid-item img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }
</style>
""", unsafe_allow_html=True)

# --- セッション初期化 ---
if 'patterns' not in st.session_state: st.session_state.patterns = None
if 'target_name' not in st.session_state: st.session_state.target_name = None
if 'gen_id' not in st.session_state: st.session_state.gen_id = str(uuid.uuid4())
if 'local_paths' not in st.session_state: st.session_state.local_paths = {}
if 'temp_dir_obj' not in st.session_state: st.session_state.temp_dir_obj = None

# --- アプリ本体 ---
st.title("📸 AI Photo Story Curator")
st.caption("アップロードした写真から「最高の4枚」を選び、物語を作ります。")

# サイドバー設定
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini API Key", type="password")
    st.markdown("[🔑 キー取得](https://aistudio.google.com/app/apikey)")
    
    st.divider()
    # モデル選択（デフォルトをFlashに固定）
    model_option = st.selectbox(
        "AIモデル (Flash推奨)", 
        ["gemini-1.5-flash", "gemini-1.5-pro"],
        index=0, # Flashを初期値に
        help="エラーが出る場合はFlashを選んでください"
    )

uploaded_files = st.file_uploader("1. 写真をアップロード", accept_multiple_files=True, type=['jpg','jpeg','png','heic','webp'])

if uploaded_files:
    st.markdown("### 2. 「核」となる写真を選ぶ")
    
    display_files = uploaded_files[:100]
    preview_imgs = []
    
    for f in display_files:
        f.seek(0)
        img = Image.open(f)
        img.thumbnail((150, 150))
        preview_imgs.append(img)
    
    sel_idx = image_select(
        label="",
        images=preview_imgs,
        captions=[f.name for f in display_files],
        index=0,
        return_value="index",
        use_container_width=False
    )
    
    target_file = display_files[sel_idx]
    
    st.markdown("### 3. 生成スタート")
    c1, c2 = st.columns(2)
    start = False
    is_random = False
    
    res_area = st.empty()

    if c1.button(f"🚀 選択した写真で作る\n({target_file.name})", type="primary"):
        start = True
        is_random = False
        res_area.empty()
        
    if c2.button("🎲 おまかせ (ランダム)"):
        target_file = random.choice(uploaded_files)
        start = True
        is_random = True
        res_area.empty()

    if start and target_file:
        if not api_key:
            st.error("⚠️ サイドバーでAPIキーを入力してください")
            st.stop()

        if is_random:
            st.info(f"🎲 運命の1枚: **{target_file.name}**")
            target_file.seek(0)
            st.image(target_file, width=300)
        else:
            st.success(f"✅ 選択中: **{target_file.name}**")
        
        genai.configure(api_key=api_key)
        status = st.empty()
        bar = st.progress(0)
        
        try:
            status.text("AI準備中...")
            
            # 一時保存処理
            if st.session_state.temp_dir_obj: st.session_state.temp_dir_obj.cleanup()
            st.session_state.temp_dir_obj = tempfile.TemporaryDirectory()
            td = st.session_state.temp_dir_obj.name
            
            status.text(f"画像を解析中... ({model_option})")
            
            st.session_state.local_paths = {}
            others = [f for f in uploaded_files if f.name != target_file.name]
            random.shuffle(others)
            process_files = [target_file] + others[:24]
            
            gemini_inputs = []
            
            for i, f_obj in enumerate(process_files):
                bar.progress((i / len(process_files)) * 0.5)
                f_obj.seek(0)
                
                path = os.path.join(td, f_obj.name)
                with open(path, "wb") as f: f.write(f_obj.read())
                st.session_state.local_paths[f_obj.name] = path
                
                img = Image.open(path)
                img.thumbnail((1024, 1024))
                if img.mode != 'RGB': img = img.convert('RGB')
                
                rz_path = os.path.join(td, f"resized_{f_obj.name}.jpg")
                img.save(rz_path, "JPEG")
                
                g_file = genai.upload_file(rz_path, mime_type="image/jpeg")
                gemini_inputs.append(g_file)
                gemini_inputs.append(f"ファイル名: {f_obj.name}")

            status.text("ストーリー構成中...")
            bar.progress(0.6)
            
            prompt = [
                f"あなたは写真編集者です。リストの「{target_file.name}」を核に、4枚組の作品を3パターン作ってください。",
                "ファイル名は正確に答えてください。",
                "出力は以下のJSON形式のみ:",
                """[
                    {"theme": "Visual", "story": "...", "reason": "...", "files": ["file1", "file2", "file3", "file4"]},
                    {"theme": "Emotional", "story": "...", "reason": "...", "files": ["f1", "f2", "f3", "f4"]},
                    {"theme": "Narrative", "story": "...", "reason": "...", "files": ["f1", "f2", "f3", "f4"]}
                ]"""
            ] + gemini_inputs
            
            model = genai.GenerativeModel(model_option)
            res = model.generate_content(prompt)
            
            json_match = re.search(r'\[.*\]', res.text, re.DOTALL)
            if not json_match: raise Exception("AIの応答解析に失敗")
            
            st.session_state.patterns = json.loads(json_match.group())
            st.session_state.target_name = target_file.name
            st.session_state.gen_id = str(uuid.uuid4())
            
            bar.progress(1.0)
            status.empty()
            
        except Exception as e:
            if "429" in str(e):
                st.error("⚠️ 使いすぎのためGoogleに制限されました。1分ほど待ってから「gemini-1.5-flash」で試してください。")
            else:
                st.error(f"エラー: {e}")

    # --- 結果表示 ---
    if st.session_state.patterns:
        with res_area.container():
            st.divider()
            st.subheader(f"🎉 物語: {st.session_state.target_name}")
            
            tabs = st.tabs(["🎨 Visual", "💧 Emotional", "📖 Story"])
            patterns = st.session_state.patterns
            paths_map = st.session_state.local_paths
            
            for i, tab in enumerate(tabs):
                if i >= len(patterns): continue
                pat = patterns[i]
                
                with tab:
                    st.write(f"**{pat.get('story')}**")
                    st.caption(f"理由: {pat.get('reason')}")
                    
                    final_files = []
                    seed_path = paths_map.get(st.session_state.target_name)
                    if seed_path: final_files.append(seed_path)
                    
                    ai_files = pat.get('files', [])
                    for name in ai_files:
                        if len(final_files) >= 4: break
                        for local_name, local_path in paths_map.items():
                            if local_path in final_files: continue
                            if name.lower() in local_name.lower():
                                final_files.append(local_path)
                                break
                    
                    if len(final_files) < 4:
                        all_vals = list(paths_map.values())
                        remain = [p for p in all_vals if p not in final_files]
                        needed = 4 - len(final_files)
                        if remain: final_files.extend(random.sample(remain, min(needed, len(remain))))
                    
                    show_files = final_files[:4]
                    
                    if len(show_files) == 4:
                        st.markdown("#### 📱 プレビュー (2x2)")
                        b64s = [img_to_base64(p) for p in show_files]
                        grid_html = f"""
                        <div class="twitter-grid">
                            <div class="grid-item"><img src="data:image/jpeg;base64,{b64s[0]}"></div>
                            <div class="grid-item"><img src="data:image/jpeg;base64,{b64s[1]}"></div>
                            <div class="grid-item"><img src="data:image/jpeg;base64,{b64s[2]}"></div>
                            <div class="grid-item"><img src="data:image/jpeg;base64,{b64s[3]}"></div>
                        </div>
                        """
                        st.markdown(grid_html, unsafe_allow_html=True)
                    
                    st.divider()
                    st.markdown("#### 🖼️ 全体表示")
                    cols = st.columns(4)
                    for idx, p in enumerate(show_files):
                        cols[idx].image(p, use_container_width=True)
                        
                    st.divider()
                    dl_cols = st.columns(2)
                    txt = f"テーマ: {pat.get('theme')}\nストーリー: {pat.get('story')}"
                    uid = st.session_state.gen_id
                    
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w") as z:
                        for p in show_files: z.write(p, os.path.basename(p))
                        z.writestr("story.txt", txt)
                    dl_cols[0].download_button("📦 オリジナル保存", buf.getvalue(), f"orig_{i+1}.zip", "application/zip", key=f"d1_{i}_{uid}")
                    
                    buf2 = io.BytesIO()
                    with zipfile.ZipFile(buf2, "w") as z:
                        for p in show_files:
                            img = Image.open(p)
                            img.thumbnail((2048, 2048))
                            ib = io.BytesIO()
                            img.convert('RGB').save(ib, 'JPEG', quality=90)
                            z.writestr(os.path.basename(p), ib.getvalue())
                        z.writestr("story.txt", txt)
                    dl_cols[1].download_button("📱 SNS用保存", buf2.getvalue(), f"sns_{i+1}.zip", "application/zip", type="primary", key=f"d2_{i}_{uid}")
