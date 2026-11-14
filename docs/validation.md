# Legacy baseline validation

Validated on November 14, 2026 with Python 3.12.14.

## Verified

Command: `python -m unittest discover -s tests -v`

Result: **10 tests passed**.

- Idempotent schema/seed initialization and exact baseline counts and money totals.
- Customer and order creation, integer-cent storage, and HTML escaping.
- Invalid quantities, prices, customer references, and malformed inputs are rejected.
- Status transitions and final states are enforced.
- Multipart document upload, download, size, and SHA-256 integrity.
- Unsupported/empty uploads and unknown order references are rejected.
- Form token, request-size, missing-route, and method boundaries.
- CSV output and spreadsheet formula-prefix protection.
- Filtering and global metric semantics.
- A real local HTTP server serving pages, stylesheet, CSV, order creation/redirect, and a rejected database-file URL.

The application was also initialized and started from the CLI; its JSON baseline reported 3 customers, 3 orders, and 436000 cents of order value.

## Not verified

- Visual desktop/mobile rendering and browser-driven workflows: browser startup was blocked by the execution environment.
- Windows/macOS startup scripts: provided, not executed on those operating systems.
- Other Python interpreter versions.
- Multiuser/concurrency, security hardening, or production hosting.
- Any cloud deployment, target data migration, or BMAD workflow execution.

These tests establish the local exercise baseline, not production readiness.
