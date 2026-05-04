"""从 IAPP 网站爬取隐私专业词汇并导入数据库"""

import re
import sys
import os

import requests

# 将 backend 目录加入 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy.orm import Session
from app.models.vocabulary import Vocabulary

# IAPP Algolia 搜索配置（公开的搜索 API）
ALGOLIA_APP_ID = 'JQI28CT642'
ALGOLIA_API_KEY = '05142b663d0923f3d221386f59c9702c'
ALGOLIA_INDEX = 'all'
ALGOLIA_URL = f'https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query'


def strip_html(text):
    """去除 HTML 标签和实体"""
    if not text:
        return text
    from html import unescape
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def fetch_glossary_terms():
    """从 IAPP Algolia 获取所有隐私术语"""
    headers = {
        'X-Algolia-Application-Id': ALGOLIA_APP_ID,
        'X-Algolia-API-Key': ALGOLIA_API_KEY,
        'Content-Type': 'application/json',
    }
    payload = {
        'query': '',
        'filters': '_content_type:glossary_terms AND domains.domains:Privacy',
        'hitsPerPage': 1000,
        'page': 0,
        'attributesToRetrieve': ['title', 'description'],
    }

    resp = requests.post(ALGOLIA_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    terms = []
    for hit in data.get('hits', []):
        title = (hit.get('title') or '').strip()
        description = strip_html(hit.get('description') or '')
        if title:
            terms.append({'term': title, 'definition': description})

    return terms


def import_terms(terms, db: Session):
    """将术语导入数据库，跳过已存在的"""
    existing = {v.term for v in db.query(Vocabulary).filter_by(is_system=True).all()}

    added = 0
    skipped = 0
    for t in terms:
        if t['term'] in existing:
            skipped += 1
            continue

        vocab = Vocabulary(
            term=t['term'],
            definition=t['definition'] or None,
            is_system=True,
        )
        db.add(vocab)
        existing.add(t['term'])
        added += 1

    db.commit()
    return added, skipped


def main():
    print('正在从 IAPP 获取隐私术语表...')
    terms = fetch_glossary_terms()
    print(f'获取到 {len(terms)} 个术语')

    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        added, skipped = import_terms(terms, db)
        print(f'导入完成：新增 {added} 个，跳过 {skipped} 个已存在术语')
    finally:
        db.close()


if __name__ == '__main__':
    main()
