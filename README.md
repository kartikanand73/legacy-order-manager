# LedgerWorks — Legacy Order Manager

A small, runnable **legacy-style application** for a BMAD brownfield-to-cloud migration exercise. All customers and orders are synthetic.

## What it does

- Lists customers and lets an operator add customers.
- Creates orders with customer, product, quantity, and USD unit price.
- Tracks orders through `New → Processing → Shipped`, or cancellation before shipment.
- Attaches and downloads PDF, TXT, and CSV order documents.
- Filters the order register by status.
- Exports the order register to CSV through the UI or a batch command.
- Produces a JSON migration baseline with row counts, financial totals, and document checksums.

## Why this represents a legacy system

The legacy characteristics are architectural: a single server-rendered Python monolith mixes HTML, SQL, validation, business rules, and filesystem access. It relies on an embedded SQLite database, server-local document storage, an INI file, a single-process web server, and manually scheduled CSV reports. It has no cloud services, REST API, infrastructure automation, distributed storage, identity provider, or deployment pipeline.

Python and SQLite themselves are not obsolete. This deliberately uses a maintained Python interpreter rather than introducing unsupported software or known vulnerable dependencies. It is a small simulation of an office application, not a recovered enterprise codebase.

## Run locally

**Prerequisite:** Python 3.11 or later. No external Python packages, database service, cloud account, or Docker installation are required. Tested here on Python 3.12.14.

From this project directory:

```bash
python app.py --init
python app.py
```

Open **http://127.0.0.1:8080**. On Windows, use `py` in place of `python` if needed; on macOS/Linux, use `python3` if `python` is unavailable. Keep the terminal open. Stop the server with Ctrl+C.

`--init` creates three sample customers and three sample orders only when the customer table is empty. Re-running it preserves existing data. Initial totals are **3 customers, 3 orders, and $4,360.00** across all statuses. All prices are stored as integer cents.

### Try the workflow

1. Open Customers and add a synthetic customer.
2. Open Orders and create an order for that customer.
3. Open the new order and move it to Processing.
4. Attach `sample-data/sample-invoice.txt` and download it again.
5. Move the order to Shipped; it can no longer be changed.
6. Export the CSV register and record a migration baseline.

### Batch operations

```bash
python app.py --export
python app.py --baseline
python -m unittest discover -s tests -v
```

The export command writes `var/reports/orders.csv`. On an existing office server, an operator would schedule that command with cron or Windows Task Scheduler; scheduling is not installed by this project.

To capture the baseline before migration:

```bash
python app.py --baseline > baseline-before.json
```

Do not commit real customer data, runtime databases, documents, credentials, or exports. The generated `var/` directory is ignored by Git.

## Project layout

| Path | Purpose |
| --- | --- |
| `app.py` | Application, web pages, SQL access, local storage, batch commands |
| `schema.sql` | SQLite schema and constraints |
| `config.ini` | Local server and file paths; no credentials |
| `style.css` | Server-served stylesheet; no frontend build |
| `sample-data/` | Synthetic customer records and a sample document |
| `tests/test_app.py` | Business behavior, validation, file integrity, and HTTP tests |
| `docs/current-state.md` | Existing architecture and known constraints |
| `docs/migration-brief.md` | Migration scope and acceptance criteria |
| `docs/bmad-start-prompt.md` | Starting prompt for your separate BMAD-enabled environment |
| `scripts/start.bat`, `scripts/start.sh` | Local startup helpers |

## Training boundary

Run on your own computer using the loopback address. There is no authentication, authorization, malware scanner, TLS termination, audit trail, or production web server. The launcher restricts the host to loopback. Do not expose this application to the internet or use it for sensitive data.

The app includes input validation, parameterized SQL, escaped HTML, form tokens, size limits, and generated attachment storage names. These make the exercise reasonably behaved; they do not make it production ready. A database and a filesystem write are not a single durable transaction, so a process crash can leave inconsistent document state. That is one migration issue to assess.

## BMAD exercise

The **legacy baseline is implemented**. BMAD has **not** been installed or run in this repository, and no cloud migration has been performed. Use the migration brief and starting prompt in your BMAD-enabled Claude Code/Codex environment. Have it inspect this codebase, identify constraints, propose architecture choices, then implement a migration in small, verifiable stories.

Keep the baseline on `main` (or tag `legacy-baseline`) and do migration work on a separate branch such as `migration/azure`. The target architecture is intentionally left open for the BMAD exercise.

## Upload to GitHub

Create an **empty** repository named `legacy-order-manager` in your GitHub account (private is a sensible default for an exercise). Do not initialize it with a README or license because this project already has files. Then run from the project directory:

```bash
git init -b main
git add .
git commit -m "Add working legacy order management baseline"
git tag legacy-baseline
git remote add origin https://github.com/YOUR_USERNAME/legacy-order-manager.git
git push -u origin main
git push origin legacy-baseline
```

Replace `YOUR_USERNAME` with your GitHub username. If a Git repository is already initialized and committed, skip the first four lines. Authenticate Git with your normal GitHub login mechanism; do not put tokens in source files or remote URLs.
