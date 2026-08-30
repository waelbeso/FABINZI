# Known limitations — Flutter Customer App checkpoint

These are contract or release-boundary limitations, not fabricated mobile capabilities.

- Customer self-signup is not exposed by the frozen Customer API.
- Automated password reset is not exposed by the frozen Customer API.
- Customer email verification/account activation is not exposed by the frozen Customer API.
- Social login is not exposed by the frozen Customer API.
- Mobile push-token registration is not exposed by the frozen Customer API. The app uses the real paginated notification feed and its supported email/SMS preferences only.
- Customer cancellation, refunds, returns initiation and payment-method management are not exposed as Customer v1 operations.
- Studio element reorder is not exposed by the frozen element PATCH operation, so the mobile editor does not fabricate reorder persistence.
- Stripe PaymentSheet requires the corresponding non-secret publishable key at build/runtime configuration via `FABINZI_STRIPE_PUBLISHABLE_KEY`; server secrets remain backend-only. Paymob uses only the server-returned redirect URL. Provider/webhook confirmation remains server-authoritative.
- Store signing identities, Play/App Store publication, production credentials and production release configuration are intentionally external to this checkpoint.
- No real-device or production-Render validation is claimed by repository CI.
- `docs/DEFERRED_LIVE_E2E.md` remains UNRESOLVED and is not executed in this checkpoint.
