"""
全ての下書きWordPress記事にPexels画像をアイキャッチとして一括設定するスクリプト
"""
import os
import base64
import requests

WP_URL = os.environ["WP_URL"].rstrip("/")
WP_USERNAME = os.environ["WP_USERNAME"]
WP_APP_PASSWORD = os.environ["WP_APP_PASSWORD"]
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

# キーワード → Pexels検索ワード（アジア系・日本風の写真が出やすいキーワード）
KEYWORD_MAP = {
    "通級":     "asian child school learning classroom",
    "ことば":   "asian child speech communication smile",
    "言語":     "asian child speak learning",
    "吃音":     "asian child speaking confidence",
    "場面緘黙": "asian child calm support therapy",
    "発達":     "asian child development learning play",
    "構音":     "asian child practice speech mouth",
    "サ行":     "asian child speech practice learning",
    "読み書き": "asian child reading book study",
    "聴覚":     "asian child listen hearing",
    "自閉":     "asian child play therapy support",
    "訓練":     "asian child therapy exercise",
    "支援":     "asian child care support family",
    "相談":     "asian parent child consultation",
    "幼児":     "asian toddler child play smile",
    "小学":     "asian child elementary school study",
    "保育":     "asian child nursery play happy",
}

DEFAULT_SEARCH = "asian child smile learning"


def get_wp_auth():
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def get_all_draft_posts():
    """全ての下書き記事を取得"""
    auth = get_wp_auth()
    posts = []
    page = 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=auth,
            params={"status": "draft", "per_page": 100, "page": page},
            timeout=15,
        )
        data = r.json()
        if r.status_code == 400 or not data:
            break
        r.raise_for_status()
        posts.extend(data)
        page += 1
    return posts


def title_to_search_term(title: str) -> str:
    """タイトルから英語検索ワードを生成"""
    for jp, en in KEYWORD_MAP.items():
        if jp in title:
            return en
    return DEFAULT_SEARCH


def fetch_pexels_image(search_term: str) -> bytes:
    """Pexels APIからアジア系の写真を取得"""
    headers = {"Authorization": PEXELS_API_KEY}
    r = requests.get(
        "https://api.pexels.com/v1/search",
        headers=headers,
        params={
            "query": search_term,
            "per_page": 5,
            "orientation": "landscape",
            "size": "large",
        },
        timeout=15,
    )
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        raise ValueError(f"'{search_term}' で写真が見つかりませんでした")

    photo = photos[0]
    img_url = photo["src"]["large2x"]
    photographer = photo.get("photographer", "Pexels")
    print(f"   📸 写真URL: {img_url[:70]}...")
    print(f"   撮影者: {photographer}")

    img_r = requests.get(img_url, timeout=30)
    img_r.raise_for_status()
    return img_r.content


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


# ===== メイン処理 =====
if not PEXELS_API_KEY:
    print("❌ PEXELS_API_KEY が設定されていません")
    exit(1)

print("📋 下書き記事を取得中...")
drafts = get_all_draft_posts()
print(f"   {len(drafts)} 件の下書きを取得しました\n")

success = 0
skipped = 0
failed = 0

for post in drafts:
    post_id = post["id"]
    title = post.get("title", {}).get("rendered", f"post-{post_id}")
    has_image = post.get("featured_media", 0)

    if has_image:
        print(f"⏭️  #{post_id}「{title}」→ 画像あり（スキップ）")
        skipped += 1
        continue

    print(f"\n🖼️  #{post_id}「{title}」")
    try:
        search_term = title_to_search_term(title)
        print(f"   検索: {search_term}")
        image_bytes = fetch_pexels_image(search_term)
        print(f"   ✅ 取得完了 ({len(image_bytes) // 1024} KB)")

        media_id = upload_image_to_wp(image_bytes, f"eyecatch-{post_id}.jpg")
        print(f"   ✅ アップロード完了（ID: {media_id}）")

        set_featured_image(post_id, media_id)
        print(f"   ✅ アイキャッチ設定完了！")
        success += 1

    except Exception as e:
        print(f"   ❌ エラー: {e}")
        failed += 1

print(f"\n{'='*40}")
print(f"✅ 設定完了: {success} 件")
print(f"⏭️  スキップ: {skipped} 件（既に画像あり）")
print(f"❌ エラー:   {failed} 件")
print(f"{'='*40}")
print(f"\n📝 確認: {WP_URL}/wp-admin/edit.php")
