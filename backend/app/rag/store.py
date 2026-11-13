"""Retrieval over a project's uploaded documents.

Embeddings are stored as JSON in the ``chunks`` table and compared in Python,
which works identically on SQLite and PostgreSQL. Per-project limits keep this
fast; swap in pgvector here if the corpus ever needs to grow.
"""
import math
import re
from collections import Counter

EMBEDDING_MODEL = 'text-embedding-3-small'
EMBED_BATCH = 64
TOKEN = re.compile(r'[a-z0-9_]{2,}')


def ref(document_id, ordinal):
    return f'doc:{document_id}#{ordinal}'


REF_PATTERN = re.compile(r'doc:[0-9a-f]{32}#\d+')


def embed(client, texts):
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH):
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=[t[:8000] for t in texts[start:start + EMBED_BATCH]])
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return vectors


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _tokens(text):
    return TOKEN.findall(text.lower())


def _keyword_scores(query, chunks):
    """BM25-style lexical scoring; used in demo mode or for chunks without embeddings."""
    terms = set(_tokens(query))
    if not terms:
        return [0.0] * len(chunks)
    docs = [Counter(_tokens(c['text'] + ' ' + c['location'])) for c in chunks]
    avg = sum(sum(d.values()) for d in docs) / max(len(docs), 1) or 1
    n = len(docs)
    scores = []
    for d in docs:
        length = sum(d.values()) or 1
        score = 0.0
        for t in terms:
            df = sum(1 for other in docs if t in other)
            if not df or t not in d:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            tf = d[t]
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / avg))
        scores.append(score)
    return scores


def search(chunks, query, k=5, query_embedding=None):
    """Rank chunks for a query. Returns dicts with ref, filename, location, text and score."""
    if not chunks or not query.strip():
        return []
    lexical = _keyword_scores(query, chunks)
    top = max(lexical) or 1.0
    ranked = []
    for chunk, lex in zip(chunks, lexical):
        if query_embedding is not None and chunk.get('embedding'):
            # Hybrid: semantic similarity dominates, lexical match breaks ties.
            score = _cosine(query_embedding, chunk['embedding']) + 0.15 * (lex / top)
        else:
            score = lex / top
        ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, chunk in ranked[:k]:
        if score <= 0:
            continue
        results.append({'ref': ref(chunk['document_id'], chunk['ordinal']), 'filename': chunk['filename'],
                        'location': chunk['location'], 'text': chunk['text'], 'score': round(score, 4)})
    return results
