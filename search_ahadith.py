#!/usr/bin/env python3
"""
سكريبت للبحث في قاعدة بيانات الأحاديث المحلية (data/ahadith.db).
"""

import argparse
import sqlite3
from pathlib import Path

from fetch_ahadith import BOOKS


def search_hadiths(db_path: Path, query: str, book: str | None = None, limit: int = 10):
    if not db_path.exists():
        print(f"قاعدة البيانات غير موجودة: {db_path}")
        print("قم بتشغيل `python3 fetch_ahadith.py` أولاً لتحميل البيانات.")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    sql = """
        SELECT h.book_key, h.id_in_book, h.arabic, h.english_text
        FROM hadiths_fts f
        JOIN hadiths h ON h.id = f.rowid
        WHERE hadiths_fts MATCH ?
    """
    params: list = [query]
    if book:
        sql += " AND h.book_key = ?"
        params.append(book)
    sql += " LIMIT ?"
    params.append(limit)

    cur.execute(sql, params)
    results = cur.fetchall()
    conn.close()

    if not results:
        print("لم يتم العثور على نتائج مطابقة.")
        return

    for idx, (book_key, num, arabic, english) in enumerate(results, 1):
        book_name = BOOKS.get(book_key, book_key)
        print("=" * 60)
        print(f"[{idx}] {book_name} - حديث رقم {num}")
        print("-" * 60)
        print(arabic)
        if english:
            print(f"\n[EN]: {english}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="البحث في قاعدة بيانات الأحاديث")
    parser.add_argument("query", help="كلمة أو عبارة للبحث")
    parser.add_argument("--book", choices=list(BOOKS.keys()), help="تصفية حسب كتاب معين")
    parser.add_argument("--limit", type=int, default=5, help="عدد النتائج (الافتراضي: 5)")
    parser.add_argument("--db", default="data/ahadith.db", help="مسار قاعدة البيانات")
    args = parser.parse_args()

    search_hadiths(Path(args.db), args.query, args.book, args.limit)


if __name__ == "__main__":
    main()
