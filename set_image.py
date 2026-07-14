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

# キーワード → Pexels検索ワードリスト（複数候補から記事番号で選択 → 多様性確保）
KEYWORD_MAP = {
    "通級":     ["asian boy school classroom", "japanese child school desk study",
                 "elementary school classroom asia", "child studying book pencil"],
    "ことば":   ["asian mother child communication", "japanese family talking smile",
                 "asian girl speech smile", "parent child reading together"],
    "言語":     ["speech therapy child asian", "asian boy language learning",
                 "child book reading smile asia", "japanese child learning activity"],
    "吃音":     ["asian boy speaking confidence", "child communication talk",
                 "japanese boy presentation school", "asian child talk smile"],
    "場面緘黙": ["calm child japanese indoor", "quiet shy child support",
                 "japanese child nature calm", "asian child indoor peaceful"],
    "発達":     ["asian boy outdoor play happy", "japanese child development activity",
                 "children playing park asia", "child drawing painting creative"],
    "構音":     ["asian boy mouth speech practice", "japanese child sing voice",
                 "child therapy session indoor", "speech practice child boy"],
    "サ行":     ["asian boy talking lesson", "japanese child practice speech",
                 "child language practice indoor", "boy speech therapy session"],
    "読み書き": ["asian boy reading book", "japanese child writing study",
                 "child notebook pencil school", "asian student study desk"],
    "聴覚":     ["child hearing test clinic", "asian child listen music headphone",
                 "ear health child medical", "japanese child doctor checkup"],
    "自閉":     ["child sensory play indoor", "japanese child creative activity",
                 "child therapy calm indoor", "asian boy puzzle play focus"],
    "訓練":     ["speech therapist child session", "child rehabilitation indoor",
                 "asian boy therapy exercise", "professional child therapy"],
    "支援":     ["japanese family home smile", "asian mother son indoor",
                 "family support home care", "japanese parent child together"],
    "相談":     ["japanese family consultation smile", "asian parent talk adult",
                 "family meeting indoor table", "parent child discussion warm"],
    "幼児":     ["asian toddler boy play", "japanese baby child happy",
                 "toddler indoor play colorful", "young child smile play asia"],
    "小学":     ["asian boy elementary school", "japanese school child study",
                 "child backpack school asia", "asian student classroom boy"],
    "保育":     ["japanese nursery child play", "kindergarten asia children play",
                 "childcare center indoor play", "asian children group activity"],
    "費用":     ["japanese family budget planning", "asian adult consultation desk",
                 "medical consultation professional", "family finance discussion"],
    "柏市":     ["japanese suburb family home", "chiba japan neighborhood",
                 "japanese residential area green", "japan suburb child outdoor"],
    "流山市":   ["japanese family park walk", "japan suburb child nature",
                 "japanese outdoor family smile", "asian family park weekend"],
}

DEFAULT_SEARCH_LIST = [
    "asian boy child learning smile",
    "japanese family home warm",
    "asian child outdoor happy play",
    "japanese mother child indoor",
    "child development learning asia",
]


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


def title_to_search_term(title: str, post_id: int = 0) -> str:
    """タイトルから英語検索ワードを生成（複数候補からpost_idで選択して多様性確保）"""
    for jp, candidates in KEYWORD_MAP.items():
        if jp in title:
            idx = post_id % len(candidates)
            return candidates[idx]
    idx = post_id % len(DEFAULT_SEARCH_LIST)
    return DEFAULT_SEARCH_LIST[idx]


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
        search_term = title_to_search_term(title, post_id)
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
