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

# --- カスタムCSS（ボタンのデザインのみ残す） ---
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
</style>
""", unsafe_allow_html=True)

# --- モデル自動選択関数 ---
def get_best_model():
    """使えるモデルを自動で探す"""
    try:
        models = genai.list_models()
        valid_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        # 優先順位: Flash系を優先（速度・制限回避のため）
        targets = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
        
        for t in targets:
            for m in valid_models:
                if t in m: return m
        if valid_models: return valid_models[0]
    except:
        pass
    return "gemini-1.5-flash"

# --- セッション初期化 ---
if 'patterns' not in st.session_state: st.session_state.patterns = None
if 'target_name' not in st.session_state: st.session_state.target_name = None
if 'gen_id' not in st.session_state: st.session_state.gen_id = str(uuid.uuid4())
if 'local_paths' not in st.session_state: st.session_state.local_paths = {}
if 'temp_dir_obj' not in st.session_state: st.session_state.temp_dir_obj = None

# --- アプリ本体 ---
st.title("📸 AI Photo Story Curator")
st.caption("アップロードした写真から「最高の4枚」を選び、物語を作ります。")

# サイドバー
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini API Key", type="password")
    st.markdown("[🔑 キー取得](https://aistudio.google.com/app/apikey)")
    
    st.divider()
    
    # モデル選択ロジック（自動 + 手動オーバーライド）
    selected_model_name = "models/gemini-1.5-flash"
    if api_key:
        try:
            genai.configure(api_key=api_key)
            models_list = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            
            default_index = 0
            for i, m in enumerate(models_list):
                if 'flash' in m and '1.5' in m:
                    default_index = i
                    break
            
            selected_model_name = st.selectbox("使用するAIモデル", models_list, index=default_index)
        except:
            st.warning("APIキーを確認してください")

uploaded_files = st.file_uploader("1. 写真をアップロード", accept_multiple_files=True, type=['jpg','jpeg','png','heic','webp'])

if uploaded_files:
    st.markdown("### 2. 「核」となる写真を選ぶ")
    
    # 表示数制限（軽量化）
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
            
            # 一時保存（前のキャッシュをクリア）
            if st.session_state.temp_dir_obj: st.session_state.temp_dir_obj.cleanup()
            st.session_state.temp_dir_obj = tempfile.TemporaryDirectory()
            td = st.session_state.temp_dir_obj.name
            
            status.text(f"画像を解析中... ({selected_model_name})")
            
            st.session_state.local_paths = {}
            others = [f for f in uploaded_files if f.name != target_file.name]
            random.shuffle(others)
            process_files = [target_file] + others[:24]
            
            gemini_inputs = []
            
            for i, f_obj in enumerate(process_files):
                bar.progress((i / len(process_files)) * 0.5)
                f_obj.seek(0)
                
                # オリジナル保存
                path = os.path.join(td, f_obj.name)
                with open(path, "wb") as f: f.write(f_obj.read())
                st.session_state.local_paths[f_obj.name] = path
                
                # AI用リサイズ
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
            
            # --- プロ仕様プロンプト ---
            prompt = [
                f"あなたは世界的に有名な写真集の編集者であり、SNSで10万いいねを集めるカリスマ・キュレーターです。",
                f"提供された写真リストから、「{target_file.name}」を核（1枚目または2枚目に配置）として、",
                "見る人の心を動かす『最強の4枚組』を3パターン作成してください。",
                "",
                "【選定の絶対ルール】",
                "1. **「引き」と「寄り」を混ぜる**: 4枚すべてが同じ距離感（全部アップ、全部風景など）にならないようにすること。広角、標準、接写をリズミカルに組み合わせる。",
                "2. **色彩の統一**: 4枚全体でトーン（青み、温かみ、彩度）が調和していること。",
                "3. **重複の禁止**: 全く同じ構図の写真を複数枚入れないこと。",
                "",
                "## 作成する3つのパターン",
                "",
                "### パターン1: 【Cinematic Sequence】（映画的ストーリー）",
                "- **特徴**: 映画のワンシーンのような連続性。",
                "- **構成案**: 「状況説明（広角）」→「核となる被写体」→「手元や視線の先のディテール（接写）」→「余韻（抽象的）」の流れを作る。",
                "",
                "### パターン2: 【Color & Light Study】（光と色の共鳴）",
                "- **特徴**: 「色」や「光」を主役にした抽象的な構成。",
                "- **構成案**: 被写体が違っても、「同じ青色が含まれている」「同じような夕日が当たっている」「影の形が似ている」写真を集める。",
                "",
                "### パターン3: 【Contrast & Rhythm】（対比とリズム）",
                "- **特徴**: ギャップで魅せる。",
                "- **構成案**: 「静と動」「光と影」「人工物と自然」「直線と曲線」など、対比的な写真を交互に配置する。",
                "",
                "## 出力形式 (JSONのみ)",
                """[
                    {
                        "theme": "Cinematic Sequence",
                        "story": "...",
                        "reason": "...",
                        "files": ["file1", "file2", "file3", "file4"]
                    },
                    {
                        "theme": "Color & Light Study",
                        "story": "...",
                        "reason": "...",
                        "files": ["f1", "f2", "f3", "f4"]
                    },
                    {
                        "theme": "Contrast & Rhythm",
                        "story": "...",
                        "reason": "...",
                        "files": ["f1", "f2", "f3", "f4"]
                    }
                ]"""
            ] + gemini_inputs
            
            model = genai.GenerativeModel(selected_model_name)
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
                st.error("⚠️ 使いすぎのため制限されました。少し時間を空けてください。")
            else:
                st.error(f"エラー: {e}")

    # --- 結果表示 ---
    if st.session_state.patterns:
        with res_area.container():
            st.divider()
            st.subheader(f"🎉 物語: {st.session_state.target_name}")
            
            tabs = st.tabs(["🎥 Cinematic", "🎨 Color & Light", "⚡ Contrast"])
            patterns = st.session_state.patterns
            paths_map = st.session_state.local_paths
            
            for i, tab in enumerate(tabs):
                if i >= len(patterns): continue
                pat = patterns[i]
                
                with tab:
                    st.write(f"**{pat.get('story')}**")
                    st.caption(f"選定理由: {pat.get('reason')}")
                    
                    # --- 画像集めロジック (必ず4枚集める) ---
                    final_files = []
                    
                    # 1. 核となる写真
                    seed_path = paths_map.get(st.session_state.target_name)
                    if seed_path: final_files.append(seed_path)
                    
                    # 2. AI選出写真
                    ai_files = pat.get('files', [])
                    for name in ai_files:
                        if len(final_files) >= 4: break
                        for local_name, local_path in paths_map.items():
                            if local_path in final_files: continue
                            if name.lower() in local_name.lower():
                                final_files.append(local_path)
                                break
                    
                    # 3. 不足分を補充 (意地でも4枚にする)
                    if len(final_files) < 4:
                        all_vals = list(paths_map.values())
                        remain = [p for p in all_vals if p not in final_files]
                        needed = 4 - len(final_files)
                        if remain: final_files.extend(random.sample(remain, min(needed, len(remain))))
                    
                    show_files = final_files[:4]
                    
                    # --- シンプルな横4枚表示 ---
                    st.markdown("#### 🖼️ 選択された4枚")
                    cols = st.columns(4)
                    for idx, p in enumerate(show_files):
                        cols[idx].image(p, use_container_width=True)
                        
                    # --- ダウンロード ---
                    st.divider()
                    dl_cols = st.columns(2)
                    txt = f"テーマ: {pat.get('theme')}\nストーリー: {pat.get('story')}\n理由: {pat.get('reason')}"
                    uid = st.session_state.gen_id
                    
                    # オリジナル
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w") as z:
                        for p in show_files: z.write(p, os.path.basename(p))
                        z.writestr("story.txt", txt)
                    dl_cols[0].download_button("📦 オリジナル保存", buf.getvalue(), f"orig_{i+1}.zip", "application/zip", key=f"d1_{i}_{uid}")
                    
                    # SNS用
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
