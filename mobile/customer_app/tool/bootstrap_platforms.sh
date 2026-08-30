#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
flutter create \
  --platforms=android,ios \
  --org com.fabinzi \
  --project-name fabinzi_customer_app \
  .
