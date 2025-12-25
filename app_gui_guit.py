import streamlit as st
import json
import io
import uuid
import datetime
import calendar
from openai import OpenAI
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- 1. 設定 & DB接続 ---
openai_api_key = st.secrets["OPENAI_API_KEY"]
supabase_url = st.secrets["SUPABASE_URL"]
supabase_key = st.secrets["SUPABASE_KEY"]

client = OpenAI(api_key=openai_api_key)
supabase: Client = create_client(supabase_url, supabase_key)

# テーマカラー（目に優しい落ち着いた色味へ）
PRIMARY_COLOR = colors.HexColor("#D35400") # 深いオレンジ
TEXT_COLOR = colors.HexColor("#333333")    # 濃いグレー

# --- 2. 認証関係 ---
def init_session():
    if 'user' not in st.session_state:
        st.session_state['user'] = None

def login_user(email, password):
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state['user'] = response.user
        st.success("おかえりなさい。")
        st.rerun()
    except Exception:
        st.error("メールアドレスかパスワードが違います。")

def signup_user(email, password):
    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        st.session_state['user'] = response.user
        st.success("登録ありがとうございます。自動ログインします。")
        st.rerun()
    except Exception as e:
        st.error(f"登録エラー: {e}")

def logout_user():
    supabase.auth.sign_out()
    st.session_state['user'] = None
    st.rerun()

# --- 3. 画像・DB操作 ---
def upload_image(uploaded_file, user_id):
    if uploaded_file is None: return None
    try:
        file_ext = uploaded_file.name.split('.')[-1]
        file_name = f"{user_id}/{str(uuid.uuid4())}.{file_ext}"
        file_bytes = uploaded_file.getvalue()
        supabase.storage.from_("recipe_images").upload(file_name, file_bytes, {"content-type": uploaded_file.type})
        return supabase.storage.from_("recipe_images").get_public_url(file_name)
    except Exception: return None

