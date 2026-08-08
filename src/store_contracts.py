"""Version contracts for persistent and rebuildable local stores.

Schema numbers live here so builders, health checks, and tests compare against
one authority. Increment a component only when its on-disk shape or required
metadata changes; migrations remain owned by the module that writes the store.
"""

from __future__ import annotations


STUDY_MEMORY_SCHEMA_VERSION = 8
CONCEPT_INVENTORY_SCHEMA_VERSION = 1
VAULT_INDEX_SCHEMA_VERSION = 1
VAULT_MARKDOWN_COMPONENT = "vault_markdown"
VAULT_BINARY_COMPONENT = "vault_binary"
ANKI_CACHE_SCHEMA_VERSION = 1
MINI_FTS_SCHEMA_VERSION = 1

SQLITE_SCHEMA_VERSIONS = {
    "study_memory": STUDY_MEMORY_SCHEMA_VERSION,
    "concept_inventory": CONCEPT_INVENTORY_SCHEMA_VERSION,
    "vault_index": VAULT_INDEX_SCHEMA_VERSION,
    "anki_vector_cache": ANKI_CACHE_SCHEMA_VERSION,
    "mini_rag_fts": MINI_FTS_SCHEMA_VERSION,
}
