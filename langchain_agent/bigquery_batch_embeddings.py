#!/usr/bin/env python3
"""
BigQuery Batch Embeddings Generation for ESCI Products

Offloads embedding generation to Google Cloud for parallel batch processing.
Much faster than serial API calls: ~1.2M products in 15-30 minutes vs ~4.5 hours.

Usage:
    PYTHONPATH=. python bigquery_batch_embeddings.py \\
      --project gen-lang-client-0250737934 \\
      --bucket kmw-esci-embeddings-2026

    # Use text-embedding-005 instead of gemini-embedding-001:
    PYTHONPATH=. python bigquery_batch_embeddings.py \\
      --project gen-lang-client-0250737934 \\
      --bucket kmw-esci-embeddings-2026 \\
      --model text-embedding-005
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import pyarrow.parquet as pq
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import bigquery, storage

logger = logging.getLogger(__name__)

# ESCI dataset paths
BASE_DIR = Path(__file__).parent
ESCI_DATASET_DIR = BASE_DIR.parent / "esci" / "shopping_queries_dataset"
ESCI_PRODUCTS_FILE = ESCI_DATASET_DIR / "shopping_queries_dataset_products.parquet"
FULL_US_PARQUET = ESCI_DATASET_DIR / "esci_products_full_us.parquet"

# BigQuery configuration
BQ_LOCATION = "US"
BQ_DATASET_ID = "esci_embeddings"
BQ_RAW_TABLE = "products_raw"
BQ_EMBEDDINGS_TABLE = "products_with_embeddings"
BQ_CONNECTION_NAME = "vertex-ai-connection"

# Product embedding constants
PRODUCT_LOCALE = "us"
MIN_TEXT_LENGTH = 50


def setup_gcp(project_id: str) -> Tuple[bigquery.Client, storage.Client]:
    """Initialize GCP clients."""
    try:
        bq_client = bigquery.Client(project=project_id, location=BQ_LOCATION)
        storage_client = storage.Client(project=project_id)
        print(f"✓ GCP clients initialized (project: {project_id})")
        return bq_client, storage_client
    except Exception as e:
        raise RuntimeError(f"Failed to initialize GCP clients: {e}") from e


def enable_gcp_apis(project_id: str) -> None:
    """Enable required GCP APIs via gcloud."""
    print("📡 Enabling required GCP APIs...")
    apis = [
        "bigqueryconnection.googleapis.com",
        "aiplatform.googleapis.com",
        "bigquery.googleapis.com",
        "storage.googleapis.com",
    ]
    for api in apis:
        try:
            subprocess.run(
                ["gcloud", "services", "enable", api, f"--project={project_id}"],
                check=True,
                capture_output=True,
                timeout=60,
            )
            print(f"   ✓ {api}")
        except Exception as e:
            print(f"   ⚠ {api} (may already be enabled): {e}")


def ensure_connection_exists(bq_client: bigquery.Client, project_id: str) -> str:
    """Ensure BigQuery Cloud Resource Connection exists and get its name."""
    conn_id = f"{project_id}.{BQ_LOCATION}.{BQ_CONNECTION_NAME}"

    try:
        # Try to get existing connection
        conn = bq_client.get_connection(conn_id)
        print(f"✓ Using existing Cloud Resource Connection: {BQ_CONNECTION_NAME}")
        return f"projects/{project_id}/locations/{BQ_LOCATION}/connections/{BQ_CONNECTION_NAME}"
    except NotFound:
        pass

    # Create new connection
    print(f"📡 Creating Cloud Resource Connection: {BQ_CONNECTION_NAME}...")
    try:
        conn = bigquery.ConnectionConfig(
            {
                "type": "CLOUD_RESOURCE",
                "cloud_resource": {},
            }
        )
        conn_obj = bq_client.create_connection(
            bigquery.CreateConnectionRequest(
                {
                    "parent": bq_client.project_path(project_id, BQ_LOCATION),
                    "connection_id": BQ_CONNECTION_NAME,
                    "connection": conn,
                }
            )
        )
        conn_path = conn_obj.result().name
        print(f"   ✓ Created: {conn_path}")

        # Grant IAM role to auto-generated service account
        _grant_connection_iam(bq_client, project_id, conn_path)
        return conn_path
    except AlreadyExists:
        print(f"   ✓ Connection already exists")
        return f"projects/{project_id}/locations/{BQ_LOCATION}/connections/{BQ_CONNECTION_NAME}"


def _grant_connection_iam(bq_client: bigquery.Client, project_id: str, conn_path: str) -> None:
    """Grant Vertex AI User role to the connection's service account."""
    try:
        conn = bq_client.get_connection(conn_path)
        service_account = conn.properties.get("serviceAccountId")
        if not service_account:
            print(f"   ⚠ Could not get service account from connection; try manually:")
            print(f"      bq show --connection {project_id}.{BQ_LOCATION}.{BQ_CONNECTION_NAME}")
            return

        print(f"   Granting IAM role to service account: {service_account}")
        subprocess.run(
            [
                "gcloud",
                "projects",
                "add-iam-policy-binding",
                project_id,
                f"--member=serviceAccount:{service_account}",
                "--role=roles/aiplatform.user",
                "--quiet",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        print(f"   ✓ Granted roles/aiplatform.user")
    except Exception as e:
        print(f"   ⚠ Could not grant IAM (may need manual setup): {e}")


def ensure_bucket(storage_client: storage.Client, bucket_name: str) -> str:
    """Ensure GCS bucket exists."""
    bucket = storage.Bucket(storage_client, bucket_name)
    try:
        storage_client.get_bucket(bucket_name)
        print(f"✓ Using existing GCS bucket: {bucket_name}")
    except NotFound:
        print(f"📦 Creating GCS bucket: {bucket_name}...")
        bucket = storage_client.create_bucket(bucket_name)
        print(f"   ✓ Created")
    return bucket_name


def ensure_dataset(bq_client: bigquery.Client, dataset_id: str) -> str:
    """Ensure BigQuery dataset exists."""
    dataset_ref = bq_client.dataset_ref(dataset_id)
    try:
        bq_client.get_dataset(dataset_ref)
        print(f"✓ Using existing BigQuery dataset: {dataset_id}")
    except NotFound:
        print(f"📊 Creating BigQuery dataset: {dataset_id}...")
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = BQ_LOCATION
        dataset = bq_client.create_dataset(dataset, timeout=30)
        print(f"   ✓ Created")
    return dataset_id


def load_products_to_bigquery(bq_client: bigquery.Client, dataset_id: str) -> None:
    """Load ESCI products into BigQuery raw table."""
    print("📥 Loading ESCI products to BigQuery...")

    # Check source file
    if not ESCI_PRODUCTS_FILE.exists():
        raise FileNotFoundError(
            f"ESCI products file not found: {ESCI_PRODUCTS_FILE}\n"
            "Run setup.sh or download the dataset from Amazon."
        )

    # Load parquet
    print(f"   Reading {ESCI_PRODUCTS_FILE.name}...")
    df = pd.read_parquet(ESCI_PRODUCTS_FILE)
    print(f"   Total products: {len(df):,}")

    # Filter to US
    df = df[df["product_locale"] == PRODUCT_LOCALE].copy()
    print(f"   US products: {len(df):,}")

    # Deduplicate by product_id
    df = df.drop_duplicates(subset=["product_id"], keep="first").copy()
    print(f"   After deduplication: {len(df):,}")

    # Select relevant columns
    df = df[
        [
            "product_id",
            "product_title",
            "product_description",
            "product_bullet_point",
            "product_brand",
            "product_color",
            "product_locale",
        ]
    ].copy()

    # Load to BigQuery
    table_id = f"{bq_client.project}.{dataset_id}.{BQ_RAW_TABLE}"
    print(f"   Loading to BigQuery table: {table_id}...")

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )

    job = bq_client.load_table_from_dataframe(df, table_id, job_config=job_config, timeout=600)
    job.result()
    print(f"   ✓ Loaded {len(df):,} products")


def setup_embedding_model(
    bq_client: bigquery.Client, dataset_id: str, model_name: str = "gemini-embedding-001"
) -> str:
    """Create or verify BigQuery ML remote embedding model."""
    model_id = f"{bq_client.project}.{dataset_id}.embedding_model"
    conn_id = f"{bq_client.project}.{BQ_LOCATION}.{BQ_CONNECTION_NAME}"

    # Try to get existing model
    try:
        bq_client.get_model(model_id)
        print(f"✓ Using existing BigQuery ML embedding model")
        return model_id
    except NotFound:
        pass

    print(f"🤖 Creating BigQuery ML remote embedding model ({model_name})...")

    sql = f"""
    CREATE OR REPLACE MODEL `{model_id}`
    REMOTE WITH CONNECTION `{conn_id}`
    OPTIONS (endpoint = '{model_name}');
    """

    query_job = bq_client.query(sql, location=BQ_LOCATION)
    query_job.result()
    print(f"   ✓ Model created: {model_id}")
    return model_id


def generate_embeddings_batch(
    bq_client: bigquery.Client,
    dataset_id: str,
    model_id: str,
    model_name: str = "gemini-embedding-001",
) -> str:
    """Run AI.GENERATE_EMBEDDING batch job."""
    print("⚙️ Generating embeddings via BigQuery batch...")
    print(f"   Model: {model_name}")

    # Prepare text in BigQuery first
    prep_table = f"{bq_client.project}.{dataset_id}.products_prepared"
    prep_sql = f"""
    CREATE OR REPLACE TABLE `{prep_table}` AS
    SELECT
      product_id,
      product_brand,
      product_color,
      product_locale,
      product_title,
      TRIM(CONCAT(
        COALESCE(product_title, ''), '\\n',
        COALESCE(product_description, ''), '\\n',
        COALESCE(product_bullet_point, '')
      )) AS text
    FROM `{bq_client.project}.{dataset_id}.{BQ_RAW_TABLE}`
    WHERE LENGTH(TRIM(CONCAT(
      COALESCE(product_title, ''), ' ',
      COALESCE(product_description, ''), ' ',
      COALESCE(product_bullet_point, '')
    ))) >= {MIN_TEXT_LENGTH};
    """
    print("   Preparing product texts...")
    query_job = bq_client.query(prep_sql, location=BQ_LOCATION)
    query_job.result()

    # Generate embeddings
    embeddings_table = f"{bq_client.project}.{dataset_id}.{BQ_EMBEDDINGS_TABLE}"
    embeddings_sql = f"""
    CREATE OR REPLACE TABLE `{embeddings_table}` AS
    SELECT
      base.product_id,
      base.product_brand,
      base.product_color,
      base.product_locale,
      base.product_title,
      emb.embedding,
      emb.ml_generate_embedding_status
    FROM AI.GENERATE_EMBEDDING(
      MODEL `{model_id}`,
      (
        SELECT
          product_id,
          product_brand,
          product_color,
          product_locale,
          product_title,
          text
        FROM `{prep_table}`
      ),
      STRUCT(
        768 AS output_dimensionality,
        'RETRIEVAL_DOCUMENT' AS task_type,
        TRUE AS flatten_json_output
      )
    ) AS emb
    JOIN (
      SELECT product_id, product_brand, product_color, product_locale, product_title
      FROM `{bq_client.project}.{dataset_id}.{BQ_RAW_TABLE}`
    ) AS base
      ON emb.product_id = base.product_id
    WHERE emb.ml_generate_embedding_status = '';
    """

    print(f"   Running embedding generation job...")
    query_job = bq_client.query(
        embeddings_sql,
        location=BQ_LOCATION,
        job_config=bigquery.QueryJobConfig(
            priority=bigquery.QueryPriority.INTERACTIVE,
        ),
    )

    # Poll for completion
    start_time = time.time()
    while not query_job.done():
        elapsed = time.time() - start_time
        print(f"   ⏳ Job running... ({elapsed:.0f}s)", flush=True)
        time.sleep(30)

    elapsed = time.time() - start_time
    print(f"   ✓ Embeddings generated in {elapsed:.0f}s")

    # Check row count
    result = bq_client.query(
        f"SELECT COUNT(*) as cnt FROM `{embeddings_table}`",
        location=BQ_LOCATION,
    ).result()
    row_count = list(result)[0].cnt
    print(f"   Embeddings created: {row_count:,}")

    return embeddings_table


def export_embeddings_to_gcs(
    bq_client: bigquery.Client,
    bucket_name: str,
    embeddings_table: str,
) -> str:
    """Export embeddings from BigQuery to GCS as parquet."""
    print("💾 Exporting embeddings to GCS...")

    gcs_uri = f"gs://{bucket_name}/esci_embeddings/results/*.parquet"
    print(f"   Destination: {gcs_uri}")

    sql = f"""
    EXPORT DATA OPTIONS(
      uri='{gcs_uri}',
      format='PARQUET',
      overwrite=true
    ) AS
    SELECT * FROM `{embeddings_table}`;
    """

    query_job = bq_client.query(sql, location=BQ_LOCATION)

    # Poll for completion
    start_time = time.time()
    while not query_job.done():
        elapsed = time.time() - start_time
        print(f"   ⏳ Export running... ({elapsed:.0f}s)", flush=True)
        time.sleep(10)

    elapsed = time.time() - start_time
    print(f"   ✓ Export completed in {elapsed:.0f}s")
    return gcs_uri


def download_and_merge_embeddings(
    storage_client: storage.Client, bucket_name: str, local_dir: Path
) -> pd.DataFrame:
    """Download parquet shards from GCS, merge, and convert embeddings."""
    print("⬇️ Downloading and merging embeddings...")

    # Create local temp directory
    local_dir.mkdir(parents=True, exist_ok=True)
    local_shards_dir = local_dir / "temp_shards"
    local_shards_dir.mkdir(parents=True, exist_ok=True)

    # List shards in GCS
    bucket = storage_client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix="esci_embeddings/results/"))
    parquet_blobs = [b for b in blobs if b.name.endswith(".parquet")]

    if not parquet_blobs:
        raise RuntimeError(f"No parquet files found in gs://{bucket_name}/esci_embeddings/results/")

    print(f"   Found {len(parquet_blobs)} parquet shards")

    # Download shards
    for i, blob in enumerate(parquet_blobs):
        local_file = local_shards_dir / blob.name.split("/")[-1]
        print(f"   Downloading shard {i+1}/{len(parquet_blobs)}: {local_file.name}...", flush=True)
        blob.download_to_filename(str(local_file))

    # Load and merge shards
    print("   Merging shards...")
    dfs = []
    for i, local_file in enumerate(sorted(local_shards_dir.glob("*.parquet"))):
        print(f"   Loading shard {i+1}/{len(parquet_blobs)}...", flush=True)
        df_shard = pd.read_parquet(local_file)

        # Convert BigQuery ARRAY<FLOAT64> embeddings to Python lists
        if "embedding" in df_shard.columns:
            df_shard["embedding"] = df_shard["embedding"].apply(
                lambda x: x.as_py() if hasattr(x, "as_py") else list(x) if x else None
            )

        dfs.append(df_shard)

    df_merged = pd.concat(dfs, ignore_index=False)
    print(f"   ✓ Merged {len(df_merged):,} rows from {len(dfs)} shards")

    # Cleanup temp directory
    import shutil

    shutil.rmtree(local_shards_dir)

    return df_merged


