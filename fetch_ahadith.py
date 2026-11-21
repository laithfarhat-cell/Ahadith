#!/usr/bin/env python3
"""
سكريبت لتحميل كتب الحديث التسعة وبناء قاعدة بيانات SQLite محلية للبحث السريع.
المصدر: مستودع AhmedBaset/hadith-json على GitHub
"""

import argparse
import json
import sqlite3
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

ARCHIVE_URL = "https://codeload.github.com/AhmedBaset/hadith-json/zip/refs/heads/main"

BOOKS = {
    "bukhari": "صحيح البخاري",
    "muslim": "صحيح مسلم",
    "abudawud": "سنن أبي داود",
    "tirmidhi": "جامع الترمذي",
    "nasai": "سنن النسائي",
    "ibnmajah": "سنن ابن ماجه",
    "malik": "موطأ مالك",
    "ahmed": "مسند الإمام أحمد",
    "darimi": "سنن الدارمي",
}


def ensure_books_downloaded(selected: list[str], json_dir: Path) -> None:
    json_dir.mkdir(parents=True, exist_ok=True)
    missing = [k for k in selected if not (json_dir / f"{k}.json").exists()]
    if not missing:
        for k in selected:
            print(f"[موجود مسبقاً] {BOOKS[k]} ({json_dir / f'{k}.json'})")
        return

    print(f"[جاري التحميل] أرشيف كتب الحديث من {ARCHIVE_URL} ...")
    req = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "Ahadith-Fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        archive_bytes = resp.read()
    print(f"[تم التحميل] حجم الأرشيف: {len(archive_bytes) / 1024 / 1024:.2f} MB")

    with zipfile.ZipFile(BytesIO(archive_bytes)) as zf:
        for member in zf.namelist():
            if "/db/by_book/the_9_books/" in member and member.endswith(".json"):
                book_name = Path(member).stem
                if book_name in selected:
                    dest = json_dir / f"{book_name}.json"
                    dest.write_bytes(zf.read(member))
                    print(f"[تم الاستخراج] {BOOKS.get(book_name, book_name)} -> {dest}")


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            arabic_title TEXT,
            english_title TEXT
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_key TEXT NOT NULL,
            chapter_id INTEGER NOT NULL,
            arabic_title TEXT,
            english_title TEXT,
            UNIQUE(book_key, chapter_id)
        );

        CREATE TABLE IF NOT EXISTS hadiths (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_key TEXT NOT NULL,
            hadith_id INTEGER,
            id_in_book INTEGER,
            chapter_id INTEGER,
            arabic TEXT,
            english_narrator TEXT,
            english_text TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS hadiths_fts USING fts5(
            book_key,
            arabic,
            english_text,
            content='hadiths',
            content_rowid='id'
        );
        """
    )
    conn.commit()
    return conn


def import_book_to_db(conn: sqlite3.Connection, book_key: str, json_path: Path) -> int:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    cur = conn.cursor()

    # Check if already imported
    cur.execute("SELECT COUNT(*) FROM hadiths WHERE book_key = ?", (book_key,))
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"[موجود في القاعدة] {BOOKS[book_key]} ({existing} حديث)")
        return existing

    metadata = data.get("metadata", {})
    arabic_meta = metadata.get("arabic", {})
    english_meta = metadata.get("english", {})

    cur.execute(
        """
        INSERT OR IGNORE INTO books (key, arabic_title, english_title)
        VALUES (?, ?, ?)
        """,
        (
            book_key,
            arabic_meta.get("title", BOOKS[book_key]),
            english_meta.get("title", book_key),
        ),
    )

    for ch in data.get("chapters", []):
        cur.execute(
            """
            INSERT OR IGNORE INTO chapters (book_key, chapter_id, arabic_title, english_title)
            VALUES (?, ?, ?, ?)
            """,
            (
                book_key,
                ch.get("id", 0),
                ch.get("arabic", ""),
                ch.get("english", ""),
            ),
        )

    hadiths = data.get("hadiths", [])
    rows = []
    for h in hadiths:
        eng = h.get("english") or {}
        rows.append(
            (
                book_key,
                h.get("id"),
                h.get("idInBook"),
                h.get("chapterId"),
                h.get("arabic", ""),
                eng.get("narrator", "") if isinstance(eng, dict) else "",
                eng.get("text", "") if isinstance(eng, dict) else str(eng),
            )
        )

    cur.executemany(
        """
        INSERT INTO hadiths (
            book_key, hadith_id, id_in_book, chapter_id,
            arabic, english_narrator, english_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    # Rebuild FTS index for newly inserted rows
    cur.execute("INSERT INTO hadiths_fts(hadiths_fts) VALUES('rebuild')")
    conn.commit()
    print(f"[تم الاستيراد] {BOOKS[book_key]}: {len(rows)} حديث")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="تحميل كتب الحديث وبناء قاعدة بيانات SQLite"
    )
    parser.add_argument(
        "--book",
        choices=["all", *BOOKS.keys()],
        default="all",
        help="اختر كتاباً محدداً أو 'all' لتحميل الكتب التسعة (الافتراضي: all)",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="مجلد حفظ البيانات (الافتراضي: data)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    json_dir = data_dir / "json"
    db_path = data_dir / "ahadith.db"

    selected = list(BOOKS.keys()) if args.book == "all" else [args.book]
    ensure_books_downloaded(selected, json_dir)
    conn = init_db(db_path)

    total = 0
    for key in selected:
        json_file = json_dir / f"{key}.json"
        total += import_book_to_db(conn, key, json_file)

    conn.close()
    print(f"\nاكتمل! إجمالي الأحاديث المستوردة في {db_path}: {total}")


if __name__ == "__main__":
    main()
