import streamlit as st
import json
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
import io

# --- 1. 設定 & DB接続 ---
# APIキーの取得
openai_api_key = st.secrets["OPENAI_API_KEY"]
supabase_url = st.secrets["SUPABASE_URL"]
supabase_key = st.secrets["SUPABASE_KEY"]

# クライアントの初期化
client = OpenAI(api_key=openai_api_key)
supabase: Client = create_client(supabase_url, supabase_key)

# テーマカラー
PRIMARY_COLOR = colors.HexColor("#E67E22")
ACCENT_COLOR = colors.HexColor("#FDEBD0")
TEXT_COLOR = colors.HexColor("#2C3E50")

# --- 2. AI関数 ---
def generate_recipe_json(ingredients, mode, condition, target, user_message):
    prompt = f"""
    あなたは「自炊効率化のプロ」です。
    ユーザーは自分用に、手軽で美味しい料理を作りたいと考えています。
    以下の情報を元に、指定のJSON形式のみを出力してください。

    【ユーザー入力】
    * 食材: {ingredients}
    * モード: {mode}
    * 条件: {condition}
    * メモ: {user_message}

    【重要ルール】
    1. 材料リストには調味料とその分量も必ず網羅すること。
    2. 手順は「考えずに動ける」くらい具体的に。
    3. JSONのみ出力。

    【出力フォーマット(JSON)】
    {{
      "title": "料理名",
      "cooking_time": "目安時間",
      "ingredients": [ {{"name": "食材名", "amount": "分量"}} ],
      "preparation": [ "下準備1", "下準備2" ],
      "steps": [ "工程1", "工程2" ],
      "chef_comment": "コツ・ポイント"
    }}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 3. データベース操作関数 ---
def save_recipe_to_db(recipe_data, user_comment=""):
    """レシピをSupabaseに保存する"""
    try:
        data = {
            "title": recipe_data["title"],
            "content": recipe_data, # JSONデータをそのまま保存
            "comment": user_comment
        }
        supabase.table("recipes").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

def get_recent_recipes():
    """最近保存したレシピを取得する"""
    try:
        response = supabase.table("recipes").select("*").order("created_at", desc=True).limit(5).execute()
        return response.data
    except Exception as e:
        return []

# --- 4. PDF生成関数 (簡略化版) ---
def create_pdf_bytes(data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=20*mm, bottomMargin=25*mm)
    
    font_path = "ipaexg.ttf" 
    try:
        pdfmetrics.registerFont(TTFont('JapaneseFont', font_path))
    except:
        return None

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(name='TitleJp', fontName='JapaneseFont', fontSize=24, leading=30, alignment=1, spaceAfter=10, textColor=PRIMARY_COLOR)
    heading_style = ParagraphStyle(name='HeadingJp', fontName='JapaneseFont', fontSize=16, leading=20, spaceBefore=15, spaceAfter=10, textColor=TEXT_COLOR)
    body_style = ParagraphStyle(name='BodyJp', fontName='JapaneseFont', fontSize=11, leading=16, textColor=TEXT_COLOR)

    story = []
    story.append(Paragraph(data['title'], title_style))
    story.append(Paragraph(f"⏱ {data['cooking_time']}", heading_style))
    
    story.append(Paragraph("🛒 材料", heading_style))
    ing_data = []
    for item in data['ingredients']:
        ing_data.append([item['name'], item['amount']])
    t_ing = Table(ing_data, colWidths=[100*mm, 40*mm])
    t_ing.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'JapaneseFont', 11),
        ('TEXTCOLOR', (0, 0), (-1, -1), TEXT_COLOR),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_ing)

    story.append(Paragraph("🍳 作り方", heading_style))
    for i, step in enumerate(data['steps'], 1):
        story.append(Paragraph(f"Step {i}: {step}", body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 5. Streamlit 画面 ---
def main():
    st.set_page_config(page_title="My Recipe Log", page_icon="🍳")
    st.title("🍳 自炊サポート & レシピログ")

    # タブで機能を分ける
    tab1, tab2 = st.tabs(["📝 レシピ作成", "📚 保存したレシピ一覧"])

    # --- タブ1: レシピ生成 ---
    with tab1:
        st.markdown("冷蔵庫の余り物で、**自分だけの効率化レシピ**を作りましょう。")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            ingredients = st.text_area("食材リスト", "豚肉、玉ねぎ、卵")
            mode = st.selectbox("モード", ["手早く済ませたい", "ガッツリ食べたい"])
            condition = st.text_input("条件", "洗い物を減らしたい")
            user_message = st.text_area("自分へのメモ", "明日のお弁当にも入れたい")
            generate_btn = st.button("🍳 レシピを考案", type="primary")

        with col2:
            if generate_btn:
                with st.spinner("AIがレシピを構築中..."):
                    # 生成
                    recipe_data = generate_recipe_json(ingredients, mode, condition, "自分", user_message)
                    
                    # セッション状態に保存（ボタンを押しても消えないように）
                    st.session_state['current_recipe'] = recipe_data
                    st.session_state['generated'] = True

            # レシピ表示部分
            if 'generated' in st.session_state and st.session_state['generated']:
                recipe = st.session_state['current_recipe']
                
                st.subheader(f"🍽️ {recipe['title']}")
                st.write(f"⏱ **時間:** {recipe['cooking_time']}")
                st.info(f"💡 **Point:** {recipe.get('chef_comment', '')}")

                # 材料と手順
                st.write("---")
                st.write("**🛒 材料:**")
                for item in recipe['ingredients']:
                    st.write(f"- {item['name']}: {item['amount']}")
                
                st.write("**🍳 手順:**")
                for i, step in enumerate(recipe['steps'], 1):
                    st.write(f"{i}. {step}")
                
                st.write("---")
                
                # --- 保存ボタン ---
                if st.button("💾 このレシピをログに保存する"):
                    if save_recipe_to_db(recipe, user_message):
                        st.success("✅ レシピをデータベースに保存しました！「保存したレシピ一覧」タブで確認できます。")
                    else:
                        st.error("保存に失敗しました。")

                # PDFダウンロード
                pdf_bytes = create_pdf_bytes(recipe)
                if pdf_bytes:
                    st.download_button("📄 PDFで保存", pdf_bytes, "recipe.pdf", "application/pdf")

    # --- タブ2: ログ閲覧 ---
    with tab2:
        st.header("📚 過去のレシピログ")
        if st.button("🔄 更新"):
            st.rerun()
            
        recipes = get_recent_recipes()
        if recipes:
            for r in recipes:
                with st.expander(f"{r['created_at'][:10]} : {r['title']}"):
                    st.write(f"**メモ:** {r['comment']}")
                    # JSONの中身を展開して表示
                    content = r['content']
                    st.write("**材料:**")
                    for item in content.get('ingredients', []):
                        st.write(f"- {item['name']}: {item['amount']}")
        else:
            st.info("まだ保存されたレシピはありません。")

if __name__ == "__main__":
    main()