# ★修正ポイント：AIの人格（プロンプト）を「落ち着いた料理家」に変更
def generate_recipe_json(ingredients, mode, condition, user_message):
    prompt = f"""
    あなたは「長年の経験を持つ落ち着いた料理家」です。
    ユーザーが自炊をするためのレシピを考えてください。
    
    【重要：トーンとマナー】
    * AIであることを忘れて、人間味のある、温かい言葉遣いをしてください。
    * 絵文字は極力使わないでください。使うとしてもタイトルに1つ程度で、文章中には入れないでください。
    * ロボットのような「〜です。〜ます。」の繰り返しを避け、自然な日本語で書いてください。
    
    【ユーザーの状況】
    * 食材: {ingredients}
    * 気分: {mode}
    * 条件: {condition}
    * メモ: {user_message}

    【出力JSON形式】
    {{
      "title": "料理名（美味しそうで、家庭的な名前）",
      "cooking_time": "目安時間（例：約20分）",
      "ingredients": [ {{"name": "食材名", "amount": "分量"}} ],
      "preparation": [ "下準備1", "下準備2" ],
      "steps": [ "工程1", "工程2" ],
      "chef_comment": "料理家からのワンポイント（「頑張ってください」等の他人事な言葉ではなく、「ここを焦がさないのがコツです」等の実用的なアドバイス）"
    }}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

def save_recipe_to_db(recipe_data, user_comment, user_id, image_url=None, is_public=False):
    try:
        data = {
            "user_id": user_id,
            "title": recipe_data["title"],
            "content": recipe_data,
            "comment": user_comment,
            "image_url": image_url,
            "is_public": is_public
        }
        supabase.table("recipes").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

def get_my_recipes(user_id):
    try:
        return supabase.table("recipes").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data
    except: return []

def get_public_recipes():
    try:
        return supabase.table("recipes").select("*").eq("is_public", True).order("created_at", desc=True).limit(20).execute().data
    except: return []

# --- 4. カレンダー・集計機能 ---
def display_stats_and_calendar(recipes):
    cooked_dates = set()
    today = datetime.date.today()
    this_month_count = 0
    
    for r in recipes:
        dt = datetime.datetime.fromisoformat(r['created_at']).date()
        cooked_dates.add(dt)
        if dt.year == today.year and dt.month == today.month:
            this_month_count += 1
            
    streak = 0
    check_date = today
    while check_date in cooked_dates:
        streak += 1
        check_date -= datetime.timedelta(days=1)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("今月作った回数", f"{this_month_count} 回")
    col2.metric("連続記録", f"{streak} 日")
    col3.metric("レシピ総数", f"{len(recipes)} 品")
    
    st.markdown("---")
    st.caption(f"{today.year}年 {today.month}月の記録")
    
    cal = calendar.monthcalendar(today.year, today.month)
    cols = st.columns(7)
    weeks = ["月", "火", "水", "木", "金", "土", "日"]
    for i, w in enumerate(weeks):
        cols[i].write(f"**{w}**")
        
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("")
            else:
                current_date = datetime.date(today.year, today.month, day)
                if current_date in cooked_dates:
                    # 派手な絵文字をやめ、シンプルな丸印に変更
                    cols[i].markdown(f"**{day}** <span style='color:orange;'>●</span>", unsafe_allow_html=True)
                else:
                    cols[i].write(f"{day}")

# PDF生成
def create_pdf_bytes(data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    font_path = "ipaexg.ttf" 
    try: pdfmetrics.registerFont(TTFont('JapaneseFont', font_path))
    except: return None
    styles = getSampleStyleSheet()
    # タイトルなどの装飾を少し落ち着かせる
    story = [Paragraph(data['title'], ParagraphStyle(name='Title', fontName='JapaneseFont', fontSize=18, textColor=PRIMARY_COLOR))]
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("■ 材料", ParagraphStyle(name='H1', fontName='JapaneseFont', fontSize=12, spaceAfter=5)))
    for item in data['ingredients']:
        story.append(Paragraph(f"・{item['name']} : {item['amount']}", ParagraphStyle(name='Body', fontName='JapaneseFont', fontSize=10, leading=14)))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("■ 作り方", ParagraphStyle(name='H1', fontName='JapaneseFont', fontSize=12, spaceAfter=5)))
    for i, step in enumerate(data['steps'], 1):
        story.append(Paragraph(f"{i}. {step}", ParagraphStyle(name='Body', fontName='JapaneseFont', fontSize=10, leading=14)))
    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 5. メイン画面制御 ---
def main():
    st.set_page_config(page_title="Kitchen Log", page_icon="🍳")
    
    # ★修正ポイント：CSSでデザインを整える（AIっぽさを消す）
    st.markdown("""
        <style>
        /* 全体のフォントを読みやすく */
        html, body, [class*="css"] {
            font-family: 'Helvetica Neue', 'Hiragino Kaku Gothic ProN', 'Arial', sans-serif;
        }
        /* ヘッダーの色変え */
        header {visibility: hidden;}
        /* ボタンのデザイン */
        div.stButton > button {
            background-color: #D35400;
            color: white;
            border-radius: 5px;
            border: none;
            padding: 0.5rem 1rem;
        }
        div.stButton > button:hover {
            background-color: #E59866;
            color: white;
        }
        /* タブのデザイン */
        .stTabs [data-baseweb="tab-list"] {
            gap: 10px;
        }
        .stTabs [data-baseweb="tab"] {
            height: 50px;
            white-space: pre-wrap;
            background-color: #f0f2f6;
            border-radius: 5px 5px 0 0;
            padding-top: 10px;
            padding-bottom: 10px;
        }
        .stTabs [aria-selected="true"] {
            background-color: white;
            border-top: 3px solid #D35400;
        }
        </style>
    """, unsafe_allow_html=True)

    init_session()

    # 未ログイン画面
    if st.session_state['user'] is None:
        st.markdown("<h1 style='text-align: center; color: #444;'>Kitchen Log</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>毎日の自炊を、もっと手軽に。</p>", unsafe_allow_html=True)
        
        tab1, tab2 = st.tabs(["ログイン", "新規登録"])
        with tab1:
            email = st.text_input("メールアドレス", key="l_mail")
            password = st.text_input("パスワード", type="password", key="l_pass")
            if st.button("ログイン", use_container_width=True): login_user(email, password)
        with tab2:
            st.info("メールアドレスだけで登録できます。")
            new_email = st.text_input("メールアドレス", key="s_mail")
            new_password = st.text_input("パスワード(6文字以上)", type="password", key="s_pass")
            if st.button("はじめる", use_container_width=True): signup_user(new_email, new_password)
        return

    # ログイン済み画面
    with st.sidebar:
        st.caption("アカウント情報")
        st.write(f"{st.session_state['user'].email}")
        if st.button("ログアウト", type="secondary"): logout_user()

    # タイトル（AIという言葉を使わない）
    st.title("Kitchen Log")
    
    tab_create, tab_log, tab_public = st.tabs(["献立を考える", "わたしの記録", "みんなのキッチン"])

    # タブ1: レシピ作成
    with tab_create:
        col1, col2 = st.columns([1, 2])
        with col1:
            st.subheader("食材と気分")
            ingredients = st.text_area("今ある食材", "豚肉、玉ねぎ、残り野菜")
            mode = st.selectbox("今日の気分", ["パパッと済ませたい", "しっかり食べたい", "ヘルシーに"])
            condition = st.text_input("条件など", "洗い物を減らしたい")
            user_message = st.text_area("メモ", "お弁当用")
            
            # ボタンの文言も自然に
            if st.button("レシピを構成する", use_container_width=True):
                with st.spinner("食材を確認しています..."):
                    st.session_state['current_recipe'] = generate_recipe_json(ingredients, mode, condition, user_message)
        
        with col2:
            if 'current_recipe' in st.session_state:
                r = st.session_state['current_recipe']
                
                # コンテナを使ってカード風に表示
                with st.container(border=True):
                    st.markdown(f"### {r['title']}")
                    st.caption(f"目安時間: {r['cooking_time']}")
                    
                    st.markdown("#### 材料")
                    for i in r['ingredients']: st.text(f"・ {i['name']} ... {i['amount']}")
                    
                    st.markdown("#### 作り方")
                    for idx, s in enumerate(r['steps'], 1):
                        st.markdown(f"**{idx}.** {s}")
                    
                    st.info(f"💡 {r['chef_comment']}")
                
                st.markdown("---")
                st.markdown("##### 記録に残す")
                uploaded_file = st.file_uploader("料理の写真", type=['jpg', 'png', 'jpeg'])
                is_public_check = st.checkbox("みんなのキッチンに公開する")
                
                if st.button("保存する", use_container_width=True):
                    user_id = st.session_state['user'].id
                    image_url = None
                    if uploaded_file:
                        image_url = upload_image(uploaded_file, user_id)
                    
                    if save_recipe_to_db(r, user_message, user_id, image_url, is_public_check):
                        st.success("記録しました")

                pdf = create_pdf_bytes(r)
                if pdf: st.download_button("PDFで書き出す", pdf, "recipe.pdf", "application/pdf")

    # タブ2: ログ
    with tab_log:
        st.subheader("記録")
        if st.button("更新", key="refresh_my"): st.rerun()
        
        user_id = st.session_state['user'].id
        my_recipes = get_my_recipes(user_id)
        
        if my_recipes:
            display_stats_and_calendar(my_recipes)
            st.markdown("---")
            st.caption("履歴")
            for r in my_recipes:
                date_str = r['created_at'].split('T')[0]
                status = "公開中" if r['is_public'] else "非公開"
                with st.expander(f"{date_str} : {r['title']} ({status})"):
                    if r.get('image_url'): st.image(r['image_url'], use_container_width=True)
                    st.write(f"メモ: {r['comment']}")
                    st.json(r['content'])
        else:
            st.write("まだ記録がありません。")

    # タブ3: シェア
    with tab_public:
        st.subheader("みんなのキッチン")
        if st.button("更新", key="refresh_pub"): st.rerun()
        public_recipes = get_public_recipes()
        if public_recipes:
            cols = st.columns(2)
            for idx, r in enumerate(public_recipes):
                with cols[idx % 2]:
                    with st.container(border=True):
                        if r.get('image_url'): st.image(r['image_url'], use_container_width=True)
                        st.markdown(f"**{r['title']}**")
                        st.caption(f"{r['created_at'].split('T')[0]}")
                        with st.expander("レシピを見る"):
                            c = r['content']
                            for i in c['ingredients']: st.text(f"・{i['name']} {i['amount']}")
                            st.divider()
                            for idx, s in enumerate(c['steps'], 1): st.write(f"{idx}. {s}")
        else:
            st.write("まだ公開レシピはありません。")

if __name__ == "__main__":
    main()







