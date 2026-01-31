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

# --- 画像をbase64に変換する関数 ---
def img_to_base64(img_path):
    with open(img_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

# --- 頑丈なモデル選択関数 ---
def get_best_model():
    """利用可能なモデルの中からベストなものを自動で探す"""
    try:
        # 1. Googleに使えるモデル一覧を問い合わせる
        all_models = list(genai.list_models())
        available_names = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        
        # 優先順位リスト（上から順に探す）
        priorities = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-flash-001',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-pro-latest',
            'models/gemini-pro'
        ]
        
        # 2. 完全一致で探す
        for p in priorities:
            if p in available_names:
                return p
        
        # 3. 部分一致で探す（"flash" が含まれるものを優先）
        for name in available_names:
            if 'flash' in name and '1.5' in name:
                return name
        
        # 4. どうしても見つからなければリストの最初を使う
        if available_names:
            return available_names[0]
            
    except Exception as e:
        # エラーが起きてもデフォルトを返す
        pass
    
    return 'gemini-1.5-flash' # 最終手段

# --- カスタムCSS ---
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
        grid-template-columns
        
