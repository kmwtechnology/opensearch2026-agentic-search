# GCP First-Timer Deployment Guide

Deploy Agentic Hybrid Search to Google Cloud Platform (GCP) from scratch. This guide walks through every prerequisite and configuration step needed to go from a cloned repo to a live, auto-updating deployment pipeline.

**Parent:** [Operations Guide](README.md)

---

## Prerequisites

Before starting, ensure you have:

1. **GCP Account with Billing Enabled**
   - Create one at [console.cloud.google.com](https://console.cloud.google.com)
   - Enable billing: Console → Billing → Link a billing account to your project
   - (You'll need a valid payment method; Cloud Run and Cloud SQL are free-tier eligible but billing is required)

2. **Google Cloud CLI (`gcloud`)**
   ```bash
   # macOS (via Homebrew)
   brew install google-cloud-sdk
   
   # Or download: https://cloud.google.com/sdk/docs/install
   
   # Authenticate
   gcloud auth login
   gcloud auth configure-docker
   ```

3. **Docker Installed**
   - [Download Docker Desktop](https://www.docker.com/products/docker-desktop)
   - Required for local image build in `deploy.sh`

4. **Java 21+ and Maven**
   ```bash
   # macOS
   brew install openjdk@21
   brew install maven
   
   # Or download from https://www.oracle.com/java/technologies/downloads/
   # and https://maven.apache.org/download.cgi
   
   java -version  # should show 17+
   mvn -version   # should show 3.8+
   ```
   - Required by Lucille ETL for product and judgment ingestion

5. **Google AI API Key**
   - Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   - Click "Create API key"
   - Copy the key (you'll paste it during `deploy.sh`)

---

## Step 1 — Create a GCP Project

Create a new GCP project and link billing:

```bash
# Choose a unique project ID (e.g., "agentic-hybrid-search-dev")
PROJECT_ID="agentic-hybrid-search-dev"

# Create the project
gcloud projects create $PROJECT_ID --name="Agentic Hybrid Search"

# Set it as your default
gcloud config set project $PROJECT_ID

# Get your billing account ID
gcloud billing accounts list
# Output: ID  DISPLAY_NAME  ACCOUNT_STATUS
#         01A2B3-C4D5E6-F7G8H9  My Billing Account  OPEN

# Link billing to the project (replace 01A2B3-C4D5E6-F7G8H9 with your ID)
BILLING_ID="01A2B3-C4D5E6-F7G8H9"
gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ID

# Verify
gcloud projects describe $PROJECT_ID
```

---

## Step 2 — Fork the Repo and Configure GitHub Actions

The CI/CD pipeline automatically deploys on every push to `main`. GitHub Actions uses Workload Identity Federation (WIF) instead of long-lived API keys — this is the most critical step.

### 2a. Fork the Repository

1. Go to [github.com/kmwtechnology/opensearch2026-agentic-search](https://github.com/kmwtechnology/opensearch2026-agentic-search)
2. Click **Fork** and fork to your account

### 2b. Set Up Workload Identity Federation

WIF allows GitHub Actions to authenticate as a GCP service account without storing long-lived keys. Copy and run these commands in order:

```bash
PROJECT_ID="agentic-hybrid-search-dev"  # from Step 1
GITHUB_ORG="your-github-username"        # YOUR GitHub username or org
GITHUB_REPO="opensearch2026-agentic-search"      # your forked repo name

# Get your project number (needed below)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
echo "Project Number: $PROJECT_NUMBER"

# 1. Create the WIF pool
gcloud iam workload-identity-pools create "github-actions" \
  --project=$PROJECT_ID \
  --location="global" \
  --display-name="GitHub Actions Pool"

# 2. Create the OIDC provider
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project=$PROJECT_ID \
  --location="global" \
  --workload-identity-pool="github-actions" \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# 3. Create a service account for GitHub Actions
gcloud iam service-accounts create "github-actions" \
  --project=$PROJECT_ID \
  --display-name="GitHub Actions"

# 4. Grant necessary roles to the service account
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.developer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# 5. Allow GitHub Actions to impersonate the service account
gcloud iam service-accounts add-iam-policy-binding \
  "github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}"
```

### 2c. Add GitHub Actions Secrets

1. Go to your forked repo on GitHub
2. Settings → Secrets and Variables → Actions → New repository secret

Add two secrets:

| Secret Name | Value |
|-------------|-------|
| `WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions/providers/github-provider` (replace `PROJECT_NUMBER`) |
| `WIF_SERVICE_ACCOUNT` | `github-actions@PROJECT_ID.iam.gserviceaccount.com` (replace `PROJECT_ID`) |

Example values (replace with your actual values):
```
WIF_PROVIDER = projects/123456789/locations/global/workloadIdentityPools/github-actions/providers/github-provider
WIF_SERVICE_ACCOUNT = github-actions@agentic-hybrid-search-dev.iam.gserviceaccount.com
```

---

## Step 3 — Update the Workflow with Your Project ID

The GitHub Actions workflow hardcodes the original project ID. Update it for your project:

1. **Edit `.github/workflows/build-deploy.yml`** (in your forked repo)
   - Find: `gen-lang-client-0250737934`
   - Replace with: `YOUR_PROJECT_ID`
   - Find: `us-central1-docker.pkg.dev/gen-lang-client-0250737934/agentic-hybrid-search/agentic-hybrid-search`
   - Replace with: `us-central1-docker.pkg.dev/YOUR_PROJECT_ID/agentic-hybrid-search/agentic-hybrid-search`

2. **Commit and push**:
   ```bash
   git add .github/workflows/build-deploy.yml
   git commit -m "chore: update GCP project ID in CI/CD workflow"
   git push origin main
   ```

Alternatively, avoid editing the workflow by always passing `--project YOUR_PROJECT_ID` to `deploy.sh` (see Step 4).

---

## Step 4 — Run deploy.sh (First Deployment)

The deployment script provisions all GCP infrastructure and performs the initial Docker build and deploy:

```bash
cd langchain_agent

# Run deploy.sh with your project ID
./scripts/deploy.sh --project agentic-hybrid-search-dev
```

**What it does:**
- Enables 6 GCP APIs (Cloud Run, Cloud Build, Artifact Registry, Cloud SQL, Secret Manager, etc.)
- Creates a Cloud SQL Postgres 16 instance (`db-f1-micro`, ~$7–10/month)
- Auto-generates database password and stores it in Secret Manager
- Prompts for your Google AI API key and stores secrets in Secret Manager
- Builds Docker image locally and pushes to Artifact Registry
- Deploys to Cloud Run with auto-scaling (0–2 instances, ~$10–30/month under load)
- Re-deploys once more to bake the Cloud Run URL into the image

**On the first run, you'll be prompted:**
```
Enter GOOGLE_API_KEY (from aistudio.google.com/apikey):
```
Paste your API key (from Prerequisites step 5).

**Script output shows:**
- Service URL (e.g., `https://agentic-hybrid-search-XXXXX.run.app`)
- Swagger URL (e.g., `https://agentic-hybrid-search-XXXXX.run.app/docs`)
- Health endpoint (e.g., `https://agentic-hybrid-search-XXXXX.run.app/api/health`)

**Typical duration:** 12–15 minutes (first time; cached Docker builds are much faster).

---

## Step 5 — Initialize the Database and Search Index

After `deploy.sh`, initialize the Cloud SQL database and ingest the ESCI product data:

```bash
./scripts/gcp-init.sh --project agentic-hybrid-search-dev
```

**What it does:**
- Auto-downloads Cloud SQL Auth Proxy (if not present)
- Connects to Cloud SQL via the proxy and creates LangGraph checkpoint tables
- Runs Lucille ETL to ingest 9,618 ESCI product embeddings and relevance judgments into hosted OpenSearch
- Verifies row counts and document counts

**Script output shows:**
```
✓ Cloud SQL tables created
✓ 9,618 products ingested
✓ 97,345 judgments ingested
✓ OpenSearch index ready
```

**Typical duration:** 3–5 minutes.

---

## Step 6 — Verify the Deployment

Confirm that the application is healthy:

```bash
PROJECT_ID="agentic-hybrid-search-dev"

# Get the service URL
SERVICE_URL=$(gcloud run services describe agentic-hybrid-search \
  --region=us-central1 --project=$PROJECT_ID \
  --format='value(status.url)')

echo "Service URL: $SERVICE_URL"

# Check health
curl "$SERVICE_URL/api/health"
```

**Expected response:**
```json
{
  "status": "ok",
  "version": "1.1.0",
  "postgres": true,
  "google_ai": true,
  "vector_store": true,
  "document_count": 9618
}
```

**Try a search:**
```bash
curl -X POST "$SERVICE_URL/api/health" \
  -H "Content-Type: application/json" \
  -d '{"query":"wireless headphones"}'
```

---

## Step 7 — Set Up Continuous Deployment (CI/CD)

Every push to `main` in your forked repo triggers the full CI/CD pipeline automatically:

```bash
# Make a change and push to main
git add .
git commit -m "chore: test CI/CD"
git push origin main
```

**Watch the deployment:**
```bash
# Option 1: Use GitHub CLI
gh run watch

# Option 2: View in browser
# Go to Actions tab in your repo: https://github.com/YOUR_ORG/opensearch2026-agentic-search/actions
```

**What the pipeline does:**
1. Unit tests (Python, ~30s)
2. Integration tests (PostgreSQL + OpenSearch, ~60s)
3. Linting (black, isort, flake8, mypy, ~15s)
4. Frontend tests (Node.js, ~20s)
5. Docker build and push (cached, ~3–5 min)
6. Deploy to Cloud Run (~3 min)
7. Smoke tests (auth, search, WebSocket, ~60s)

**Total time:** ~12–15 minutes.

**Rollback is instant** if tests fail — new revisions get 0% traffic until all tests pass, then automatically promote to 100% traffic.

---

## Troubleshooting

### WIF 403 Error on GitHub Actions Push

**Symptom:** GitHub Actions workflow fails with "403 Forbidden" when trying to authenticate to GCP.

**Cause:** The OIDC binding in Step 2b didn't match your GitHub org/repo path.

**Fix:**
```bash
PROJECT_ID="agentic-hybrid-search-dev"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
GITHUB_ORG="your-github-org"
GITHUB_REPO="agentic-hybrid-search"

# Re-run the workloadIdentityUser binding with the correct repo path
gcloud iam service-accounts add-iam-policy-binding \
  "github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}"
```

### deploy.sh Fails at "Enable APIs"

**Symptom:** `deploy.sh` fails with "Billing account not found" or "Project not linked to billing".

**Cause:** Billing was not linked to your GCP project.

**Fix:**
```bash
PROJECT_ID="agentic-hybrid-search-dev"
BILLING_ID=$(gcloud billing accounts list --format='value(name)' | head -1)

gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ID
```

### gcp-init.sh Fails at Cloud SQL Proxy

**Symptom:** `gcp-init.sh` hangs or fails to connect to Cloud SQL.

**Cause:** `deploy.sh` didn't complete successfully, so the Cloud SQL instance doesn't exist.

**Fix:** Ensure `deploy.sh` completed without errors. Check:
```bash
gcloud sql instances list --project=$PROJECT_ID
# Should show: agentic-hybrid-search-db
```

If the instance doesn't exist, re-run `deploy.sh`.

### OpenSearch Has 0 Documents After gcp-init.sh

**Symptom:** `gcp-init.sh` completes but OpenSearch index is empty.

**Cause:** Lucille ETL (`lucille_ingest.sh`) failed silently or was skipped.

**Fix:** Re-ingest manually:
```bash
export OPENSEARCH_HOST="34.138.97.13"  # GCP hosted instance (see CLAUDE.md)
export OPENSEARCH_PORT="9200"
export OPENSEARCH_USE_SSL="true"
export OPENSEARCH_VERIFY_CERTS="false"

cd langchain_agent
bash scripts/lucille_ingest.sh --reset-index
```

### Cloud Run Returns 500 After Deployment

**Symptom:** Health check or search request returns HTTP 500.

**Cause:** Missing or incorrect environment variables in Cloud Run.

**Fix:** Check that all 5 secrets exist in Secret Manager and are properly injected:
```bash
PROJECT_ID="agentic-hybrid-search-dev"

# Verify all secrets exist
gcloud secrets list --project=$PROJECT_ID | grep agentic

# Check Cloud Run env vars
gcloud run services describe agentic-hybrid-search \
  --region=us-central1 --project=$PROJECT_ID \
  --format='value(spec.template.spec.containers[0].env)' | grep GOOGLE_API_KEY
```

If secrets are missing, re-run `deploy.sh` and pay careful attention to the prompts.

### How to Check Cloud Run Logs

```bash
PROJECT_ID="agentic-hybrid-search-dev"

# Stream recent logs
gcloud run services logs read agentic-hybrid-search \
  --region=us-central1 --project=$PROJECT_ID \
  --limit=100 --follow

# Or view in the Console
# https://console.cloud.google.com/run/detail/us-central1/agentic-hybrid-search/logs
```

---

## Cost Estimates

Expected monthly costs for a demo/dev deployment:

| Service | Cost |
|---------|------|
| Cloud SQL (db-f1-micro, Postgres 16) | $7–10 |
| Cloud Run (0–2 instances, idle free) | $0–30 |
| Artifact Registry (container images) | ~$0.10/GB/month |
| Secret Manager (5 secrets) | ~$1 |
| **Total** | **~$20–40/month** |

Cloud Run and Cloud SQL both have free-tier limits (5 billion requests/month, 365 days/month of db-f1-micro). A lightly-used demo typically stays within free tier.

---

## Next Steps

1. **Set up monitoring** — See [Monitoring](monitoring.md) to configure log-based alerts
2. **Enable rate limiting** — Check CLAUDE.md for `slowapi` configuration
3. **Configure custom domain** — Use Cloud Run's custom domain feature for a vanity URL
4. **Automate backups** — Cloud SQL automated backups are on by default (7-day retention)
5. **Scale for production** — See [Scaling](scaling.md) for instance sizing and cost optimization

---

**Questions?** Check [Troubleshooting](troubleshooting.md) or file an issue on GitHub.
