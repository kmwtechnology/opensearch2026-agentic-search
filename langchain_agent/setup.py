#!/usr/bin/env python3
"""
Unified Setup Script for E-Commerce Search Agent
Initializes PostgreSQL database, loads ESCI product data, and validates the local Ollama models.
This is the single entry point for complete system setup from scratch

Usage:
    python setup.py                    # Full setup with ESCI products
    python setup.py --skip-docs        # Setup without loading products
"""

import argparse
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
    print("\n[1/7] Creating database...")

    try:
        # Connect to the default postgres database to create our database
        if POSTGRES_HOST.startswith("/cloudsql/"):
            admin_conn_string = (
                f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@/postgres?host={POSTGRES_HOST}"
            )
        else:
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


def create_opensearch_index(reset: bool = False):
    """Create the OpenSearch index with knn and text mappings.

    Args:
        reset: If True, delete an existing index before recreating it. Used by
               --reset-index to guarantee a fresh knn_vector mapping even if a
               prior (broken or auto-mapped) index already exists.
    """
    print("\n[2/7] Creating OpenSearch index...")

    try:
        from retrieval.vector_store import INDEX_MAPPING, create_opensearch_client

        client = create_opensearch_client()

        # Verify connectivity
        info = client.info()
        print(f"      ✓ Connected to OpenSearch {info['version']['number']}")

        # When reset=True, delete any existing index so the next create always
        # uses INDEX_MAPPING (knn_vector + analyzers). Without this, an auto-
        # created or stale index would be silently skipped by the exists() check.
        if reset and client.indices.exists(index=OPENSEARCH_INDEX_NAME):
            client.indices.delete(index=OPENSEARCH_INDEX_NAME)
            print(f"      ✓ Index '{OPENSEARCH_INDEX_NAME}' deleted (reset)")

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
    print("\n[3/7] Creating search pipeline...")

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


def init_metadata_table():
    """Initialize conversation metadata table"""
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_metadata (
                        thread_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                print("      ✓ Conversation metadata table created")
    except Exception as e:
        print(f"      ✗ Error initializing metadata table: {e}")
        raise


# ============================================================================
# STEP 2: LOCAL MODEL (OLLAMA) VALIDATION
# ============================================================================


def validate_ollama_models():
    """Check Ollama is up, every configured model is pulled, and embeddings fit the index."""
    from core.llm import missing_ollama_models

    print("\n[5/7] Validating local Ollama models...")
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
    parser = argparse.ArgumentParser(description="Setup LangChain Agent")
    parser.add_argument(
        "--skip-docs", action="store_true", help="Skip document loading (database setup only)"
    )
    parser.add_argument(
        "--skip-models", action="store_true", help="Skip local Ollama model validation"
    )
    parser.add_argument(
        "--reset-index",
        action="store_true",
        help="Delete the existing OpenSearch index before creating a new one (forces re-index with new mapping)",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip PostgreSQL setup (OpenSearch index + search pipeline only). Used by lucille_ingest.sh --reset-index on CI runners that have no Postgres.",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("E-COMMERCE SEARCH AGENT - COMPLETE SETUP")
    print("=" * 70)
    print("\nThis script will:")
    if not args.skip_db:
        print("  1. Create PostgreSQL database (for checkpoints)")
    print("  2. Create OpenSearch index (for products)")
    print("  3. Create search pipeline (for hybrid search)")
    if not args.skip_models:
        print("  4. Validate local Ollama models")
    if not args.skip_docs:
        print("  5. Load ESCI e-commerce products")
    print("\n" + "=" * 70)

    try:
        # Step 1: PostgreSQL Setup (checkpoints only) — skipped on CI runners
        if not args.skip_db:
            create_database()
            verify_connection()
            init_checkpoint_tables()
            init_metadata_table()

        # Step 2-3: OpenSearch Setup (documents + search)
        create_opensearch_index(reset=args.reset_index)
        create_search_pipeline()

        # Step 2: local model validation (optional)
        if not args.skip_models:
            validate_ollama_models()

        # Step 3: Product + Judgment Data Loading via Lucille ETL
        docs_ingest_failed = False
        if not args.skip_docs:
            print("\n[6/7] Loading ESCI products and judgments via Lucille ETL...")
            print(
                "      Runs via Docker by default (no local Java/Maven needed). Embeddings are precomputed — no API calls needed."
            )
            print("      Seeding color taxonomy (discovery pass, then a products pass)...")
            try:
                import subprocess

                lucille_script = Path(__file__).parent / "scripts" / "lucille_ingest.sh"
                lucille_args = [str(lucille_script)]
                if args.reset_index:
                    lucille_args.append("--reset-index")
                # setup.py only runs on first-time setup, so this is always a
                # fresh cluster with an empty taxonomy store (see CLAUDE.md: "A
                # fresh cluster's taxonomy store is empty and nothing seeds it
                # implicitly"). Mandatory, not optional: without it, every
                # color attribute_filter query returns zero results until
                # someone happens to run `make seed-taxonomy` by hand. The
                # "waterproof" attribute type is deliberately NOT seeded here —
                # it starts empty and is grown entirely by the live enrichment
                # flywheel (see attribute_discovery.py's WATERPROOF_CANONICALS
                # comment).
                lucille_args.append("--seed-taxonomy")
                result = subprocess.run(
                    lucille_args,
                    cwd=str(Path(__file__).parent),
                    check=True,
                )
                print("      ✓ Products and judgments loaded via Lucille ETL")
            except subprocess.CalledProcessError as e:
                docs_ingest_failed = True
                print(f"      ✗ Lucille ingest failed (exit {e.returncode})")
                print("      Check prerequisites: docker -v (default path), or")
                print(
                    "      java -version (21+) and mvn -version (3.8+) if LUCILLE_USE_DOCKER=false"
                )
                print(
                    "      Retry manually: bash langchain_agent/scripts/lucille_ingest.sh --seed-taxonomy"
                )
            except FileNotFoundError:
                docs_ingest_failed = True
                print("      ✗ lucille_ingest.sh not found — Lucille ingest skipped")
                print(
                    "      Run manually: bash langchain_agent/scripts/lucille_ingest.sh --seed-taxonomy"
                )

        # A failed ingest means zero (or stale) products are indexed — that's not
        # a state to report as "SETUP COMPLETE". Fail loud instead of continuing
        # past it; --skip-docs remains the way to deliberately opt out of ingest.
        if docs_ingest_failed:
            print("\n" + "=" * 70)
            print("✗ SETUP INCOMPLETE — Lucille ingest failed, no products indexed")
            print("=" * 70)
            print("\nDatabase, OpenSearch index, and API key setup succeeded above.")
            print("Fix the ingest issue and retry:")
            print("  bash langchain_agent/scripts/lucille_ingest.sh --reset-index --seed-taxonomy")
            print("\n" + "=" * 70)
            return 1

        # Summary
        print("\n" + "=" * 70)
        print("✓ SETUP COMPLETE!")
        print("=" * 70)
        print("\nYou can now run the agent:")
        print("  python main.py")
        print("\nExample queries:")
        print("  - Find me wireless headphones")
        print("  - Show me blue backpacks")
        print("  - What products do you have from Brand X?")
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
        print("3. ESCI Dataset: Ensure files are present in ../esci/shopping_queries_dataset/")
        print("4. Connection: Verify config.py settings")
        print("\n" + "=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
