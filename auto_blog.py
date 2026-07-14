# -*- coding: utf-8 -*-
"""
HOPE ブログ全自動生成スクリプト
================================
キーワード選択 → Claude記事生成 → DALL-E画像生成（失敗時スキップ） → WordPress自動投稿

必要な環境変数（GitHub Secrets に設定すること）:
  ANTHROPIC_API_KEY   : AnthropicのAPIキー
  OPENAI_API_KEY      : OpenAIのAPIキー（画像生成用。未設定時は画像なしで投稿）
  WP_URL              : WordPressサイトURL（例: https://hope-kids.com）
  WP_USERNAME         : WordPressのユーザー名（例: admin）
  WP_APP_PASSWORD     : WordPressのアプリケーションパスワード
"""

import os
import json
import random
import base64
import tempfile
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import openpyxl
import requests
from openai import OpenAI

# ============================================================
# 設定
# ============================================================
KEYWORDS_FILE   = "hope-kids_keywords.xlsx"
USED_FILE       = "used_keywords.json"
WP_POST_STATUS  = "draft"     # 下書き投稿（確認してからpublishに変更可）
PRIORITY_ORDER  = ["高", "中", "低"]

# ============================================================
# HOPEサービス情報（プロンプトに埋め込む）
# ============================================================
HOPE_SERVICE_INFO = """
【サービス概要】
名称: ことばの相談室・訪問訓練 HOPE
代表: 関口 亮（言語聴覚士・国家資格保有）
所在地: 千葉県柏市若柴2-8 三貴ハウス207号室
対応エリア: 柏市・流山市を中心に千葉・茨城・埼玉・東京（訪問対応あり）
サービス: 言語聴覚士による訪問・通所の言語訓練（自費・保険外・診断書不要）
対象: ことばの遅れ・発音・吃音・学習支援・発達障害など言語に困りのあるお子さん
強み①: 国家資格（言語聴覚士）を持つ専門家による完全個別訓練
強み②: 訪問対応で自宅で受けられる（下の子がいても・通えなくても大丈夫）
強み③: 診断書・受給者証不要。グレーゾーン・診断待ちでも利用可
URL: https://hope-kids.com/
問い合わせ: https://hope-kids.com/contact-us
"""

# ============================================================
# 記事生成ルール（プロンプトに埋め込む）
# ============================================================
BLOG_RULES = """
【記事生成ルール】
■ 基本
- 文字数: 2000〜3500文字
- 文体: 「です・ます調」。専門用語には平易な説明を添える
- 見出し: H2（3〜5個）、H3（各2〜3個）
- 対象読者: 30〜40代のお母さん。子供の言語発達に不安を感じている

■ 必須要素
1. リード文（最初の200字以内）
   - 悩みへの共感 + この記事でわかること
2. LLMO対策段落
   - 「〇〇とは？」「〇〇の原因は？」に直接・簡潔に答えるブロック
   - ChatGPT・Perplexity等に引用されやすいfactualな短段落
3. E-E-A-T強化
   - 「言語聴覚士（国家資格）が解説」「専門家の視点から」を自然に2〜3回
4. 地域キーワード
   - 柏市・流山市を本文・見出しに自然に盛り込む
5. 記事末尾CTA（必ず以下をそのまま入れる）
   ---
   ことばの遅れや発音・吃音でお困りの場合は、柏市・流山市を中心に訪問対応している
   言語聴覚士のHOPEに、まずは無料でご相談ください。
   → [無料相談はこちら](https://hope-kids.com/contact-us)
   ---

■ 執筆姿勢
- 不安をあおらず、安心と受診目安をセットで示す
- 「様子見」で終わらせず、何を見ればよいかを具体化
- 数値は幅をもって提示（例: 「74〜80%前後」）
- 治療法は適応と家庭相性を書く
- 神経多様性の視点を入れつつ、支援の必要性もぼかさない

■ 禁止事項
- 競合他社の実名
- 「〇〇は発達障害です」などの断言
- 「必ず治ります」など根拠のない断定
"""

