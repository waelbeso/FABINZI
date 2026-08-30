# FABINZI WEB v1.0 — Accepted Limitations Register

These are truthful release limitations, not silent PASS items.

## Account lifecycle

- Automated customer password reset is not implemented.
- Customer email verification/account activation is not implemented.

## Legal/operator readiness

- Repository Terms/Privacy/Returns/Shipping/Support copy is baseline product copy and still requires jurisdiction/operator legal review before a public launch decision.
- Public support email/phone/address coordinates are not invented by source; the operator must configure/approve them.

## Infrastructure/integrations

- Production Amazon S3 account connectivity has not been independently proven by repository CI.
- Optional Paymob, Stripe, Mailgun, Twilio, Cloudflare Images and Sentry production health has not been independently proven.
- Worker/Beat runtime health is not inferred from source topology.
- Backup/restore capability is documented, but a FABINZI operational restore drill is not verified and no measured RPO/RTO is claimed.
- The exact deployed production SHA is not claimed because this checkpoint does not deploy production.

## Validation scope

- `docs/DEFERRED_LIVE_E2E.md` remains UNRESOLVED. Remote isolated-QA lifecycle, isolation, payment, async and 20-shot validation remains deferred until after Flutter.
- No formal WCAG certification or performance SLA is claimed.
- API v1 is inventoried read-only for the next checkpoint; the future Customer contract and mobile authentication strategy are not frozen here.
- No Flutter/Android/iOS/Dart artifact is part of WEB v1.0 release preparation.
