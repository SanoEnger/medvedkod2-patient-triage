#!/bin/sh
set -eu
cp /run/postgres-secrets/postgres.crt /tmp/postgres.crt
cp /run/postgres-secrets/postgres.key /tmp/postgres.key
chown postgres:postgres /tmp/postgres.crt /tmp/postgres.key
chmod 600 /tmp/postgres.key
exec docker-entrypoint.sh "$@"
