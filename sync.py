#!/usr/bin/env python3
"""
sync.py — синхронизация коллекций Caps Game из API CapsTradeBot
в статический data/collections.js для GitHub Pages.

Запуск:
    python3 sync.py --dry-run     # ничего не пишет, только печатает план
    python3 sync.py --no-push     # пишет data/collections.js, но не коммитит
    python3 sync.py               # полный цикл: запись + git commit + push
    python3 sync.py --force       # перепробовать размеры даже если size известен
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------- пути ----------
ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT / "data" / "collections.js"
ENRICHMENT_PATH = ROOT / "enrichment.json"
ENV_PATH = ROOT / ".env"

# ---------- константы ----------
STORAGE_BASE = "https://firebasestorage.googleapis.com/v0/b/capsgame-prod.appspot.com/o/"
SIZE_CANDIDATES = [3, 6, 9, 12, 15, 18, 21, 24, 27, 30]
PROBE_DELAY_MS = 150

TYPE_MAP = {
    "COMMON": "common",
    "COMMUNITIES": "community",
    "EVENT": "event",
    "SPECIAL": "special",
    "PREMIUM": "premium",
}


# ---------- env ----------
def load_env():
    """Читает .env (простые KEY=VALUE, без кавычек/подстановок)."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        print(f"[error] Не задана переменная окружения: {name}", file=sys.stderr)
        sys.exit(1)
    return value


# ---------- api ----------
def fetch_collections():
    url = env("CAPSTRADE_URL", "https://capstrade.rashidmingazov.ru/api/public/collection")
    token = env("CAPSTRADE_TOKEN", required=True)

    print(f"[api] GET {url}")
    resp = requests.get(url, headers={
        "Accept": "*/*",
        "Authorization": f"Bearer {token}",
    }, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"Ожидался список, получено: {type(data).__name__}")

    items = []
    for item in data:
        cid = item.get("collection_id")
        if not cid:
            continue
        raw_type = (item.get("type") or "").upper()
        items.append({
            "id": cid,
            "title": item.get("name") or cid,
            "type": TYPE_MAP.get(raw_type, "common"),
        })

    print(f"[api] Получено коллекций: {len(items)}")
    return items


# ---------- probe ----------
def probe_size(collection_id):
    """
    Возвращает размер коллекции (кратно 3) или None.
    Проверяет существование {n}.png через Range: bytes=0-0.
    """
    last_ok = None
    for n in SIZE_CANDIDATES:
        path = f"collections/{collection_id}/{n}.png"
        url = f"{STORAGE_BASE}{requests.utils.quote(path, safe='')}?alt=media"
        try:
            r = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=15, stream=True)
            # читать тело не нужно, закрываем
            r.close()
            if r.status_code in (200, 206):
                last_ok = n
            elif r.status_code == 404:
                return last_ok
            else:
                # 403/405/429 и прочее — не считаем ни существующим, ни отсутствующим
                print(f"    [probe] {collection_id} #{n}: HTTP {r.status_code}, стоп")
                return last_ok
        except requests.RequestException as e:
            print(f"    [probe] {collection_id} #{n}: {e}, стоп")
            return last_ok
        finally:
            time.sleep(PROBE_DELAY_MS / 1000)
    return last_ok


# ---------- io ----------
def load_enrichment():
    if not ENRICHMENT_PATH.exists():
        return {}
    try:
        return json.loads(ENRICHMENT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[warn] enrichment.json битый: {e}. Игнорирую.", file=sys.stderr)
        return {}


def load_prev_snapshot():
    """Парсит data/collections.js (window.CAPS_DATA = {...};) → dict по id."""
    if not SNAPSHOT_PATH.exists():
        return {}
    text = SNAPSHOT_PATH.read_text(encoding="utf-8")
    m = re.search(r"window\.CAPS_DATA\s*=\s*(\{.*\});?\s*$", text, re.DOTALL)
    if not m:
        print("[warn] Не удалось распарсить collections.js, считаю пустым.", file=sys.stderr)
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"[warn] collections.js битый JSON: {e}", file=sys.stderr)
        return {}
    return {c["id"]: c for c in data.get("collections", [])}


def write_snapshot(collections, prev, dry_run=False):
    """
    Пишет data/collections.js.
    Если коллекции не изменились (сравнение без generatedAt) — файл не трогаем,
    чтобы не создавать пустых коммитов из-за одного поля generatedAt.
    """
    # Сравнение по содержимому, без generatedAt
    prev_list = sorted(prev.values(), key=lambda c: c.get("id", "")) if isinstance(prev, dict) else []
    new_list = sorted(collections, key=lambda c: c.get("id", ""))
    if prev_list == new_list and SNAPSHOT_PATH.exists():
        print("[write] данные не изменились, файл не трогаю")
        return

    payload = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(collections),
        "collections": collections,
    }
    body = "window.CAPS_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"

    if dry_run:
        print(f"[dry-run] collections.js: {len(collections)} коллекций, {len(body)} байт (изменения есть)")
        return

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(body, encoding="utf-8")
    print(f"[write] {SNAPSHOT_PATH} ({len(body)} байт)")


