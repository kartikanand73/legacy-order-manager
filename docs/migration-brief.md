# BMAD brownfield migration brief

## Goal

Move the working LedgerWorks application from local state to an Azure-hosted application while preserving the agreed business behavior, relationships, money values, and attachment bytes. This is a learning project; no cloud resources have been provisioned.

## Inputs to inspect

Read the source, schema, configuration, tests, README, and current-state document. Run the application and tests. Add one customer, one order, and the sample attachment before capturing `python app.py --baseline`.

The current baseline is the source of truth for behavior. Its database and documents are generated locally, so they are not in Git. Do not assume the three seed orders represent a complete migration dataset.

## Architecture decisions to make

1. Choose a suitable Azure application host and production server, with trade-offs for this workload.
2. Choose managed relational storage and map SQLite schema, money values, timestamps, identities, and transactions.
3. Choose durable object storage and design metadata/file consistency and reconciliation.
4. Define operator sign-in, authorization, application identity, secrets, and permissions.
5. Decide report execution, scheduling, retention, and download behavior.
6. Define repeatable infrastructure, configuration, logging, and a controlled deployment process.
7. Define migration execution, validation, cutover, and rollback. Decide when writes stop and how to restore the source without losing post-cutover changes.

Do not select services simply because they are popular. Keep the design proportional to a small application. Do not provision cloud resources without a selected subscription, resource scope, region, and cost boundaries from the owner.

## Migration acceptance criteria

- Customer and order counts and IDs reconcile between source and target.
- Every order retains its customer relationship, product, quantity, unit price in cents, status, and timestamp.
- Exact aggregate value and per-status counts match the frozen source baseline.
- Every attachment retains its order link, filename, byte count, and SHA-256 checksum; downloaded target bytes match.
- Creating customers/orders and the allowed status transitions behave as before.
- Invalid quantities/prices, missing customers, invalid state transitions, and unsupported uploads remain rejected.
- UI lists, order details, filters, and CSV report remain functional.
- Target identity and authorization checks have explicit validation evidence.
- Restarting the cloud runtime does not lose database records or documents.
- Migration scripts handle retries without duplicate records or files and record their results.
- Cutover and rollback are rehearsed with synthetic data and documented limitations.

Unit tests in this repository validate the local baseline. They do not establish target-platform readiness. Adapt the tests and add target integration checks as part of migration.

## Suggested delivery slices

1. Brownfield discovery and requirements clarification.
2. Target architecture, risks, and cost estimate.
3. Deployment skeleton and configuration.
4. Relational data conversion and reconciliation.
5. Document migration and integrity checks.
6. Application adaptation and business-behavior validation.
7. Identity, operational checks, cutover rehearsal, and evidence review.

BMAD should refine these slices after inspection rather than treating them as completed stories. Keep baseline, proposed design, implemented changes, and verified results distinct.
