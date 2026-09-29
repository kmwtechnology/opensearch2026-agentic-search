#!/usr/bin/env python3
"""
Setup: initializes the PostgreSQL checkpoint tables, the OpenSearch index and
search pipeline, validates the local Ollama models, and bulk-loads the
precomputed corpus dump. Invoked by scripts/setup.sh; takes no arguments.
"""

import os
import sys
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql
from psycopg_pool import ConnectionPool

from core.config import (
    DATABASE_URL,
    DB_CONNECTION_KWARGS,
    DB_POOL_MAX_SIZE,
    EMBEDDINGS_MODEL,
    LLM_MODEL,
    OLLAMA_HOST,
    OPENSEARCH_INDEX_NAME,
    OPENSEARCH_SEARCH_PIPELINE,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
    QUERY_EVAL_MODEL,
    VECTOR_DIMENSION,
)

# ============================================================================
# STEP 1: POSTGRESQL DATABASE SETUP
# ============================================================================


def create_database():
    """Create the langchain_agent database if it doesn't exist"""
    print("\n[1/5] Creating PostgreSQL database and checkpoint tables...")

    try:
        # Connect to the default postgres database to create our database
        admin_conn_string = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/postgres"

        with psycopg.connect(admin_conn_string) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Check if database exists
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (POSTGRES_DB,))
                if not cur.fetchone():
                    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(POSTGRES_DB)))
                    print(f"      ✓ Database '{POSTGRES_DB}' created")
                else:
                    print(f"      ✓ Database '{POSTGRES_DB}' already exists")
    except Exception as e:
        print(f"      ✗ Error creating database: {e}")
        raise


def verify_connection():
    """Verify connection to the database"""
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
                postgres_version = version.split(",")[0]
                print(f"      ✓ Connected to: {postgres_version}")
    except Exception as e:
        print(f"      ✗ Error connecting to database: {e}")
        raise


def create_opensearch_index():
    """Create the OpenSearch index with knn and text mappings."""
    print("\n[2/5] Creating OpenSearch index...")

    try:
        from retrieval.vector_store import INDEX_MAPPING, create_opensearch_client

        client = create_opensearch_client()

        # Verify connectivity
        info = client.info()
        print(f"      ✓ Connected to OpenSearch {info['version']['number']}")

        # Create index if it doesn't exist
        if client.indices.exists(index=OPENSEARCH_INDEX_NAME):
            print(f"      ✓ Index '{OPENSEARCH_INDEX_NAME}' already exists")
        else:
            client.indices.create(index=OPENSEARCH_INDEX_NAME, body=INDEX_MAPPING)
            print(f"      ✓ Index '{OPENSEARCH_INDEX_NAME}' created (knn + text)")

    except Exception as e:
        print(f"      ✗ Error creating OpenSearch index: {e}")
        raise


def create_search_pipeline():
    """Create the hybrid search pipeline with normalization"""
    print("\n[3/5] Creating search pipeline...")

    try:
        from retrieval.vector_store import SEARCH_PIPELINE, create_opensearch_client

        client = create_opensearch_client()

        client.transport.perform_request(
            "PUT",
            f"/_search/pipeline/{OPENSEARCH_SEARCH_PIPELINE}",
            body=SEARCH_PIPELINE,
        )
        print(f"      ✓ Search pipeline '{OPENSEARCH_SEARCH_PIPELINE}' created")

    except Exception as e:
        print(f"      ✗ Error creating search pipeline: {e}")
        raise


def init_checkpoint_tables():
    """Initialize the PostgresSaver checkpoint tables"""
    try:
        # Create connection pool
        connection_kwargs = DB_CONNECTION_KWARGS.copy()
        pool = ConnectionPool(
            conninfo=DATABASE_URL, max_size=DB_POOL_MAX_SIZE, kwargs=connection_kwargs
        )

        # Initialize the checkpointer (creates tables if they don't exist)
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        pool.close()
        print("      ✓ Conversation checkpointer tables created")

    except Exception as e:
        print(f"      ✗ Error initializing checkpoint tables: {e}")
        raise


# ============================================================================
# STEP 2: LOCAL MODEL (OLLAMA) VALIDATION
# ============================================================================