def merge_embeddings_with_full_dataset(
    embeddings_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge BigQuery embeddings with full US product dataset."""
    print("🔗 Merging embeddings with full product dataset...")

    # Load or create full US dataset (without embeddings)
    if FULL_US_PARQUET.exists():
        df = pd.read_parquet(FULL_US_PARQUET)
        print(f"   Loaded existing full US dataset: {len(df):,} products")
    else:
        # Load and prepare from source
        print(f"   Loading from source: {ESCI_PRODUCTS_FILE.name}...")
        df = pd.read_parquet(ESCI_PRODUCTS_FILE)
        df = df[df["product_locale"] == PRODUCT_LOCALE].copy()
        df = df.drop_duplicates(subset=["product_id"], keep="first").copy()
        df["embedding"] = None
        print(f"   Prepared: {len(df):,} unique US products")

    # Merge embeddings
    print(f"   Merging {len(embeddings_df):,} embeddings...")
    embeddings_df = embeddings_df[["product_id", "embedding"]].copy()
    df = df.merge(embeddings_df, on="product_id", how="left", suffixes=("", "_new"))

    # Update embedding column
    if "embedding_new" in df.columns:
        df["embedding"] = df["embedding_new"].fillna(df["embedding"])
        df = df.drop(columns=["embedding_new"])

    return df


def save_embeddings_to_parquet(df: pd.DataFrame, output_file: Path) -> None:
    """Save merged embeddings to parquet."""
    print(f"💾 Saving embeddings to {output_file.name}...")
    ESCI_DATASET_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_file)
    print(f"   ✓ Saved {len(df):,} products")


def main():
    parser = argparse.ArgumentParser(
        description="Generate embeddings for ESCI products via BigQuery batch processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  PYTHONPATH=. python bigquery_batch_embeddings.py \\
    --project gen-lang-client-0250737934 \\
    --bucket kmw-esci-embeddings-2026

  # Use text-embedding-005:
  PYTHONPATH=. python bigquery_batch_embeddings.py \\
    --project gen-lang-client-0250737934 \\
    --bucket kmw-esci-embeddings-2026 \\
    --model text-embedding-005
        """,
    )
    parser.add_argument(
        "--project",
        required=True,
        help="GCP project ID",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="GCS bucket name for temporary export storage",
    )
    parser.add_argument(
        "--model",
        default="gemini-embedding-001",
        choices=["gemini-embedding-001", "text-embedding-005"],
        help="Embedding model to use (default: gemini-embedding-001)",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        print("\n🚀 BigQuery Batch Embeddings Generation")
        print(f"   Project: {args.project}")
        print(f"   Bucket: {args.bucket}")
        print(f"   Model: {args.model}\n")

        # Setup GCP
        enable_gcp_apis(args.project)
        bq_client, storage_client = setup_gcp(args.project)

        # Ensure infrastructure
        ensure_connection_exists(bq_client, args.project)
        ensure_bucket(storage_client, args.bucket)
        ensure_dataset(bq_client, BQ_DATASET_ID)

        # Load products
        load_products_to_bigquery(bq_client, BQ_DATASET_ID)

        # Setup embedding model and generate
        model_id = setup_embedding_model(bq_client, BQ_DATASET_ID, args.model)
        embeddings_table = generate_embeddings_batch(bq_client, BQ_DATASET_ID, model_id, args.model)

        # Export and download
        export_embeddings_to_gcs(bq_client, args.bucket, embeddings_table)
        embeddings_df = download_and_merge_embeddings(storage_client, args.bucket, ESCI_DATASET_DIR)

        # Merge with full dataset and save
        df = merge_embeddings_with_full_dataset(embeddings_df)
        save_embeddings_to_parquet(df, FULL_US_PARQUET)

        # Verify
        print("\n✅ BigQuery batch embedding generation complete!")
        print(f"\n📊 Verify with:")
        print(f"   PYTHONPATH=. python generate_embeddings.py --stats")
        print(f"\n📥 Ingest into OpenSearch with:")
        print(f"   PYTHONPATH=. python ingest_esci_products.py --all")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
