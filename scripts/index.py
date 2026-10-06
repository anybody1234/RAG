"""Parse + chunk + embed văn bản trong data/manifest.json rồi upsert vào Qdrant dưới user_id "system".

Chạy từ thư mục gốc của repo (cần `docker compose up -d` và OPENAI_API_KEY trong .env):
    python scripts/index.py                               # mọi văn bản trong manifest
    python scripts/index.py --doc vi-bo-luat-lao-dong-2019
    python scripts/index.py --recreate                    # xoá collection rồi tạo lại

Embedding được cache theo hash nội dung chunk (data/cache/embeddings.sqlite), nên chạy lại không tốn tiền.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings
from app.core.rag_config import get_rag_config
from app.ingestion.manifest import load_manifest
from app.ingestion.pipeline import ingest_manifest_document
from app.retrieval.embedding import EmbeddingCache, EmbeddingUsage, build_embedder
from app.retrieval.index import SYSTEM_USER_ID, ensure_collection, index_document
from app.retrieval.sparse import SparseEncoder


async def run(doc_ids: list[str] | None, recreate: bool) -> int:
    config = get_rag_config()
    collection = config.collection_name
    manifest = load_manifest()
    docs = [doc for doc in manifest.documents if not doc_ids or doc.doc_id in doc_ids]
    if doc_ids and len(docs) != len(doc_ids):
        print(f"doc_id không có trong manifest: {sorted(set(doc_ids) - {doc.doc_id for doc in docs})}")
        return 1

    client = AsyncQdrantClient(url=get_settings().qdrant_url)
    cache = EmbeddingCache()
    embedder = build_embedder(config, cache)
    encoder = SparseEncoder(config.sparse.k1, config.sparse.b, config.sparse.avg_doc_len)
    try:
        created = await ensure_collection(client, collection, config.embedding.dimensions, recreate=recreate)
        print(f"config_version={config.config_version}, collection={collection}"
              f"{' (vừa tạo)' if created else ''}, user_id={SYSTEM_USER_ID}\n")
        print(f"{'doc_id':<42} {'chunk':>6} {'cache':>6} {'token mới':>10} {'$':>9} {'xoá cũ':>7} {'giây':>6}")
        total = EmbeddingUsage()
        for doc in docs:
            start = time.perf_counter()
            chunks = ingest_manifest_document(doc).chunks
            report = await index_document(client, collection, chunks, SYSTEM_USER_ID, embedder, encoder)
            total += report.usage
            print(f"{doc.doc_id:<42} {report.chunks:>6} {report.usage.cached:>6} {report.usage.tokens:>10} "
                  f"{report.usage.cost_usd:>9.5f} {report.removed:>7} {time.perf_counter() - start:>6.1f}")
        points = (await client.count(collection, exact=True)).count
        print(f"\nEmbedding: {total.requests} request, {total.tokens} token mới, ${total.cost_usd:.5f}, "
              f"{total.cached} chunk lấy từ cache. Collection có {points} point.")
    finally:
        await client.close()
        cache.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--doc", action="append", help="doc_id trong manifest (lặp lại được)")
    parser.add_argument("--recreate", action="store_true", help="xoá collection rồi tạo lại")
    args = parser.parse_args()
    return asyncio.run(run(args.doc, args.recreate))


if __name__ == "__main__":
    sys.exit(main())
