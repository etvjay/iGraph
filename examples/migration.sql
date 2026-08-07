-- Example artifact generated for the iGraph golden demo.
-- Proposed change: orders.customer_id -> account_id
-- This file is intentionally non-destructive and reviewable.

ALTER TABLE orders RENAME COLUMN customer_id TO account_id;
