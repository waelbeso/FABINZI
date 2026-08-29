# Stage 7 Acceptance — Manufacturing & Fulfillment

Status: **COMPLETE**

Stage 7 converts confirmed customer orders into controlled manufacturing and fulfillment operations without changing checkout/payment ownership.

## Acceptance gates
- Confirmed made-to-order purchases automatically create one Production Job and one Fulfillment Record.
- Stock purchases bypass manufacturing and enter Ready to Pack after Stage 6 stock reservation.
- Production Jobs use an accepted Stage 4 Manufacturer Selection matching the order's Designed Product.
- Manufacturer tenant isolation and production/QC roles are enforced.
- Five controlled milestones: Materials, Cutting, Assembly/Sewing, Printing/Embroidery, Finishing.
- QC cannot start before all milestones are completed.
- QC history is append-only; pass releases the order to fulfillment, failure/rework returns the job to a controlled non-ready state.
- Private Production Assets support work instructions and QC evidence.
- Fulfillment lifecycle supports Ready to Pack → Packed → Shipped → Delivered with immutable event history.
- Shipping requires carrier and tracking number; customers receive in-app shipped/delivered notifications.
- Customer, Designer and assigned Manufacturer visibility is isolated to their own operations.
- Web surfaces, DRF API, `/Maneg/` administration, audit events and automated tests are included.

## Boundaries
- Stage 7 does not re-run payment logic or introduce payouts, commissions, settlements or accounting; those belong to Stage 8 Finance.
- Shipping provider API integrations are not required here; carrier/tracking data is operationally recorded and can be integrated later.
