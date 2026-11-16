"""X(Twitter) の新着ツイートを Discord フォーラムチャンネルへ「1ツイート=1スレッド」で投稿する。

GitHub Actions から定期実行される想定。外部ライブラリ不要（Python標準ライブラリのみ）。
ツイート取得には無料の非公式API (api.fxtwitter.com) を使う。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

# ===== 設定 =====
# アカウント: (スレッド名のラベル, フォーラムのタグID)
# タグIDは README の「タグIDの調べ方」を参照。空文字ならタグなしで投稿。
ACCOUNTS = {
    "Yuzu1581": ("メイン", "1571743783043858473"),
    "Gat_Blitz": ("FPS", "1571743823648923748"),
}
INCLUDE_RETWEETS = False   # True にするとリツイートも投稿する
INCLUDE_REPLIES = False    # True にするとリプライも投稿する
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
UA = "tweet-to-discord-relay/1.0"
# ================

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()


def http_json(url, data=None):
    body = None
    headers = {"User-Agent": UA}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read()
        return json.loads(raw) if raw else None


def fetch_tweets(user):
    data = http_json(f"https://api.fxtwitter.com/2/profile/{user}/statuses")
    tweets = []
    for t in data.get("results", []):
        if t.get("type") != "status":
            continue
        is_rt = bool(t.get("reposted_by"))
        if is_rt and not INCLUDE_RETWEETS:
            continue
        if t.get("replying_to") and not INCLUDE_REPLIES:
            continue
        if not is_rt and (t.get("author") or {}).get("screen_name", "").lower() != user.lower():
            continue
        tweets.append(t)
    tweets.sort(key=lambda t: int(t["id"]))
    return tweets


def make_thread_name(label, text):
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else "(画像・動画のみ)"
    name = f"【{label}】{first}"
    return name[:97] + "…" if len(name) > 100 else name


def post_to_discord(label, tag_id, tweet):
    author = (tweet.get("author") or {}).get("screen_name", "")
    link = f"https://fxtwitter.com/{author}/status/{tweet['id']}"  # Discordで画像/動画付きの埋め込みになる
    payload = {
        "thread_name": make_thread_name(label, tweet.get("text")),
        "content": link,
    }
    if tag_id:
        payload["applied_tags"] = [str(tag_id)]
    for attempt in range(3):
        try:
            http_json(WEBHOOK_URL, payload)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429:  # レート制限
                time.sleep(5 * (attempt + 1))
                continue
            raise


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    if not WEBHOOK_URL:
        sys.exit("DISCORD_WEBHOOK_URL が設定されていません")
    state = load_state()
    errors = 0
    for user, (label, tag_id) in ACCOUNTS.items():
        try:
            tweets = fetch_tweets(user)
        except Exception as e:
            print(f"[{user}] 取得失敗: {e}")
            errors += 1
            continue
        last_id = state.get(user)
        if last_id is None:
            # 初回は過去ツイートを大量投稿しないよう、最新IDを記録するだけ
            state[user] = tweets[-1]["id"] if tweets else "0"
            print(f"[{user}] 初回実行: {len(tweets)}件を既読として記録")
            continue
        new = [t for t in tweets if int(t["id"]) > int(last_id)]
        for t in new:
            post_to_discord(label, tag_id, t)
            state[user] = t["id"]
            print(f"[{user}] 投稿: {t['id']}")
            time.sleep(1)
        if not new:
            print(f"[{user}] 新着なし")
    save_state(state)
    if errors == len(ACCOUNTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
