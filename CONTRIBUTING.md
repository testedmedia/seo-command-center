# Contributing to SEO Command Center

Thanks for wanting to help. The codebase is intentionally boring: stdlib Python only, one file per report, no build step, SQLite for storage. Keeping it boring is the feature.

## Ground rules

- **Zero dependencies stays zero.** PRs that add a pip requirement will be asked to reimplement with stdlib. If it truly can't be done, open an issue first.
- **One report = one script.** A new report is a single script that writes its JSON + HTML, plus one nav entry. Look at any existing report in `tracker/` for the pattern.
- **SQLite is the database.** No Postgres, no ORM, no migrations framework.

## Getting started

```bash
git clone https://github.com/testedmedia/seo-command-center
cd seo-command-center
python3 demo.py && python3 worker.py serve
```

The demo runs with bundled sample data, no DataForSEO key needed, so you can develop against it immediately.

## Good first issues

Check the [good first issue label](https://github.com/testedmedia/seo-command-center/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) for tasks scoped to a single file.

## Reporting bugs

Open an issue with: what you ran, what you expected, what happened, and your Python version. If a report renders wrong, attach the JSON it was built from.

## Questions

Use [GitHub Discussions](https://github.com/testedmedia/seo-command-center/discussions) for anything that isn't a bug or a PR.
