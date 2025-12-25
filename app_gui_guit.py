import streamlit as st
import json
import io
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

# --- 2. 認証関係の関数 (新機能) ---
def init_session():
    """セッションの初期化"""
    if 'user' not in st.session_state:
        st.session_state['user'] = None

def login_user(email, password):
    """ログイン処理"""
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state['user'] = response.user
        st.success("ログインしました！")
        st.rerun()
    except Exception as e:
        st.error(f"ログインエラー: メールアドレスかパスワードが間違っています。")

def signup_user(email, password):
    """新規登録処理"""
    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        st.session_state['user'] = response.user
        st.success("アカウント作成成功！自動的にログインします。")
        st.rerun()
    except Exception as e:
        st.error(f"登録エラー: {e}")

def logout_user():
    """ログアウト処理"""
    supabase.auth.sign_out()
    st.session_state['user'] = None
    st.rerun()

# --- 3. アプリのメイン機能（AI & DB） ---

def generate_recipe_json(ingredients, mode, condition, user_message):
    prompt = f"""
    あなたは「自炊効率化のプロ」です。
    ユーザーは自分用に、手軽で美味しい料理を作りたいと考えています。
    以下の情報を元に、指定のJSON形式のみを出力してください。
    
    【ユーザー入力】
    * 食材: {ingredients}
    * モード: {mode}
    * 条件: {condition}
    * メモ: {user_message}

    【出力フォーマット(JSON)】
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

def save_recipe_to_db(recipe_data, user_comment, user_id):
    """レシピを保存（ユーザーID付き）"""
    try:
        data = {
            "user_id": user_id,  # 誰のデータか記録
            "title": recipe_data["title"],
            "content": recipe_data,
            "comment": user_comment
        }
        supabase.table("recipes").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

def get_my_recipes(user_id):
    """自分のレシピだけを取得"""
    try:
        # .eq("user_id", user_id) で自分のデータだけフィルターする
        response = supabase.table("recipes").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        return []

# PDF生成関数（簡略版）
def create_pdf_bytes(data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    font_path = "ipaexg.ttf" 
    try:
        pdfmetrics.registerFont(TTFont('JapaneseFont', font_path))
    except:
        return None
    styles = getSampleStyleSheet()
    story = [Paragraph(data['title'], ParagraphStyle(name='Title', fontName='JapaneseFont', fontSize=20))]
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("■材料", ParagraphStyle(name='H1', fontName='JapaneseFont', fontSize=14)))
    for item in data['ingredients']:
        story.append(Paragraph(f"・{item['name']} : {item['amount']}", ParagraphStyle(name='Body', fontName='JapaneseFont')))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("■作り方", ParagraphStyle(name='H1', fontName='JapaneseFont', fontSize=14)))
    for i, step in enumerate(data['steps'], 1):
        story.append(Paragraph(f"{i}. {step}", ParagraphStyle(name='Body', fontName='JapaneseFont')))
    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 4. 画面制御（メイン） ---
def main():
    st.set_page_config(page_title="My Recipe Log", page_icon="🍳")
    init_session()

    # --- ログインしていない時 ---
    if st.session_state['user'] is None:
        st.title("🍳 Recipe Log - ログイン")
        st.markdown("自分だけのレシピ帳を作るには、ログインしてください。")
        
        tab1, tab2 = st.tabs(["ログイン", "新規登録"])
        
        with tab1:
            email = st.text_input("メールアドレス", key="login_email")
            password = st.text_input("パスワード", type="password", key="login_pass")
            if st.button("ログイン", type="primary"):
                login_user(email, password)
        
        with tab2:
            st.warning("※現在はテスト運用のめ、適当なメールアドレスでも登録できます。")
            new_email = st.text_input("メールアドレス", key="signup_email")
            new_password = st.text_input("パスワード（6文字以上）", type="password", key="signup_pass")
            if st.button("アカウント作成"):
                signup_user(new_email, new_password)
        
        return  # ここで処理を止める（メイン画面を見せない）

    # --- ログインしている時（メインアプリ） ---
    
    # サイドバーにユーザー情報とログアウトボタン
    with st.sidebar:
        st.write(f"ログイン中: {st.session_state['user'].email}")
        if st.button("ログアウト"):
            logout_user()

    st.title("🍳 自炊サポート & ログ")
    
    tab_create, tab_log = st.tabs(["📝 レシピ作成", "📚 自分のレシピ帳"])

    # タブ1: レシピ作成
    with tab_create:
        col1, col2 = st.columns([1, 2])
        with col1:
            ingredients = st.text_area("食材", "豚肉、玉ねぎ")
            mode = st.selectbox("モード", ["手早く", "ガッツリ"])
            condition = st.text_input("条件", "洗い物少なく")
            user_message = st.text_area("メモ", "お弁当用")
            if st.button("レシピ考案", type="primary"):
                with st.spinner("AI思考中..."):
                    recipe = generate_recipe_json(ingredients, mode, condition, user_message)
                    st.session_state['current_recipe'] = recipe
        
        with col2:
            if 'current_recipe' in st.session_state:
                r = st.session_state['current_recipe']
                st.subheader(r['title'])
                st.write(f"⏱ {r['cooking_time']}")
                
                # 材料表示
                st.write("**🛒 材料**")
                for i in r['ingredients']: st.write(f"- {i['name']} {i['amount']}")
                
                # 手順表示
                st.write("**🍳 手順**")
                for idx, s in enumerate(r['steps'], 1): st.write(f"{idx}. {s}")

                st.markdown("---")
                # 保存ボタン（ユーザーIDを渡す！）
                if st.button("💾 自分のログに保存"):
                    user_id = st.session_state['user'].id
                    if save_recipe_to_db(r, user_message, user_id):
                        st.success("保存しました！")
                
                # PDF
                pdf = create_pdf_bytes(r)
                if pdf: st.download_button("PDF保存", pdf, "recipe.pdf", "application/pdf")

    # タブ2: ログ閲覧（自分のデータだけ！）
    with tab_log:
        st.header("📚 あなたの料理ログ")
        if st.button("更新"): st.rerun()
        
        # 自分のIDでフィルタリングして取得
        user_id = st.session_state['user'].id
        my_recipes = get_my_recipes(user_id)
        
        if my_recipes:
            for r in my_recipes:
                # 日付変換
                date_str = r['created_at'].split('T')[0]
                with st.expander(f"{date_str} : {r['title']}"):
                    st.write(f"メモ: {r['comment']}")
                    st.json(r['content']) # 詳細データ
        else:
            st.info("保存されたレシピはまだありません。")

if __name__ == "__main__":
    main()