# フォーマット別の書き方ガイド
FORMAT_GUIDE = {
    "解説記事":    "原因→症状→対処法の流れで専門知識を平易に（約2500字）",
    "実践記事":    "番号リスト＋具体的なやり方。今日からできることを（約2000字）",
    "Q&A記事":     "よくある疑問に直接答える形式。LLMO対策に最も有効（約2000字）",
    "チェックリスト": "表形式で年齢別・症状別に一覧化（約1500字＋表）",
    "地域ガイド":  "「柏市で〇〇するには？」形式で地域名を前面に（約1500字）",
    "比較記事":    "「AとBの違いは？」形式で検索意図に直接回答（約2000字）",
    "専門解説":    "難しい概念をわかりやすく。LLMO引用率が高い（約2500字）",
    "共感記事":    "保護者の気持ちに寄り添う。自責感・孤独感を軽減（約2000字）",
    "相談ガイド":  "「どこに相談すればいいか」を段階的に案内（約1800字）",
    "費用解説":    "費用・料金体系を丁寧に。HOPEの自費サービスも自然に紹介（約1500字）",
    "対応記事":    "学校・園・家庭での具体的な対応方法を実践的に（約2000字）",
}

# ============================================================
# キーワード管理
# ============================================================

def load_keywords():
    """Excelからキーワード一覧を読み込む"""
    wb = openpyxl.load_workbook(KEYWORDS_FILE)
    ws = wb.active
    keywords = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # ヘッダーをスキップ
        no, category, keyword, title, persona, priority, fmt = row
        if no is None:
            continue
        keywords.append({
            "no": int(no),
            "category": category,
            "keyword": keyword,
            "title": title,
            "persona": persona,
            "priority": priority or "中",
            "format": fmt or "解説記事",
        })
    return keywords


