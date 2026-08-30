# FABINZI Customer App

Native Customer product for Android and iOS. The application consumes only the frozen `/api/v1/customer/` contract in this repository.

## Toolchain

- Flutter 3.47.0 (stable, August 2026)
- Dart 3.13.x

Platform project files are generated with `tool/bootstrap_platforms.sh` using the pinned Flutter SDK before local builds and CI builds. This keeps the monorepo source focused on the Customer app while producing standard Flutter Android/iOS hosts.

This checkpoint is in progress. `main`, production deployment, Designer/Manufacturer/`/Maneg/` mobile surfaces, and `docs/DEFERRED_LIVE_E2E.md` are out of scope.
