# Parity

The parity script compares prose, flow, plain-mode and personal-style findings
against the pinned source archive. Run it with an archive that contains `hooks/`
and `docs/`:

```sh
python3 scripts/parity_check.py --source /path/to/archive
```

The pinned-source run compared 76 Markdown files and returned PARITY OK 76 files.
