#!/usr/bin/env bash
# Copy úřední deska cards (drafts + approved) from this checkout into the running app pod and
# load them into the database. Drafts never go to git; approved cards are committed and also
# reach the cluster through the image (bootstrap seeds them), this just makes them visible now.
set -euo pipefail
cd "$(dirname "$0")/.."
NS=otevrena-petka
POD=$(kubectl -n "$NS" get pods -o name --field-selector=status.phase=Running | grep '^pod/app-' | head -1)
[ -n "$POD" ] || { echo "no running app pod" >&2; exit 1; }
mkdir -p data/uredni_deska/drafts data/uredni_deska/digests
tar -C data/uredni_deska -cf - drafts digests \
  | kubectl -n "$NS" exec -i "$POD" -c app -- sh -c \
      'mkdir -p /data/uredni_deska && rm -rf /data/uredni_deska/drafts && tar -C /data/uredni_deska -xf -'
kubectl -n "$NS" exec "$POD" -c app -- usneseni deska-load
