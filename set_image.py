"""
テスト用：既存のWordPress記事にUnsplash画像をアイキャッチとして設定する
"""
import os
import base64
import requests

WP_URL = os.environ["WP_URL"].rstrip("/")
WP_USERNAME = os.environ["WP_USERNAME"]
WP_APP_PASSWORD = os.environ["WP_APP_PASSWORD"]
POST_ID = int(os.environ.get("POST_ID", "3006"))

# キーワード → 英語検索ワードの簡易マッピング
KEYWORD_MAP = {
    "通級": "speech therapy classroom children",
    "ことば": "child speech language therapy",
    "言語": "speech language pathology child",
    "吃音": "child speech therapy communication",
    "場面緘黙": "shy child therapy support",
    "発達": "child development therapy",
    "構音": "speech articulation therapy child",
    "サ行": "speech therapy child practice",
}

def get_wp_auth():
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}"}

def get_post_info(post_id):
    """投稿のキーワード情報を取得"""
    auth = get_wp_auth()
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=auth,
        timeout=10,
    )
    if r.status_code == 200:
        return r.json()
    return {}

def keyword_to_english(title: str) -> str:
    """タイトルからUnsplash用の英語キーワードを生成"""
    for jp, en in KEYWORD_MAP.items():
        if jp in title:
            return en
    return "speech therapy children japan"  # デフォルト

def fetch_unsplash_image(search_term: str) -> bytes:
    """Pexels APIから関連画像を取得（PEXELS_API_KEY が必要）
    フォールバック: picsum.photos のランダム高品質写真"""
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    if pexels_key:
        # Pexels API（テーマに合った写真）
        headers = {"Authorization": pexels_key}
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers,
            params={"query": search_term, "per_page": 1, "orientation": "landscape"},
            timeout=15,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if photos:
            img_url = photos[0]["src"]["large2x"]
            print(f"   ✅ Pexels から取得: {img_url[:60]}...")
            img_r = requests.get(img_url, timeout=30)
            img_r.raise_for_status()
            return img_r.content

    # フォールバック: picsum.photos（ランダム高品質写真、APIキー不要）
    url = "https://picsum.photos/1200/630"
    print(f"   📸 picsum.photos からランダム写真を取得中...")
    r = requests.get(url, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.content

def upload_image_to_wp(image_bytes: bytes, filename: str) -> int:
    """WordPressメディアライブラリにアップロード"""
    auth = get_wp_auth()
    headers = {
        **auth,
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "image/jpeg",
    }
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/media",
        headers=headers,
        data=image_bytes,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]

def set_featured_image(post_id: int, media_id: int):
    """投稿にアイキャッチ画像を設定"""
    auth = get_wp_auth()
    headers = {**auth, "Content-Type": "application/json"}
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=headers,
        json={"featured_media": media_id},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

# ===== メイン処理 =====
print(f"🔍 投稿 #{POST_ID} の情報を取得中...")
post = get_post_info(POST_ID)
title = post.get("title", {}).get("rendered", "")
print(f"   タイトル: {title}")

search_term = keyword_to_english(title)
print(f"\n🖼️  Unsplash から画像を取得中...")
image_bytes = fetch_unsplash_image(search_term)
print(f"   ✅ 画像取得完了 ({len(image_bytes) // 1024} KB)")

print(f"\n📤 WordPress にアップロード中...")
media_id = upload_image_to_wp(image_bytes, f"eyecatch-post{POST_ID}.jpg")
print(f"   ✅ アップロード完了（メディアID: {media_id}）")

print(f"\n🔗 投稿 #{POST_ID} にアイキャッチを設定中...")
set_featured_image(POST_ID, media_id)
print(f"   ✅ 設定完了！")

print(f"\n👀 確認URL:")
print(f"   {WP_URL}/wp-admin/post.php?post={POST_ID}&action=edit")