# ---------- merge ----------
def build_collections(api_items, enrichment, prev, force):
    """
    api_items: [{id, title, type}]
    enrichment: {id: {size?, supply?, releasedAt?}}
    prev: {id: {...}} — предыдущий снапшот (чтобы не пробовать заново)
    """
    result = []
    probe_count = 0

    for item in api_items:
        cid = item["id"]
        enr = enrichment.get(cid) or {}
        prev_item = prev.get(cid) or {}

        # --- size ---
        if "size" in enr and enr["size"] is not None:
            size = int(enr["size"])
            size_source = "manual"
        elif not force and prev_item.get("size") is not None:
            size = prev_item["size"]
            size_source = prev_item.get("sizeSource", "probe")
        else:
            print(f"  [probe] {cid} ({item['title']})")
            size = probe_size(cid)
            size_source = "probe" if size is not None else "unknown"
            probe_count += 1
            if size is None:
                print(f"    [warn] размер не определён для {cid}")

        # --- supply / releasedAt ---
        supply = enr.get("supply") if "supply" in enr else None
        released_at = enr.get("releasedAt") if "releasedAt" in enr else None

        result.append({
            "id": cid,
            "title": item["title"],
            "type": item["type"],
            "size": size,
            "sizeSource": size_source,
            "supply": supply,
            "releasedAt": released_at,
        })

    if probe_count:
        print(f"[probe] Пробинг выполнен для {probe_count} коллекций")

    # сортировка по collection_id
    result.sort(key=lambda c: c["id"])
    return result


# ---------- ntfy ----------
def notify_ntfy(title, message, dry_run=False):
    url = os.environ.get("NTFY_URL")
    token = os.environ.get("NTFY_TOKEN")
    if not url:
        print("[ntfy] NTFY_URL не задан, пропускаю")
        return
    if dry_run:
        print(f"[dry-run][ntfy] {title}: {message}")
        return
    headers = {"Title": title, "Tags": "sparkles"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=15)
        r.raise_for_status()
        print(f"[ntfy] отправлено: {title}")
    except requests.RequestException as e:
        print(f"[warn] ntfy не отправлен: {e}", file=sys.stderr)


# ---------- git ----------
def git_commit_and_push(dry_run=False, no_push=False):
    if dry_run or no_push:
        print("[git] пропущено (dry-run / no-push)")
        return

    def run(*args, check=True):
        return subprocess.run(args, cwd=ROOT, check=check,
                              capture_output=True, text=True)

    # ничего не изменилось — выходим
    run("git", "add", "data/collections.js", check=True)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )
    if diff.returncode == 0:
        print("[git] изменений нет, коммит не нужен")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run("git", "commit", "-m", f"data: sync {ts}")
    print("[git] commit создан")

    branch = env("GIT_BRANCH", "main")
    remote = env("GIT_REMOTE", "origin")
    run("git", "push", remote, branch)
    print(f"[git] push {remote} {branch} выполнен")


# ---------- main ----------
def main():
    parser = argparse.ArgumentParser(description="Caps Gallery sync")
    parser.add_argument("--dry-run", action="store_true",
                        help="ничего не писать и не пушить")
    parser.add_argument("--no-push", action="store_true",
                        help="писать collections.js, но не коммитить/пушить")
    parser.add_argument("--force", action="store_true",
                        help="перепробовать размеры даже если size известен")
    args = parser.parse_args()

    load_env()

    try:
        api_items = fetch_collections()
    except Exception as e:
        msg = f"Не удалось получить данные из API: {e}"
        print(f"[error] {msg}", file=sys.stderr)
        notify_ntfy("Caps Gallery: sync failed", msg, dry_run=args.dry_run)
        sys.exit(1)

    if not api_items:
        msg = "API вернул 0 коллекций, снапшот не обновлён"
        print(f"[error] {msg}", file=sys.stderr)
        notify_ntfy("Caps Gallery: empty response", msg, dry_run=args.dry_run)
        sys.exit(1)

    enrichment = load_enrichment()
    prev = load_prev_snapshot()

    new_ids = [i["id"] for i in api_items if i["id"] not in prev]
    if new_ids:
        names = [i["title"] for i in api_items if i["id"] in new_ids]
        msg = f"Новые коллекции ({len(new_ids)}): {', '.join(names)}"
        print(f"[diff] {msg}")
        notify_ntfy("Caps Gallery: new collections", msg, dry_run=args.dry_run)
    else:
        print("[diff] Новых коллекций нет")

    collections = build_collections(api_items, enrichment, prev, args.force)
    write_snapshot(collections, prev, dry_run=args.dry_run)
    git_commit_and_push(dry_run=args.dry_run, no_push=args.no_push)

    print("[done]")


if __name__ == "__main__":
    main()