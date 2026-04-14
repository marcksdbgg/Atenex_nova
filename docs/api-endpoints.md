# API Endpoints

This document catalogs the current public HTTP surface exposed by the backend.

## Notes

- The FastAPI app is created in [backend/atenex_nova/main.py](../backend/atenex_nova/main.py).
- Routers live under [backend/atenex_nova/presentation/api/routers](../backend/atenex_nova/presentation/api/routers).
- The endpoint set below is derived from the current code, not from the roadmap.

## Health

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Return basic service status |

## Collections

| Method | Route | Purpose |
|---|---|---|
| POST | `/collections` | Create a collection |
| GET | `/collections` | List collections |
| GET | `/collections/{collection_id}` | Fetch one collection |
| PATCH | `/collections/{collection_id}` | Update collection metadata and profiles |
| DELETE | `/collections/{collection_id}` | Delete a collection and cleanup derived artifacts |
| GET | `/collections/{collection_id}/documents` | List collection documents with pagination and optional status filter |
| POST | `/collections/{collection_id}/documents` | Upload a file into the collection |
| POST | `/collections/{collection_id}/documents/import` | Register a local file path as a document |
| POST | `/collections/{collection_id}/documents/import-folder` | Import a local folder into the collection |
| POST | `/collections/{collection_id}/rebuild` | Requeue the collection rebuild pipeline |

## Documents

| Method | Route | Purpose |
|---|---|---|
| GET | `/documents/{document_id}` | Fetch one document |
| GET | `/documents/{document_id}/nodes` | List structural nodes for the document |

## Queries

| Method | Route | Purpose |
|---|---|---|
| GET | `/queries/history?collection_id=...&limit=...` | Show recent queries and answer metadata for a collection |
| POST | `/queries/search` | Run retrieval only and return ranked hits |
| POST | `/queries/answer` | Run retrieval plus answer synthesis |

### Search Response

The search endpoint returns:

- query metadata
- route mode
- intent and language
- total hits
- ranked evidence items

### Answer Response

The answer endpoint returns:

- answer text
- verdict
- grounding score
- citations
- supporting evidence items

## Answers

| Method | Route | Purpose |
|---|---|---|
| GET | `/answers/{answer_id}` | Fetch a stored answer with citations and evidence |
| GET | `/answers/{answer_id}/export/markdown` | Export an answer as Markdown |
| GET | `/answers/{answer_id}/export/pdf` | Export an answer as PDF |

## Jobs

| Method | Route | Purpose |
|---|---|---|
| GET | `/jobs` | List jobs with pagination |
| GET | `/jobs/{job_id}` | Fetch one job |

## Observability

| Method | Route | Purpose |
|---|---|---|
| GET | `/observability/audit` | List recent audit entries, or filter by entity or run id |
| GET | `/observability/documents/{document_id}/evidence` | Fetch a document-centered evidence bundle |

## Evaluation

| Method | Route | Purpose |
|---|---|---|
| GET | `/evaluation/datasets` | List available datasets |
| POST | `/evaluation/runs` | Run an evaluation against a collection and dataset |
| GET | `/evaluation/runs` | List evaluation runs |
| GET | `/evaluation/runs/{run_id}` | Fetch an evaluation run |
| GET | `/evaluation/reports/{run_id}` | Fetch the report for a run |

## Request Patterns

### Collection document listing

The backend supports `offset`, `limit`, and `status` parameters on the collection document listing endpoint. The frontend uses these parameters to fetch a full inventory when needed.

### File uploads

Uploads use `multipart/form-data` with the file payload and optional `collection_path` and `display_title` fields.

### Query modes

The request body accepts routing modes such as `auto`, `exact`, `factual_local`, `multi_hop`, `global`, `argumentative`, and `visual`.

## Related Docs

- [docs/architecture-backend.md](architecture-backend.md)
- [docs/jobs-and-workers.md](jobs-and-workers.md)
