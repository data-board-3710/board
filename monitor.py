import os, json, requests, datetime

X_TOKEN   = os.environ["X_BEARER_TOKEN"]
CLAUDE_KEY = os.environ["ANTHROPIC_API_KEY"]

KEYWORD = "ニチホ"
SEEN_FILE = "seen.json"
RESULT_FILE = "results.jsonl"
JSON_FILE = "results.json"
MAX_VIEW = 50

def fetch_posts():
    url = "https://api.x.com/2/tweets/search/recent"
    params = {"query": KEYWORD, "max_results": 10,
              "tweet.fields": "created_at,author_id",
              "expansions": "author_id", "user.fields": "username"}
    headers = {"Authorization": f"Bearer {X_TOKEN}"}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    users = {u["id"]: u.get("username","") for u in data.get("includes",{}).get("users",[])}
    out = []
    for t in data.get("data", []):
        t["username"] = users.get(t.get("author_id"), "")
        out.append(t)
    return out

def classify(text):
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": CLAUDE_KEY,
               "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    prompt = ("次の投稿を評判監視の観点で次の4つのいずれかに分類し、"
              "ラベルだけを1語で出力: 通常 / ポジティブ / ネガティブ / 誹謗中傷\n\n"
              f"投稿: {text}")
    body = {"model": "claude-haiku-4-5-20251001",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": prompt}]}
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()

LABEL2CODE = {"誹謗中傷":"bad","ネガティブ":"neg","ポジティブ":"pos","通常":"normal"}

def load_seen():
    try:
        return set(json.load(open(SEEN_FILE)))
    except FileNotFoundError:
        return set()

def load_records():
    recs = []
    try:
        with open(RESULT_FILE, encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if line: recs.append(json.loads(line))
    except FileNotFoundError:
        pass
    return recs

def main():
    seen = load_seen()
    posts = fetch_posts()
    new_records, alerts = [], []
    for p in posts:
        if p["id"] in seen:
            continue
        label = classify(p["text"])
        rec = {"id": p["id"], "text": p["text"], "label": label,
               "username": p.get("username",""),
               "created_at": p.get("created_at"),
               "fetched_at": datetime.datetime.utcnow().isoformat()}
        new_records.append(rec)
        seen.add(p["id"])
        if label == "誹謗中傷":
            alerts.append(rec)

    json.dump(list(seen), open(SEEN_FILE, "w"), ensure_ascii=False)
    with open(RESULT_FILE, "a", encoding="utf-8") as f:
        for rec in new_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 表示用 results.json を書き出す(最新MAX_VIEW件)
    allrec = load_records()
    allrec.sort(key=lambda r: r.get("fetched_at",""), reverse=True)
    view = []
    for r in allrec[:MAX_VIEW]:
        c = LABEL2CODE.get(r.get("label"),"normal")
        un = r.get("username","")
        view.append({
            "a": ("@"+un) if un else "(不明)",
            "t": r.get("text",""),
            "d": (r.get("created_at","") or "")[:16].replace("T"," "),
            "c": c
        })
    out = {"keyword": KEYWORD,
           "updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")+" UTC",
           "posts": view}
    json.dump(out, open(JSON_FILE,"w"), ensure_ascii=False, indent=1)

    if alerts:
        lines = ["⚠ 誹謗中傷を検知しました\n"]
        for a in alerts:
            url = f"https://x.com/i/status/{a['id']}"
            lines.append(f"・{a['text']}\n  {url}\n")
        open("alert_body.txt", "w", encoding="utf-8").write("\n".join(lines))
        print("ALERT")
    print(f"{len(new_records)}件 追加 / 誹謗中傷 {len(alerts)}件")

if __name__ == "__main__":
    main()
