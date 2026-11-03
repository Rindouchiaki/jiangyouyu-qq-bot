"""从 shadowverse-wins.com 抓卡组（只收 GrandMaster 10 连胜以上）。

    python tools/szb_crawl.py                     # 指定 + 无限，各职业前 3 页
    python tools/szb_crawl.py --env 指定 --pages 1
    python tools/szb_crawl.py --dry-run            # 只看抓到几条，不下载不入库

站点是服务端渲染的，列表页参数：
    ?leader=<R|E|W|D|B|Nmr|Nm>&mp=GrandMaster&format=<rotation|unlimited>&more=10&page=<n>

职业只能靠 leader 参数定（页面不按条目给职业）；卡组名站点没有，从推文正文里
抠「特征词 + 职业词」，翻不出来就保留日文原词。
"""

import argparse
import hashlib
import html
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

import szb_decks  # noqa: E402

BASE = "https://shadowverse-wins.com/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) jiangyouyu-bot/0.1 (+personal deck index)"

# leader 参数 → 中文职业（站点里 Nm=ネメシス/超越者，Nmr=ナイトメア/梦魇，别搞反）
LEADERS = {
    "R": "皇家",
    "E": "妖精",
    "W": "法师",
    "D": "龙族",
    "B": "主教",
    "Nm": "超越者",
    "Nmr": "梦魇",
}
ENV_PARAM = {"指定": "rotation", "无限": "unlimited"}

CLASS_JP = {
    "ロイヤル": "皇家",
    "エルフ": "妖精",
    "ウィッチ": "法师",
    "ドラゴン": "龙族",
    "ビショップ": "主教",
    "ネメシス": "超越者",
    "ナイトメア": "梦魇",
}

# 常见特征词，翻不出来就保留日文
ARCH_JP = {
    "海賊": "海盗",
    "兎": "兔子",
    "融合": "融合",
    "ランプ": "跳费",
    "秘術": "秘术",
    "機械": "机械",
    "進化": "进化",
    "自然": "自然",
    "教会": "教会",
    "回復": "回复",
    "ドラゴン": "龙",
    "ミッドレンジ": "中速",
    "コントロール": "控制",
    "アグロ": "快攻",
    "コンボ": "组合技",
}

_NOISE = re.compile(
    r"(グランド?マスター?|グラマス|ラマス|マスター|ダイヤ(モンド)?|サファイア|ルビー|トパーズ|ブロンズ)帯?"
    r"|現在|環境|帯$"
)

_CLASS_WORD = re.compile("|".join(CLASS_JP))
_ARCH_IN_TEXT = re.compile(
    "([ァ-ヶー一-龠A-Za-z0-9]{1,10})(ロイヤル|エルフ|ウィッチ|ドラゴン|ビショップ|ネメシス|ナイトメア)"
)

_SECTION = re.compile(r"<section>(.*?)</section>", re.S)
_WINS = re.compile(r'<div class="wins"><em>(\d+)</em>')
_TEXT = re.compile(r'<p class="text">(.*?)</p>', re.S)
_IMG = re.compile(r'<img src="(https://pbs\.twimg\.com/media/[^"]+)"')
_MID = re.compile(r"/single\.php\?manageId=(\d+)")
_NAME = re.compile(r'<div class="name"><a[^>]*>(.*?)</a>')
_TIME = re.compile(r'<div class="timestamp"><a[^>]*>([^<]+)</a>')


