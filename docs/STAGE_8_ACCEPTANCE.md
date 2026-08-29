# Stage 8 Acceptance — Finance

Status: **COMPLETE**

Stage 8 adds platform accounting, organization balances and controlled settlement readiness without re-running checkout, payment collection, manufacturing or fulfillment.

## Acceptance gates
- Delivered orders are financially recognized exactly once.
- Finance policy snapshots platform commission basis points, settlement delay and minimum payout at recognition time.
- Designer earnings, Manufacturer payable where applicable and FABINZI platform fee are posted as immutable signed ledger entries.
- Stock orders recognize Designer earnings and platform fee without inventing a Manufacturer payable.
- Manufacturer payable uses the accepted Stage 4 quote unit price for the actual Stage 7 order quantity and requires matching currency.
- Organization Finance Accounts are separated by currency; a dedicated platform account records platform fees.
- Balances expose total, available, pending, reserved and withdrawable values derived from the ledger and open settlement requests.
- Payout Profiles store masked/non-sensitive destination hints and require staff verification before settlements.
- Owner, Manager and Accountant roles can manage finance for their own organization only.
- Settlement requests enforce minimum payout, verified payout readiness and withdrawable balance.
- Staff approval/rejection and paid-state control are separate; marking paid requires an external reference and posts one immutable settlement debit.
- Staff-only financial adjustments create append-only ledger entries with audit history.
- In-app notification is sent when a settlement is marked paid.
- Web dashboard, DRF endpoints, `/Maneg/` administration, audit events and automated tests are included.

## Boundaries
- Stage 8 does not store raw bank credentials or card data; payout profiles contain only masked/non-sensitive destination hints.
- Stage 8 does not execute external bank transfers. `Paid` records an externally executed settlement reference; banking/payout-provider integration can be added later.
- Refund/dispute automation and broader communication hardening remain later work.
