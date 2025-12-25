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

# テーマカラー
PRIMARY_COLOR = colors.HexColor("#E67E22")
TEXT_COLOR = colors.HexColor("#2C3E50")

# --- 2. 認証関係 ---
def init_session():
    if 'user' not in st.session_state:
        st.session_state['user'] = None

def login_user(email, password):
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state['user'] = response.user
        st.success("ログインしました！")
        st.rerun()
    except Exception as e:
        st.error("ログインエラー: メールまたはパスワードが違います。")

def signup_user(email, password):
    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        st.session_state['user'] = response.user
        st.success("登録成功！自動ログインします。")
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
    except Exception as e: return None

def generate_recipe_json(ingredients, mode, condition, user_message):
    prompt = f"""
    あなたは「自炊効率化のプロ」です。
    ユーザーは自分用に、手軽で美味しい料理を作りたいと考えています。
    以下の情報を元に、指定のJSON形式のみを出力してください。
    【ユーザー入力】食材:{ingredients}, モード:{mode}, 条件:{condition}, メモ:{user_message}
    【出力JSON形式】
    {{
      "title": "料理名",
      "cooking_time": "目安時間",
      "ingredients": [ {{"name": "食材名", "amount": "分量"}} ],
      "preparation": [ "下準備1", "下準備2" ],
      "steps": [ "工程1", "工程2" ],
      "chef_comment": "コツ"
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
        # 全件取得（カレンダー用）
        return supabase.table("recipes").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data
    except: return []

def get_public_recipes():
    try:
        return supabase.table("recipes").select("*").eq("is_public", True).order("created_at", desc=True).limit(20).execute().data
    except: return []

# --- 4. カレンダー・集計機能（新機能） ---
def display_stats_and_calendar(recipes):
    """自炊の統計とカレンダーを表示する関数"""
    
    # 日付データの抽出（YYYY-MM-DD形式のリストを作成）
    cooked_dates = set()
    today = datetime.date.today()
    this_month_count = 0
    
    for r in recipes:
        # created_at は "2023-12-25T12:00:00..." 形式
        dt = datetime.datetime.fromisoformat(r['created_at']).date()
        cooked_dates.add(dt)
        if dt.year == today.year and dt.month == today.month:
            this_month_count += 1
            
    # ストリーク計算（今日から遡って連続何日やっているか）
    streak = 0
    check_date = today
    while check_date in cooked_dates:
        streak += 1
        check_date -= datetime.timedelta(days=1)
    
    # --- 統計表示エリア ---
    col1, col2, col3 = st.columns(3)
    col1.metric("📅 今月の自炊回数", f"{this_month_count} 回")
    col2.metric("🔥 現在の連続記録", f"{streak} 日")
    col3.metric("🏆 通算レシピ数", f"{len(recipes)} 品")
    
    st.markdown("---")
    
    # --- カレンダー表示エリア ---
    st.subheader(f"📅 {today.year}年 {today.month}月の記録")
    
    # カレンダーの作成
    cal = calendar.monthcalendar(today.year, today.month)
    
    # 曜日ヘッダー
    cols = st.columns(7)
    weeks = ["月", "火", "水", "木", "金", "土", "日"]
    for i, w in enumerate(weeks):
        cols[i].write(f"**{w}**")
        
    # 日付埋め込み
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("") # 空白
            else:
                # その日に料理したかチェック
                current_date = datetime.date(today.year, today.month, day)
                if current_date in cooked_dates:
                    # 料理した日は目立たせる
                    cols[i].markdown(f"**{day}**<br>🍳", unsafe_allow_html=True)
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
    story = [Paragraph(data['title'], ParagraphStyle(name='Title', fontName='JapaneseFont', fontSize=20))]
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("■材料", ParagraphStyle(name='H1', fontName='JapaneseFont', fontSize=14)))
    for item in data['ingredients']:
        story.append(Paragraph(f"・{item['name']} : {item['amount']}", ParagraphStyle(name='Body', fontName='JapaneseFont')))
    story.append(Paragraph("■作り方", ParagraphStyle(name='H1', fontName='JapaneseFont', fontSize=14)))
    for i, step in enumerate(data['steps'], 1):
        story.append(Paragraph(f"{i}. {step}", ParagraphStyle(name='Body', fontName='JapaneseFont')))
    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 5. メイン画面制御 ---
def main():
    st.set_page_config(page_title="My Recipe Log", page_icon="🍳")
    init_session()

    if st.session_state['user'] is None:
        st.title("🍳 Recipe Log - ログイン")
        tab1, tab2 = st.tabs(["ログイン", "新規登録"])
        with tab1:
            email = st.text_input("メール", key="l_mail")
            password = st.text_input("パスワード", type="password", key="l_pass")
            if st.button("ログイン", type="primary"): login_user(email, password)
        with tab2:
            st.warning("テスト運用中")
            new_email = st.text_input("メール", key="s_mail")
            new_password = st.text_input("パスワード", type="password", key="s_pass")
            if st.button("登録"): signup_user(new_email, new_password)
        return

    with st.sidebar:
        st.write(f"User: {st.session_state['user'].email}")
        if st.button("ログアウト"): logout_user()

    st.title("🍳 自炊サポート & ログ")
    tab_create, tab_log, tab_public = st.tabs(["📝 レシピ作成", "📚 自分のレシピ帳", "🌏 みんなの広場"])

    with tab_create:
        col1, col2 = st.columns([1, 2])
        with col1:
            ingredients = st.text_area("食材", "豚肉、玉ねぎ")
            mode = st.selectbox("モード", ["手早く", "ガッツリ"])
            condition = st.text_input("条件", "洗い物少なく")
            user_message = st.text_area("メモ", "お弁当用")
            if st.button("レシピ考案", type="primary"):
                with st.spinner("AI思考中..."):
                    st.session_state['current_recipe'] = generate_recipe_json(ingredients, mode, condition, user_message)
        
        with col2:
            if 'current_recipe' in st.session_state:
                r = st.session_state['current_recipe']
                st.subheader(r['title'])
                st.write(f"⏱ {r['cooking_time']}")
                st.write("**🛒 材料**")
                for i in r['ingredients']: st.write(f"- {i['name']} {i['amount']}")
                st.write("**🍳 手順**")
                for idx, s in enumerate(r['steps'], 1): st.write(f"{idx}. {s}")
                st.markdown("---")
                
                st.write("### 📸 保存設定")
                uploaded_file = st.file_uploader("完成写真", type=['jpg', 'png', 'jpeg'])
                is_public_check = st.checkbox("みんなの広場に公開する")
                
                if st.button("💾 ログに保存"):
                    user_id = st.session_state['user'].id
                    image_url = None
                    if uploaded_file:
                        image_url = upload_image(uploaded_file, user_id)
                    
                    if save_recipe_to_db(r, user_message, user_id, image_url, is_public_check):
                        st.success("保存しました！")

                pdf = create_pdf_bytes(r)
                if pdf: st.download_button("PDF保存", pdf, "recipe.pdf", "application/pdf")

    # --- カレンダー機能追加エリア ---
    with tab_log:
        st.header("📊 あなたの自炊記録")
        if st.button("更新", key="refresh_my"): st.rerun()
        
        user_id = st.session_state['user'].id
        my_recipes = get_my_recipes(user_id)
        
        # ★ここで統計とカレンダーを表示
        if my_recipes:
            display_stats_and_calendar(my_recipes)
            st.markdown("---")
            st.subheader("📚 履歴リスト")
            for r in my_recipes:
                date_str = r['created_at'].split('T')[0]
                status = "🌏 公開" if r['is_public'] else "🔒 非公開"
                with st.expander(f"{date_str} : {r['title']} ({status})"):
                    if r.get('image_url'): st.image(r['image_url'], use_container_width=True)
                    st.write(f"**メモ:** {r['comment']}")
                    st.json(r['content'])
        else:
            st.info("まだ記録がありません。レシピを作って保存してみましょう！")

    with tab_public:
        st.header("🌏 みんなのレシピ広場")
        if st.button("更新", key="refresh_pub"): st.rerun()
        public_recipes = get_public_recipes()
        if public_recipes:
            cols = st.columns(2)
            for idx, r in enumerate(public_recipes):
                with cols[idx % 2]:
                    with st.container(border=True):
                        if r.get('image_url'): st.image(r['image_url'], use_container_width=True)
                        else: st.markdown("🍳 *No Image*")
                        st.subheader(r['title'])
                        st.caption(f"{r['created_at'].split('T')[0]}")
                        with st.expander("詳細"):
                            st.json(r['content'])
        else:
            st.info("公開レシピはまだありません。")

if __name__ == "__main__":
    main()






