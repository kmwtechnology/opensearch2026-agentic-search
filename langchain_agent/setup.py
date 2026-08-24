#!/usr/bin/env python3
"""
Unified Setup Script for E-Commerce Search Agent
Initializes PostgreSQL database, loads ESCI product data, and validates Google AI API key.
This is the single entry point for complete system setup from scratch

Usage:
    python setup.py                    # Full setup with ESCI products
    python setup.py --skip-docs        # Setup without loading products
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Tuple

import psycopg
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql
from psycopg_pool import ConnectionPool

from config import (
    DATABASE_URL,
    DB_CONNECTION_KWARGS,
    DB_POOL_MAX_SIZE,
    EMBEDDINGS_MODEL,
    GOOGLE_API_KEY,
    LLM_MODEL,
    OPENSEARCH_INDEX_NAME,
    OPENSEARCH_SEARCH_PIPELINE,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
    QUERY_EVAL_MODEL,
    RERANKER_MODEL,
    VECTOR_DIMENSION,
)

# Document chunking settings
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


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
        from vector_store import INDEX_MAPPING, SEARCH_PIPELINE, create_opensearch_client

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
        from vector_store import SEARCH_PIPELINE, create_opensearch_client

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
# STEP 2: GOOGLE AI API VALIDATION
# ============================================================================


def validate_google_api():
    """Validate Google API key by testing an embedding call"""
    print("\n[5/7] Validating Google AI API key...")

    if not GOOGLE_API_KEY:
        print("      ✗ GOOGLE_API_KEY not set in environment")
        print("      Set it in .env or export GOOGLE_API_KEY=your-key")
        return False

    try:
        embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDINGS_MODEL, output_dimensionality=VECTOR_DIMENSION
        )
        result = embeddings.embed_query("test")
        print(f"      ✓ Google AI API key is valid")
        print(f"      ✓ Embedding dimension: {len(result)}")
        print(f"      Models configured:")
        print(f"        LLM: {LLM_MODEL}")
        print(f"        Classifier: {QUERY_EVAL_MODEL}")
        print(f"        Embeddings: {EMBEDDINGS_MODEL}")
        print(f"        Reranker: {RERANKER_MODEL} (Google AI)")
        return True
    except Exception as e:
        print(f"      ✗ Google AI API validation failed: {e}")
        print("      Check your GOOGLE_API_KEY in .env")
        return False


# ============================================================================
# STEP 3: SAMPLE DATA LOADING
# ============================================================================


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks"""
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]

        if chunk.strip():
            chunks.append(chunk)

        start = end - overlap
        if end == len(text):
            break

    return chunks


def load_documents_from_directory(docs_dir: str) -> List[Tuple[str, str]]:
    """Load all text documents from a directory"""
    documents = []
    docs_path = Path(docs_dir)

    if not docs_path.exists():
        print(f"      ✗ Documents directory not found: {docs_dir}")
        return documents

    txt_files = list(docs_path.glob("*.txt"))
    if not txt_files:
        print(f"      ⚠ No .txt files found in {docs_dir}")
        return documents

    for file_path in txt_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                documents.append((file_path.name, content))
                print(f"      ✓ Loaded: {file_path.name} ({len(content)} chars)")
        except Exception as e:
            print(f"      ✗ Error loading {file_path.name}: {e}")

    return documents


def verify_data_load() -> bool:
    """Verify that documents were loaded into OpenSearch"""
    try:
        from vector_store import create_opensearch_client

        client = create_opensearch_client()
        count = client.count(index=OPENSEARCH_INDEX_NAME, body={"query": {"match_all": {}}})[
            "count"
        ]

        print(f"      ✓ Chunks in OpenSearch: {count}")
        return count > 0

    except Exception as e:
        print(f"      ✗ Error verifying load: {e}")
        return False


# ============================================================================
# MAIN SETUP ORCHESTRATION
# ============================================================================


def main():
    """Run complete setup process"""
    parser = argparse.ArgumentParser(description="Setup LangChain Agent")
    parser.add_argument(
        "--skip-docs", action="store_true", help="Skip document loading (database setup only)"
    )
    parser.add_argument("--skip-models", action="store_true", help="Skip Google AI API validation")
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
        print("  4. Validate Google AI API key")
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

        # Step 2: Google AI API validation (optional)
        if not args.skip_models:
            validate_google_api()

        # Step 3: Product + Judgment Data Loading via Lucille ETL
        if not args.skip_docs:
            print("\n[6/7] Loading ESCI products and judgments via Lucille ETL...")
            print(
                "      Requires Java 17+ and Maven. Embeddings are precomputed — no API calls needed."
            )
            try:
                import subprocess

                lucille_script = Path(__file__).parent / "scripts" / "lucille_ingest.sh"
                lucille_args = [str(lucille_script)]
                if args.reset_index:
                    lucille_args.append("--reset-index")
                result = subprocess.run(
                    lucille_args,
                    cwd=str(Path(__file__).parent),
                    check=True,
                )
                print("      ✓ Products and judgments loaded via Lucille ETL")
            except subprocess.CalledProcessError as e:
                print(f"      ⚠ Lucille ingest failed (exit {e.returncode})")
                print("      Check prerequisites: java -version (17+) and mvn -version (3.8+)")
                print("      Retry manually: bash langchain_agent/scripts/lucille_ingest.sh")
            except FileNotFoundError:
                print("      ⚠ lucille_ingest.sh not found — skipping Lucille ingest")
                print("      Run manually: bash langchain_agent/scripts/lucille_ingest.sh")

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
        print("2. Google AI: Ensure GOOGLE_API_KEY is set in .env")
        print("3. ESCI Dataset: Ensure files are present in ../esci/shopping_queries_dataset/")
        print("4. Connection: Verify config.py settings")
        print("\n" + "=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
