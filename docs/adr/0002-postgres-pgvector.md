# ADR 0002 — Postgres + pgvector instead of a dedicated vector database

**Status:** Accepted
**Date:** 2026-01

## Context

RiMo's long-term memory needs semantic recall over distilled lessons
(architecture decisions, bug fixes, successful patterns). That implies vector
embeddings and nearest-neighbour search. The market default is a dedicated
vector database (Pinecone, Weaviate, Qdrid, Milvus).

## Decision

Store embeddings in **Postgres using the `pgvector` extension**, in the same
database as all transactional state, with an HNSW index for approximate nearest
neighbour search.

## Rationale

- **One store, one operational surface.** Memory records reference projects and
  tasks. Keeping them in the same database means foreign keys, transactional
  writes (a memory and its source task commit together), and a single thing to
  back up, secure, and migrate.
- **No cross-store consistency problem.** With a separate vector DB, every write
  is a two-phase dance (write the row, then upsert the vector) with its own
  failure modes. Here it's one transaction.
- **pgvector + HNSW is genuinely good enough.** At RiMo's scale (thousands to low
  millions of memories per deployment), HNSW cosine search in Postgres is fast
  and accurate. We are nowhere near the scale where a specialised store's
  performance edge matters.
- **Portability.** Most managed Postgres providers support pgvector, so operators
  don't take on a second managed service.

## Consequences

- Very large deployments (hundreds of millions of vectors) might eventually
  outgrow pgvector's performance envelope; at that point memory could be sharded
  out without touching the rest of the schema, since recall goes through one
  service (`app/memory/service.py`).
- We manage the HNSW index parameters (`m`, `ef_construction`) ourselves rather
  than getting them tuned by a vendor.

## Alternatives considered

- **Pinecone / Weaviate / Qdrant.** More features at scale, but a second
  datastore to operate, secure, and keep consistent with Postgres — unjustified
  for the scale and the tight coupling between memories and relational entities.
