#!/usr/bin/env bash
set -euo pipefail

# The database schema is provisioned separately (see ../database, applied via
# Alembic or as docker-entrypoint-initdb.d scripts in docker-compose). Ordering
# against the DB is handled by the compose healthcheck (depends_on: service_healthy),
# so we simply launch the app here.
exec "$@"