def load_used_keywords():
    """使用済みキーワードのIDリストを読み込む"""
    if Path(USED_FILE).exists():
        with open(USED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_used_keyword(no):
    """使用したキーワードIDを記録する"""
    used = load_used_keywords()
    if no not in used:
        used.append(no)
    with open(USED_FILE, "w", encoding="utf-8") as f:
        json.dump(used, f, ensure_ascii=False, indent=2)


def pick_keyword(keywords, used_ids):
    """優先度順（高→中→低）でランダムに1件選ぶ。全消化したらリセット"""
    available = [k for k in keywords if k["no"] not in used_ids]
    if not available:
        print("⚠️ 全キーワードを消化しました。リセットして最初から始めます。")
        with open(USED_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        available = keywords

    # 優先度順に選ぶ
    for priority in PRIORITY_ORDER:
        group = [k for k in available if k["priority"] == priority]
        if group:
            return random.choice(group)

    return random.choice(available)


# ============================================================
# 記事生成（Claude API）
# ============================================================

def generate_article(kw: dict) -> str:
    """Claude APIで記事を生成する"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    format_hint = FORMAT_GUIDE.get(kw["format"], "解説記事形式で書く（約2000字）")

    prompt = f"""あなたは言語聴覚士（国家資格）の関口亮として、以下の条件でWordPressブログ記事を書いてください。

{HOPE_SERVICE_INFO}

{BLOG_RULES}

【今回の記事情報】
- No: {kw['no']}
- カテゴリ: {kw['category']}
- メインキーワード: {kw['keyword']}
- 記事タイトル（参考）: {kw['title']}
- 検索意図ペルソナ: {kw['persona']}
- フォーマット: {kw['format']}
  書き方: {format_hint}

【出力形式】
HTML形式で記事本文のみを出力してください。
- 見出しは <h2>、<h3> タグを使用（# や ## は使わない）
- 箇条書きは <ul><li> タグを使用（* や - は使わない）
- 太字は <strong> タグを使用（** は使わない）
- 段落は <p> タグで囲む
- リンクは <a href="..."> タグを使用
- HTMLタグ以外の特殊記号（#・*・**・---など）は使わない
記事末尾にWordPress設定を以下の形式で付けてください：

---【WordPress設定】---
カテゴリ: {kw['category']}
タグ: {kw['keyword']}, 柏市, 流山市, 言語聴覚士
パーマリンク: （英語スラッグ例を提案）
メタディスクリプション（120字以内）: （検索意図に応答する文）
投稿者名: 関口 亮（代表・言語聴覚士）
"""

    print(f"📝 Claude APIで記事を生成中: {kw['title']}")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


# ============================================================
# 画像生成（DALL-E 3）
# ============================================================

def generate_image(kw: dict) -> bytes:
    """DALL-E 3でアイキャッチ画像を生成して画像データを返す"""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # テーマに合ったプロンプトを作成
    image_prompt = f"""A warm and reassuring flat illustration for a Japanese children's speech therapy blog.
Theme: "{kw['keyword']}" — targeting worried Japanese mothers aged 30-40.
Style: Soft pastel colors, gentle and hopeful atmosphere, clean flat illustration style.
Scene: A caring scene of a mother and young child (age 1-6) communicating warmly —
playing, reading together, or a gentle speech therapist visiting their home.
No text. No letters. No words in the image.
Horizontal format (16:9). Child-friendly. Professional yet approachable."""

    print(f"🎨 DALL-E 2で画像を生成中...")
    response = client.images.generate(
        model="dall-e-2",
        prompt=image_prompt,
        size="1024x1024",
        n=1,
    )

    image_url = response.data[0].url
    img_response = requests.get(image_url, timeout=30)
    img_response.raise_for_status()
    return img_response.content


# ============================================================
# WordPress投稿
# ============================================================

def get_wp_auth():
    """WordPressの認証ヘッダーを返す"""
    username = os.environ["WP_USERNAME"]
    app_password = os.environ["WP_APP_PASSWORD"]
    credentials = f"{username}:{app_password}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def upload_image_to_wp(image_bytes: bytes, filename: str) -> int:
    """画像をWordPressメディアライブラリにアップロードしてIDを返す"""
    wp_url = os.environ["WP_URL"].rstrip("/")
    headers = get_wp_auth()
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    headers["Content-Type"] = "image/png"

    print(f"⬆️ WordPressに画像をアップロード中...")
    response = requests.post(
        f"{wp_url}/wp-json/wp/v2/media",
        headers=headers,
        data=image_bytes,
        timeout=60,
    )
    response.raise_for_status()
    media_id = response.json()["id"]
    print(f"   → メディアID: {media_id}")
    return media_id


def parse_wp_settings(article_text: str) -> dict:
    """記事末尾のWordPress設定ブロックを解析する"""
    settings = {
        "slug": "",
        "meta_description": "",
        "tags": [],
        "category": "",
    }

    lines = article_text.split("\n")
    in_settings = False
    for line in lines:
        if "【WordPress設定】" in line:
            in_settings = True
            continue
        if not in_settings:
            continue
        if line.startswith("パーマリンク"):
            slug_part = line.split(":", 1)[-1].strip()
            # スラッグ例から英語部分だけ取り出す
            import re
            match = re.search(r'[a-z][a-z0-9\-]+', slug_part)
            if match:
                settings["slug"] = match.group()
        elif line.startswith("メタディスクリプション"):
            settings["meta_description"] = line.split(":", 1)[-1].strip()
        elif line.startswith("タグ"):
            tags_str = line.split(":", 1)[-1].strip()
            settings["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]
        elif line.startswith("カテゴリ"):
            settings["category"] = line.split(":", 1)[-1].strip()

    return settings


def get_or_create_tag(wp_url, headers, tag_name) -> int:
    """タグIDを取得（なければ作成）"""
    r = requests.get(
        f"{wp_url}/wp-json/wp/v2/tags",
        headers=headers,
        params={"search": tag_name},
    )
    data = r.json()
    if data:
        return data[0]["id"]
    r2 = requests.post(
        f"{wp_url}/wp-json/wp/v2/tags",
        headers=headers,
        json={"name": tag_name},
    )
    return r2.json()["id"]


def post_to_wordpress(article_text: str, kw: dict, media_id: int = 0) -> str:
    """WordPressに記事を投稿してURLを返す"""
    wp_url = os.environ["WP_URL"].rstrip("/")
    auth_headers = get_wp_auth()
    content_headers = {**auth_headers, "Content-Type": "application/json"}

    # 記事本文（WordPress設定ブロックを除いた部分）
    body = article_text
    if "---【WordPress設定】---" in article_text:
        body = article_text.split("---【WordPress設定】---")[0].strip()

    # WordPress設定の解析
    wp_settings = parse_wp_settings(article_text)

    # タイトルを抽出（HTML h1タグ優先、なければkw["title"]）
    import re as _re
    title = kw["title"]
    h1_match = _re.search(r'<h1[^>]*>(.*?)</h1>', body, _re.IGNORECASE | _re.DOTALL)
    if h1_match:
        title = _re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()

    # タグIDの取得・作成
    tag_ids = []
    for tag_name in wp_settings.get("tags", [kw["keyword"], "柏市", "流山市", "言語聴覚士"]):
        try:
            tag_id = get_or_create_tag(wp_url, auth_headers, tag_name)
            tag_ids.append(tag_id)
        except Exception:
            pass

    # スラッグ
    slug = wp_settings.get("slug") or f"hope-blog-{kw['no']}"

    post_data = {
        "title": title,
        "content": body,
        "status": WP_POST_STATUS,
        "slug": slug,
        "tags": tag_ids,
        "excerpt": wp_settings.get("meta_description", ""),
        "author": 1,  # デフォルトの投稿者（必要なら変更）
    }

    # アイキャッチ画像がある場合のみ設定
    if media_id:
        post_data["featured_media"] = media_id

    # 認証テスト（/users/me で認証が通るか確認）
    print(f"🌐 投稿先URL: {wp_url}")
    print(f"🔑 WordPress認証テスト中...")
    auth_test = requests.get(
        f"{wp_url}/wp-json/wp/v2/users/me",
        headers=auth_headers,
        timeout=10,
    )
    if auth_test.status_code == 200:
        me = auth_test.json()
        print(f"   ✅ 認証OK: ユーザー={me.get('name')} / ロール={me.get('roles')}")
    else:
        print(f"   ⚠️ 認証テスト失敗: HTTP {auth_test.status_code}")
        print(f"   詳細: {auth_test.text[:300]}")

    print(f"📤 WordPressに記事を投稿中...")
    response = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts",
        headers=content_headers,
        json=post_data,
        timeout=30,
    )
    if not response.ok:
        print(f"⚠️ WP APIエラー HTTP {response.status_code}: {response.text[:500]}")
    response.raise_for_status()
    post_url = response.json().get("link", "")
    print(f"   → 投稿URL: {post_url}")
    return post_url


# ============================================================
# メイン処理
# ============================================================

def main():
    print("=" * 50)
    print(f"🚀 HOPE ブログ自動生成スタート: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # 1. キーワード選択
    keywords = load_keywords()
    used_ids = load_used_keywords()
    kw = pick_keyword(keywords, used_ids)
    print(f"\n📌 選択キーワード: No.{kw['no']} 「{kw['keyword']}」")
    print(f"   タイトル: {kw['title']}")
    print(f"   カテゴリ: {kw['category']} / 優先度: {kw['priority']} / フォーマット: {kw['format']}")

    # 2. 記事生成
    article_text = generate_article(kw)
    print(f"\n✅ 記事生成完了（{len(article_text)}文字）")

    # 3. 画像生成（失敗しても記事投稿は続行する）
    media_id = 0
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        try:
            image_bytes = generate_image(kw)
            print(f"✅ 画像生成完了（{len(image_bytes) // 1024}KB）")

            # 4. 画像アップロード
            filename = f"hope-blog-{kw['no']}-{datetime.now().strftime('%Y%m%d')}.png"
            media_id = upload_image_to_wp(image_bytes, filename)
            print(f"✅ 画像アップロード完了")
        except Exception as img_err:
            print(f"⚠️ 画像生成/アップロード失敗（スキップして記事投稿を続行）: {img_err}")
    else:
        print("⚠️ OPENAI_API_KEY 未設定のため画像生成をスキップ")

    # 5. 記事投稿
    post_url = post_to_wordpress(article_text, kw, media_id)
    print(f"✅ 記事投稿完了")

    # 6. 使用済みとして記録
    save_used_keyword(kw["no"])

    # 7. 最終投稿情報をファイルに保存（デバッグ・確認用）
    wp_url_env = os.environ.get("WP_URL", "未設定")
    last_post = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "keyword_no": kw["no"],
        "keyword": kw["keyword"],
        "title": kw["title"],
        "wp_url": wp_url_env,
        "post_link": post_url,
    }
    with open("last_post_info.json", "w", encoding="utf-8") as f:
        json.dump(last_post, f, ensure_ascii=False, indent=2)
    print(f"💾 投稿情報を last_post_info.json に保存しました")

    print("\n" + "=" * 50)
    print(f"🎉 完了！")
    print(f"   キーワード: No.{kw['no']} 「{kw['keyword']}」")
    print(f"   投稿URL: {post_url}")
    print(f"   投稿先サイト: {wp_url_env}")
    print(f"   残りキーワード: {len(keywords) - len(load_used_keywords())}件")
    print("=" * 50)


if __name__ == "__main__":
    main()
