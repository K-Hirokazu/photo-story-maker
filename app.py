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

# --- カスタムCSS ---
st.markdown("""
<style>
    /* 全体のフォントや雰囲気を調整 */
    .block-container {
        padding-top: 2rem;
    }
    /* ボタンデザイン */
    .stButton>button {
        width: 100%;
        border-radius: 20px;
        font-weight: bold;
        height: 3em;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    /* ステップ表示のデザイン */
    .step-box {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        border-left: 5px solid #ff4b4b;
    }
    /* ダークモード対応 */
    @media (prefers-color-scheme: dark) {
        .step-box {
            background-color: #262730;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- セッション初期化 ---
if 'patterns' not in st.session_state: st.session_state.patterns = None
if 'target_name' not in st.session_state: st.session_state.target_name = None
if 'gen_id' not in st.session_state: st.session_state.gen_id = str(uuid.uuid4())
if 'local_paths' not in st.session_state: st.session_state.local_paths = {}
if 'temp_dir_obj' not in st.session_state: st.session_state.temp_dir_obj = None

# --- サイドバー（設定） ---
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini API Key", type="password", placeholder="ここにキーを入力")
    st.markdown("""
    <small>
    KEYS:
    1. <a href="https://aistudio.google.com/app/apikey" target="_blank">Google AI Studio</a>でキーを取得
    2. ここに貼り付ける
    3. 写真をアップロードして開始！
    </small>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    # モデル選択（APIキーがある時だけ表示）
    selected_model_name = "models/gemini-1.5-flash"
    if api_key:
        try:
            genai.configure(api_key=api_key)
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            # Flash優先
            idx = 0
            for i, m in enumerate(models):
                if 'flash' in m and '1.5' in m:
                    idx = i
                    break
            selected_model_name = st.selectbox("使用モデル", models, index=idx)
            st.success("✅ 接続OK")
        except:
            st.error("🚫 キーが無効です")

# --- メインエリア ---
st.title("📸 AI Photo Story Curator")
st.caption("あなたの写真フォルダから、SNSで輝く「最強の4枚」をAIがセレクトします。")

# --- ユーザーへの案内ロジック ---
if not api_key:
    # 1. APIキー未入力時の案内
    st.markdown("""
    <div class="step-box">
        <h3>👋 ようこそ！まずは準備をしましょう</h3>
        <p>このアプリを使うには、GoogleのAI（Gemini）を動かすための「鍵」が必要です。</p>
        <ol>
            <li>左のサイドバーにあるリンクから <b>API Key</b> を取得してください（無料です）。</li>
            <li>取得したキーをサイドバーに入力してください。</li>
            <li>入力すると、写真のアップロード画面が現れます！</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)
    st.stop() # ここで処理を止める

# APIキーはあるが、ファイルがない場合
uploaded_files = st.file_uploader("📂 1. 写真をまとめてアップロード (20枚〜推奨)", accept_multiple_files=True, type=['jpg','jpeg','png','heic','webp'])

if not uploaded_files:
    st.info("👆 上のボックスに、セレクトしたい写真たち（候補写真）をドラッグ＆ドロップしてください。")
    st.stop()

# --- 以降、アプリ本体 ---
st.markdown("### 👁️ 2. 「核」となる写真を選ぶ")
st.caption("この1枚を軸にして、AIがストーリーを組み立てます。")

# プレビュー表示
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

st.markdown("### 🚀 3. 生成スタート")
c1, c2 = st.columns(2)
start = False
is_random = False
res_area = st.empty()

if c1.button(f"この写真で作る\n({target_file.name})", type="primary"):
    start = True
    is_random = False
    res_area.empty()
    
if c2.button("🎲 運任せ（ランダム）で作る"):
    target_file = random.choice(uploaded_files)
    start = True
    is_random = True
    res_area.empty()

# --- 生成処理 ---
if start and target_file:
    if is_random:
        st.info(f"🎲 選ばれたのは... **{target_file.name}** でした！")
        target_file.seek(0)
        st.image(target_file, width=300)
    else:
        st.success(f"✅ **{target_file.name}** を核にして構成します")

    genai.configure(api_key=api_key)
    status = st.empty()
    bar = st.progress(0)
    
    try:
        status.text("📸 写真を読み込んでいます...")
        
        # 一時保存
        if st.session_state.temp_dir_obj: st.session_state.temp_dir_obj.cleanup()
        st.session_state.temp_dir_obj = tempfile.TemporaryDirectory()
        td = st.session_state.temp_dir_obj.name
        
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

        status.text("🧠 プロの視点で構成を考えています...")
        bar.progress(0.7)
        
        prompt = [
            f"あなたはカリスマ写真編集者です。リストの「{target_file.name}」を核に、4枚組の作品を3パターン作ってください。",
            "ファイル名は正確に答えてください。",
            "【選定ルール】引きと寄りのバランス、色彩の統一、重複禁止。",
            "出力は以下のJSON形式のみ:",
            """[
                {"theme": "Cinematic Sequence", "story": "...", "reason": "...", "files": ["f1", "f2", "f3", "f4"]},
                {"theme": "Color & Light Study", "story": "...", "reason": "...", "files": ["f1", "f2", "f3", "f4"]},
                {"theme": "Contrast & Rhythm", "story": "...", "reason": "...", "files": ["f1", "f2", "f3", "f4"]}
            ]"""
        ] + gemini_inputs
        
        model = genai.GenerativeModel(selected_model_name)
        res = model.generate_content(prompt)
        
        json_match = re.search(r'\[.*\]', res.text, re.DOTALL)
        if not json_match: raise Exception("AI応答エラー")
        
        st.session_state.patterns = json.loads(json_match.group())
        st.session_state.target_name = target_file.name
        st.session_state.gen_id = str(uuid.uuid4())
        
        bar.progress(1.0)
        status.empty()
        
    except Exception as e:
        st.error(f"エラー: {e}")

# --- 結果表示 ---
if st.session_state.patterns:
    with res_area.container():
        st.divider()
        st.subheader(f"🎉 完成: {st.session_state.target_name}")
        
        tabs = st.tabs(["🎥 シネマティック", "🎨 色と光", "⚡ コントラスト"])
        patterns = st.session_state.patterns
        paths_map = st.session_state.local_paths
        
        for i, tab in enumerate(tabs):
            if i >= len(patterns): continue
            pat = patterns[i]
            
            with tab:
                st.write(f"**{pat.get('story')}**")
                st.caption(f"💡 {pat.get('reason')}")
                
                # 画像集め
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
                
                # 補充
                if len(final_files) < 4:
                    all_vals = list(paths_map.values())
                    remain = [p for p in all_vals if p not in final_files]
                    needed = 4 - len(final_files)
                    if remain: final_files.extend(random.sample(remain, min(needed, len(remain))))
                
                show_files = final_files[:4]
                
                # 表示
                cols = st.columns(4)
                for idx, p in enumerate(show_files):
                    cols[idx].image(p, use_container_width=True)
                    
                # DL
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
