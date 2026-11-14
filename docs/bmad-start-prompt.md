# Starting prompt for your BMAD-enabled environment

BMAD is not bundled or installed here. Open this repository in the coding environment where you already use BMAD and give it the prompt below using the brownfield workflow available in your installed version. This is task context, not a claim about a particular BMAD slash command.

```text
I want to use BMAD for a brownfield migration of this legacy application to Azure.

First inspect the repository. Read README.md, app.py, schema.sql, config.ini,
tests/test_app.py, docs/current-state.md, and docs/migration-brief.md.

Run the existing tests and explain the current architecture, actual behavior,
stateful dependencies, technical constraints, and missing information.

The legacy baseline is a server-rendered Python monolith with SQLite, local
document storage, INI configuration, and manual CSV reports. It is already
implemented. Do not replace it with a new greenfield application or invent
features that do not exist.

Use BMAD to produce proportional requirements, target architecture,
migration stories, and validation criteria. Explain the choices and trade-offs
for application hosting, managed relational storage, object storage, identity,
configuration, observability, reports, data migration, cutover, and rollback.

Keep the baseline intact and implement migration work on a separate branch.
Preserve customer/order IDs and relationships, exact integer money values,
business status transitions, timestamps, document metadata, and file hashes.

Treat docs/migration-brief.md as input for discussion and verification. Clearly
separate proposed architecture, completed implementation, and verified behavior.
Use small stories and concise artifacts appropriate to this POC. Track model
usage and cost where available; avoid repetitive planning and speculative scope.

Start with discovery and a short list of architecture decisions and questions.
Do not provision Azure resources until subscription, region, resource scope,
and cost boundaries have been supplied.
```