def _strip_tags(raw: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", raw or "")).strip()


def _deck_name(text: str, cls: str, wins: str, mid: str) -> str:
    """从推文里抠特征词，拼「特征 + 职业简称」；抠不到就退化成 职业-连胜-编号。"""
    m = _ARCH_IN_TEXT.search(text or "")
    arch = ""
    if m:
        arch = _NOISE.sub("", m.group(1))
        for jp, cn in ARCH_JP.items():
            arch = arch.replace(jp, cn)
        arch = re.sub(r"[^\w\u4e00-\u9fa5]", "", arch)
        arch = arch[-8:]
    name = f"{arch}{szb_decks.CLASS_SHORT[cls]}" if arch else f"{cls}-{wins}连胜-{mid[-4:]}"
    return name[: szb_decks.MAX_NAME]


def fetch_page(client: httpx.Client, env: str, leader: str, page: int) -> str:
    params = {
        "leader": leader,
        "mp": "GrandMaster",
        "format": ENV_PARAM[env],
        "more": "10",
        "page": str(page),
    }
    resp = client.get(BASE, params=params, timeout=25)
    resp.raise_for_status()
    return resp.text


def parse_entries(page_html: str) -> list[dict]:
    out = []
    for block in _SECTION.findall(page_html):
        wins = _WINS.search(block)
        mid = _MID.search(block)
        if not wins or not mid:
            continue
        imgs = _IMG.findall(block)
        if not imgs:
            continue
        out.append(
            {
                "wins": int(wins.group(1)),
                "manage_id": mid.group(1),
                "text": _strip_tags(_TEXT.search(block).group(1)) if _TEXT.search(block) else "",
                "images": imgs,
                "player": _strip_tags(_NAME.search(block).group(1)) if _NAME.search(block) else "",
                "time": _strip_tags(_TIME.search(block).group(1)) if _TIME.search(block) else "",
            }
        )
    return out


def _fetch_images(client: httpx.Client, urls: list[str], limit: int) -> list[bytes]:
    """把一条投稿里的图都下下来（最多 limit 张），单张失败就跳过。"""
    shots: list[bytes] = []
    for url in urls[:limit]:
        try:
            resp = client.get(
                url,
                timeout=30,
                headers={"Referer": "https://shadowverse-wins.com/", "User-Agent": UA},
            )
            resp.raise_for_status()
            if len(resp.content) > szb_decks.MAX_IMAGE_MB * 1024 * 1024:
                print(f"  图太大，跳过一张：{url}")
                continue
            shots.append(resp.content)
        except Exception as exc:  # noqa: BLE001
            print(f"  图下载失败（{type(exc).__name__}）：{url}")
        time.sleep(0.4)
    return shots


def crawl_env(
    client: httpx.Client,
    env: str,
    pages: int,
    max_per_class: int,
    dry: bool,
    max_images: int = 4,
    refresh_images: bool = False,
) -> dict:
    stat = {"seen": 0, "new": 0, "skip": 0, "fail": 0}
    known = {(d.get("source_id") or "") for d in szb_decks.list_decks(None, None, None, limit=5000)}
    known = {k for k in known if k}
    for leader, cls in LEADERS.items():
        added = 0
        for page in range(1, pages + 1):
            try:
                body = fetch_page(client, env, leader, page)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{env}/{cls}] 第 {page} 页抓取失败：{type(exc).__name__}: {exc}")
                stat["fail"] += 1
                time.sleep(2)
                continue
            entries = parse_entries(body)
            if not entries:
                break
            for e in entries:
                if e["wins"] < 10:
                    continue
                stat["seen"] += 1
                if e["manage_id"] in known:
                    if refresh_images and not dry:
                        deck = next(
                            (
                                d
                                for d in szb_decks.list_decks(None, None, None, limit=5000)
                                if d.get("source_id") == e["manage_id"]
                            ),
                            None,
                        )
                        if deck is not None:
                            shots = _fetch_images(client, e["images"], max_images)
                            if shots:
                                count = szb_decks.replace_images(deck["id"], shots)
                                print(f"  [{env}/{cls}] ~ {deck['id']} 补图 {count} 张")
                            else:
                                print(f"  [{env}/{cls}] ~ {deck['id']} 补图失败，保持原样")
                    stat["skip"] += 1
                    continue
                name = _deck_name(e["text"], cls, str(e["wins"]), e["manage_id"])
                if dry:
                    print(f"  [{env}/{cls}] {name} {e['wins']}连胜 {e['manage_id']} {e['images'][0]}")
                    stat["new"] += 1
                    added += 1
                    if added >= max_per_class:
                        break
                    continue
                try:
                    shots = _fetch_images(client, e["images"], max_images)
                    if not shots:
                        print(f"  [{env}/{cls}] 一张图都没下来，跳过 {name}")
                        stat["skip"] += 1
                        continue
                    deck = szb_decks.add_deck(
                        name=name,
                        cls=cls,
                        env=env,
                        images=shots,
                        source="scrape",
                        note=e["text"],
                        meta={
                            "source_id": e["manage_id"],
                            "source_url": f"{BASE}single.php?manageId={e['manage_id']}",
                            "winstreak": e["wins"],
                            "player": e["player"],
                            "season": e["time"][:10],
                            "sha256": hashlib.sha256(b"\x00".join(shots)).hexdigest(),
                        },
                    )
                    known.add(e["manage_id"])
                    stat["new"] += 1
                    added += 1
                    print(
                        f"  [{env}/{cls}] + {deck['id']} {deck['name']}"
                        f"（{e['wins']}连胜，{len(deck.get('images') or [])} 张图）"
                    )
                except szb_decks.DeckError as exc:
                    stat["skip"] += 1
                    print(f"  [{env}/{cls}] 跳过：{exc}")
                except Exception as exc:  # noqa: BLE001
                    stat["fail"] += 1
                    print(f"  [{env}/{cls}] 入库失败：{type(exc).__name__}: {exc}")
                time.sleep(1.0)
                if added >= max_per_class:
                    break
            if added >= max_per_class:
                break
            time.sleep(1.0)
    return stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=["指定", "无限", "both"], default="both")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--max-per-class", type=int, default=6)
    ap.add_argument("--max-images", type=int, default=4, help="每条投稿最多存几张图")
    ap.add_argument("--refresh-images", action="store_true", help="同步已有卡组的图（补/加图）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    envs = ["指定", "无限"] if args.env == "both" else [args.env]
    total = {"seen": 0, "new": 0, "skip": 0, "fail": 0}
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        for env in envs:
            print(f"=== {env} ===")
            st = crawl_env(
                client,
                env,
                args.pages,
                args.max_per_class,
                args.dry_run,
                max_images=args.max_images,
                refresh_images=args.refresh_images,
            )
            for k in total:
                total[k] += st[k]
    print(
        f"完成：看到 {total['seen']} 条，新增 {total['new']} 条，跳过 {total['skip']}，失败 {total['fail']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
