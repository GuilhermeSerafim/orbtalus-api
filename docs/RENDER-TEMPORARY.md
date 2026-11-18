# Temporary Render deployment (Free only)

Prepared from source inspection and official documentation on 2026-11-18.
This is a deployment procedure, not evidence of a completed deployment.

| Gate | Status |
| --- | --- |
| Render account eligibility, resource availability and billing state | **UNVERIFIED** |
| Linux Docker build, dependency resolution and runtime memory | **UNVERIFIED** |
| Cloud database, PostGIS, schema, grants and hydrography data | **UNVERIFIED** |
| Public frontend/API connection and CORS | **UNVERIFIED** |
| Real provider integration, access, cost and analysis quality | **UNVERIFIED** |

## Boundaries and cost

Use a separate, disposable cloud database. The existing local Docker database is
not implicitly reachable from Render. Preserve the local database and services
on UI 3000, API 8000 and LP 18085; this procedure does not reconfigure them.

Select **Free** for both resources. Free Postgres permits one database per
workspace, holds 1 GB, expires after 30 days, and is deleted after a further
14-day grace period. It has no backups or managed pooling. Preserve any needed
data outside this temporary service before expiry; never treat it as durable
production storage. Free web services sleep after 15 idle minutes, have ephemeral
filesystems and share 750 running hours per workspace per month.

For **R$0**, verify remaining workspace quotas and avoid paid compute, upgrades,
disks or paid provider calls. A payment method can permit billable bandwidth/build
overages; confirm account billing controls before deployment. Without a payment
method, Render suspends services or disables new builds when applicable quotas
are exhausted. Stop if a required resource cannot be created for free.
[Official Free limits](https://render.com/docs/free).

## Manual sequence

1. Select the reviewed API commit and prove its Linux Docker build and runtime
   before declaring deployment readiness. The repository Dockerfile uses wheel-only
   dependency installation; existing Windows evidence does not prove Linux support.
2. Create a **new Free Render Postgres**, in the region selected for the API.
   PostgreSQL 15 aligns with the local compose major version; verify the selected
   version and PostGIS availability. Record resource identity and expiry without
   recording credentials. Render supports PostGIS on PostgreSQL 13 and later.
   [Database creation](https://render.com/docs/postgresql-creating-connecting),
   [extensions](https://render.com/docs/postgresql-extensions).
3. From an authorized external administration environment, connect to that new
   database using its complete external hostname. Enable PostGIS in `public`:

   ```sql
   CREATE EXTENSION postgis WITH SCHEMA public;
   ```

   Then use the existing guarded baseline procedure below. Cloud initialization
   must finish independently of application startup. Free web services offer no
   shell/SSH or one-off jobs; pre-deploy commands require paid services.
   [Deploy commands](https://render.com/docs/deploys#pre-deploy-command).
4. Create an independent application role with only the required database/schema
   access, table operations and sequence privileges for API reads, assessment writes
   and OSM cache writes. Keep owner/DDL credentials exclusively in the admin
   environment. Verify the app role can use the schema and cannot perform DDL.
   Use the app role in the cloud runtime connection, not the database owner.
5. If a useful distance result is required, import the approved local GeoJSON once
   through the guarded importer. River data is excluded from the image and imports
   do not deduplicate. An empty initialized database can pass `/ready`.
6. Create a **Free Docker Web Service** from the reviewed API repository/commit,
   same region as the database, root Dockerfile, auto-deploy **Off**. Retain its
   Docker CMD: it binds `0.0.0.0` and honors `PORT`. Configure the runtime names
   below using the database's **internal** endpoint and independent app role.
   [Web services](https://render.com/docs/web-services),
   [manual deploy controls](https://render.com/docs/deploys).
7. After schema/grants are validated, set HTTP health check path `/ready`, deploy
   manually, and record the deployed commit and observed health results. Connect
   the public frontend to this API only after its public origin is known and
   configured exactly in `CORS_ORIGINS`. Verify browser preflight and response
   from that origin. Localhost CORS does not authorize the public frontend.

## Runtime environment names

| Name | Use |
| --- | --- |
| `PORT` | Supplied by Render; existing Docker command honors it. |
| `DATABASE_URL` | Cloud internal endpoint, independent app role; accepted PostgreSQL driver scheme. |
| `CORS_ORIGINS` | Exact public frontend HTTP(S) origin(s), comma-separated, with no path, trailing slash or wildcard. |
| `OPENAI_API_KEY` | Real AI only; leave absent for provider-free readiness. |
| `GEE_PROJECT` | Real Earth Engine only. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Optional mounted runtime credential path for Earth Engine. |
| `GEE_SERVICE_ACCOUNT_JSON` | Alternative inline runtime credential; file-path option has priority. |

No `.env` is loaded by the app. Earth Engine also supports runtime ADC. Supply
actual secrets only through the authorized runtime/admin channel; store none in
Git, images, contracts, command arguments or reports. Names above do not imply
that credentials, dataset access or cost-free provider use have been established.

## Guarded baseline and optional import

Read [ORIGINAL-SCHEMA.md](ORIGINAL-SCHEMA.md) for the authoritative contract,
manifest and recovery rules. Run from the repository root with approved dependencies.
Set admin `DATABASE_URL` in the process environment using the new database's
external hostname, an accepted `postgresql`/`postgresql+psycopg2` scheme, explicit
port 5432 and exact database name. The guard rejects URL query parameters;
set admin `PGSSLMODE` to `require` for TLS instead. Ensure `PGHOSTADDR` and
`PGSERVICE` are absent. Render external connections require TLS.
[Connection details and TLS](https://render.com/docs/postgresql-creating-connecting).

Prepare a credential-free `target.json` containing exactly `host`, `port`,
`database`, `schema` (`public`) and `purpose` (`disposable-original-baseline`),
matching that new external target. Use a new manifest output filename:

```text
python scripts/init_original_db.py --initialize --target-contract target.json --manifest-out original-manifest.json
python scripts/init_original_db.py --validate-only --target-contract target.json --manifest original-manifest.json
```

Initialization requires PostGIS already installed and an otherwise empty public
schema. Preserve the manifest even after failure and inspect state using the
documented recovery procedure. Use validation for an already initialized schema;
do not rerun initialization or clear objects automatically. The historical
Alembic revision is not this baseline: do not run upgrade/stamp here.

Optional, only for an approved dataset and confirmed target:

```text
python migrate_rivers.py --target-contract target.json --input /approved/path/rivers.geojson
```

## Health evidence and completion

| Check | What success establishes |
| --- | --- |
| `GET /ping` | Process liveness; no DB or provider access. |
| `GET /ready` | DB, PostGIS and original table/column checks; reports `providers: not_verified`. |
| `GET /debug-db` | Database river count; no external provider access. |
| `POST /geo/distance` | DB-only spatial behavior; an empty river table returns 404. |

`/ready` does not prove full baseline manifest equivalence, river data presence
or successful risk analysis. Render requires a health response within five
seconds; actual cloud latency remains unverified.
[HTTP health checks](https://render.com/docs/health-checks).

Keep `/geo/risk` and `/ai/ask-ai` outside provider-free checks: they can call
external providers and AI. Publish this temporary service as readiness/DB scope
only until real integration and costs are separately established. Completion
requires recorded cloud resource identities/expiry, deployed commit, successful
Linux runtime, validated schema/app grants and observed health/CORS results;
unperformed gates remain explicitly **UNVERIFIED**.
