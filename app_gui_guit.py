import streamlit as st
import json
import os
from openai import OpenAI
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io

# --- 1. 設定 ---
# 【重要】ここにAPIキーを入れてください
#API_KEY = "APIキー" 
api_key = st.secrets["OPENAI_API_KEY"]
#client = OpenAI(api_key=API_KEY)


client = OpenAI(api_key=api_key)

# --- 2. AI関数 ---
def generate_recipe_json(ingredients, mode, condition, target, user_message):
    
    # プロンプト：モードと条件を両方反映させるように修正
    prompt = f"""
    あなたは「調理工程の効率化」に特化したプロの料理研究家です。
    ユーザーは「{target}」へのプレゼントとしてレシピを作りたいと考えています。
    以下の情報を元に、指定のJSON形式のみを出力してください。

    【ユーザー入力】
    * 食材: {ingredients}
    * 基本モード: {mode}
    * その他の条件(味の好み等): {condition}
    * 添えるメッセージ: {user_message}

    【レシピ構成のルール】
    1. 下準備で調味料を混ぜて「合わせ調味料」を作ること。
    2. 本工程は「合わせ調味料を入れる」等シンプルにすること。
    3. JSON形式のみ出力すること。余計な会話は不要。

    【出力フォーマット(JSON)】
    {{
      "title": "料理名",
      "cooking_time": "目安時間",
      "ingredients": [ {{"name": "食材名", "amount": "分量"}} ],
      "preparation": [ "下準備1", "下準備2" ],
      "steps": [ "工程1", "工程2" ],
      "chef_comment": "シェフからのアドバイス"
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 3. PDF生成関数（修正：宛名とメッセージを引数で受け取る） ---
def create_pdf_bytes(data, target_name, user_message_content):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    
    # フォント設定
    font_path = "ipaexg.ttf" 
    try:
        pdfmetrics.registerFont(TTFont('JapaneseFont', font_path))
    except:
        st.error("エラー: ipaexg.ttf が見つかりません。")
        return None

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(name='TitleJp', fontName='JapaneseFont', fontSize=24, leading=30, alignment=1, spaceAfter=20)
    heading_style = ParagraphStyle(name='HeadingJp', fontName='JapaneseFont', fontSize=16, leading=20, spaceBefore=15, spaceAfter=10, textColor=colors.darkgreen)
    body_style = ParagraphStyle(name='BodyJp', fontName='JapaneseFont', fontSize=12, leading=18)
    # メッセージ欄のデザイン
    message_style = ParagraphStyle(name='MsgJp', fontName='JapaneseFont', fontSize=14, leading=22, backColor=colors.lightyellow, borderColor=colors.orange, borderWidth=1, splitLongWords=1, spaceBefore=10, spaceAfter=10, borderPadding=10)

    story = []

    # タイトル
    story.append(Paragraph(data['title'], title_style))
    
    # ★修正箇所：宛名を正しく表示
    story.append(Paragraph(f"For: {target_name}", heading_style))
    
    story.append(Paragraph(f"調理時間: {data['cooking_time']}", body_style))
    story.append(Spacer(1, 5*mm))

    # ★修正箇所：メッセージ欄（ユーザー入力をそのまま表示）
    if user_message_content:
        story.append(Paragraph("Message:", heading_style))
        story.append(Paragraph(user_message_content, message_style))
        story.append(Spacer(1, 5*mm))

    # 材料表
    story.append(Paragraph("■ 材料", heading_style))
    ing_data = [[item['name'], item['amount']] for item in data['ingredients']]
    t = Table(ing_data, colWidths=[100*mm, 50*mm])
    t.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'JapaneseFont', 12),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.whitesmoke),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t)

    # 下準備
    story.append(Paragraph("■ 下準備 (Mise en place)", heading_style))
    for i, prep in enumerate(data['preparation'], 1):
        story.append(Paragraph(f"{i}. {prep}", body_style))
    
    # 工程
    story.append(Paragraph("■ 作り方", heading_style))
    for i, step in enumerate(data['steps'], 1):
        story.append(Paragraph(f"Step {i}: {step}", body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 4. Streamlit 画面構築 ---
def main():
    st.title("🍳 AI Recipe Gift Generator")
    st.markdown("冷蔵庫の中身から、**大切な人に贈るレシピ**を作成します。")

    with st.sidebar:
        st.header("入力情報")
        ingredients = st.text_area("食材リスト", "豚肉、余ったキャベツ、卵1個")
        
        # 誰宛か
        target = st.text_input("誰のために作りますか？（宛名）", "妻へ")
        
        # モード選択
        mode = st.selectbox("買い物モード", ["家にあるもので意地でも作る", "買い物OK！豪華にする"])
        
        # ★復活させた条件入力欄
        condition = st.text_input("その他の条件・味の好み", "ガッツリ系、ニンニク多め、辛いのOK")
        
        # メッセージ
        user_message = st.text_area("添えるメッセージ", "いつもありがとう！今日は僕が作ります。")
        
        generate_btn = st.button("レシピを生成する！")

    if generate_btn:
        with st.spinner("AIシェフが最高のレシピを考案中..."):
            # 1. AI生成
            recipe_data = generate_recipe_json(ingredients, mode, condition, target, user_message)
            
            # 2. プレビュー
            st.success(f"完成しました！：{recipe_data['title']}")
            
            # 3. PDF生成（宛名とメッセージを直接渡す）
            pdf_bytes = create_pdf_bytes(recipe_data, target, user_message)
            
            if pdf_bytes:
                st.download_button(
                    label="📄 レシピPDFをダウンロード",
                    data=pdf_bytes,
                    file_name="recipe_gift.pdf",
                    mime="application/pdf"
                )

if __name__ == "__main__":
    main()