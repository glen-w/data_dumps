# Contributing

Do not attach real GDPR dumps, extracted files, or DuckDB warehouses to issues or pull requests. Use the synthetic fixtures under `tests/` (see [SECURITY.md](SECURITY.md) for private reports).

New dumps follow [docs/guides/add-a-dump.md](docs/guides/add-a-dump.md). The short version:

- Implement `Source` in `src/data_dumps/sources/<slug>.py` (`detect`, `load`, `tables`, `inventory`).
- Append one `Contribution` in `src/data_dumps/contributions.py`. Do not add dynamic plugin discovery or entry points. Someone adding their own export without a repository change uses the custom manifest or `$DATA_DUMPS_ROOT/user_contributions.py` ([docs/guides/services/custom.md](docs/guides/services/custom.md)).
- Add synthetic tests that assert IPs, emails, phones, ads, and KYC are dropped. Do not commit real dumps or a DuckDB warehouse.
- Queries and an explorer tab come after the loader, when that is the task.

Do not format `notebooks/` with Black or Ruff. Marimo cell structure is not a formatter target.

Stop the Marimo dashboard (or `docker compose stop app`) before `ingest` or `enrich-musicbrainz`. See [docs/WAREHOUSE.md](docs/WAREHOUSE.md).