def validate_ollama_models():
    """Check Ollama is up, every configured model is pulled, and embeddings fit the index."""
    from core.llm import missing_ollama_models

    print("\n[4/5] Validating local Ollama models...")
    try:
        missing = missing_ollama_models([LLM_MODEL, QUERY_EVAL_MODEL, EMBEDDINGS_MODEL])
    except OSError as e:
        print(f"      ✗ Ollama not reachable at {OLLAMA_HOST}: {e}")
        print("      Start it (`ollama serve` or the Ollama app)")
        return False
    if missing:
        for m in missing:
            print(f"      ✗ Model not pulled: {m}  (run: ollama pull {m})")
        return False

    from retrieval.embeddings import build_embeddings

    try:
        dims = len(build_embeddings().embed_query("test"))
    except Exception as e:
        print(f"      ✗ Embedding call failed: {e}")
        return False
    if dims != VECTOR_DIMENSION:
        print(
            f"      ✗ {EMBEDDINGS_MODEL} returns {dims}-dim vectors; the index expects {VECTOR_DIMENSION}"
        )
        return False

    print(f"      ✓ Ollama reachable at {OLLAMA_HOST}")
    print("      Models configured:")
    print(f"        LLM: {LLM_MODEL}")
    print(f"        Classifier: {QUERY_EVAL_MODEL}")
    print(f"        Embeddings: {EMBEDDINGS_MODEL} ({dims}-dim)")
    return True


# ============================================================================
# MAIN SETUP ORCHESTRATION
# ============================================================================


def main():
    """Run complete setup process"""
    print("\n" + "=" * 70)
    print("E-COMMERCE SEARCH AGENT - COMPLETE SETUP")
    print("=" * 70)
    print("\nThis script will:")
    print("  1. Create PostgreSQL database (for checkpoints)")
    print("  2. Create OpenSearch index (for products)")
    print("  3. Create search pipeline (for hybrid search)")
    print("  4. Validate local Ollama models")
    print("  5. Load the precomputed ESCI corpus")
    print("\n" + "=" * 70)

    try:
        create_database()
        verify_connection()
        init_checkpoint_tables()

        create_opensearch_index()
        create_search_pipeline()

        if not validate_ollama_models():
            print("\n✗ SETUP INCOMPLETE — fix the Ollama problem above, then re-run `make setup`.")
            return 1

        docs_ingest_failed = False
        precomputed_dump = (
            Path(__file__).parent.parent / "data" / "precomputed" / "dump_metadata.json"
        )

        if not precomputed_dump.exists():
            print("\n" + "=" * 70)
            print("✗ SETUP INCOMPLETE — data/precomputed/ is missing")
            print("=" * 70)
            print(
                "\nThe product corpus is a permanent, one-time export committed to this "
                "repo via Git LFS. It is not rebuilt locally — there is no ingest "
                "pipeline for it any more (see data/README.md)."
            )
            print("\nMost likely cause: Git LFS objects were never pulled. Run:")
            print("  git lfs pull")
            print("\nThen re-run setup.")
            print("\n" + "=" * 70)
            return 1

        print("\n[5/5] Loading precomputed products and attribute taxonomy...")
        print(
            "      Bulk-loading data/precomputed/*.parquet — embeddings and attribute "
            "detection were already run once and committed (Git LFS). No Ollama call, "
            "no re-embedding needed."
        )
        try:
            import subprocess

            loader_script = Path(__file__).parent / "scripts" / "load_precomputed_indices.py"
            python = Path(__file__).parent / ".venv" / "bin" / "python"
            if not python.exists():
                python = Path(sys.executable)
            subprocess.run(
                [str(python), str(loader_script)],
                cwd=str(Path(__file__).parent),
                check=True,
                env={**os.environ, "PYTHONPATH": "."},
            )
            print("      ✓ Products and attribute taxonomy loaded from precomputed dump")
        except subprocess.CalledProcessError as e:
            docs_ingest_failed = True
            print(f"      ✗ Precomputed load failed (exit {e.returncode})")

        # A failed load means zero (or stale) products are indexed — that's not
        # a state to report as "SETUP COMPLETE". Fail loud instead.
        if docs_ingest_failed:
            print("\n" + "=" * 70)
            print("✗ SETUP INCOMPLETE — precomputed load failed, no products indexed")
            print("=" * 70)
            print("\nDatabase and OpenSearch index setup succeeded above.")
            print("Fix the load issue and re-run `make setup`.")
            print("\n" + "=" * 70)
            return 1

        # Summary
        print("\n" + "=" * 70)
        print("✓ SETUP COMPLETE!")
        print("=" * 70)
        print("\nStart everything with: make dev")
        print("\n" + "=" * 70)

        return 0

    except Exception as e:
        print("\n" + "=" * 70)
        print(f"✗ SETUP FAILED: {e}")
        print("=" * 70)
        print("\nTroubleshooting:")
        print("1. PostgreSQL: Ensure Docker container is running")
        print("   docker compose up -d")
        print("2. Ollama: ensure it is running and the models are pulled (scripts/doctor.sh)")
        print("3. Product data: Ensure data/precomputed/ is populated (git lfs pull)")
        print("4. Connection: Verify config.py settings")
        print("\n" + "=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
