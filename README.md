# Kørselsgodtgørelse for Skolekørsler — Udbetaling

This robot is part of the 'MBU Koerselsgodtgoerelse Skolekoersler' process and runs on
[Automation Server](https://github.com/odense-rpa/automation-server-client).

It picks up the reviewed *egenbefordring* Excel file from SharePoint, turns every approved row into a work item,
and creates an outlay ticket (*udlægsbilag*) for it in OPUS with the citizen's receipt attached. When every item
for a file is done, it writes the file back to SharePoint with the outcome of each row and notifies personnel.

The Excel file is produced by the upstream robot,
[rpa-upload-egenbefordring-til-sharepoint](https://github.com/AAK-MBU/MBU_Egenbefordring_Excel_Upload_Til_Sharepoint_ATS),
which validates the submissions against each child's bevilling and marks the payable rows.

## Running

```bash
uv sync
uv run python main.py --queue
uv run python main.py --process
```

| Flag | Stage | What it does |
| --- | --- | --- |
| `--queue` | Populate | Reads the Excel file from SharePoint and queues one work item per approved row |
| `--process` | Process | Creates the OPUS ticket for each item, then finalizes the file once all items are done |

There is no `--finalize` flag. Finalization is checked after every processed item and runs on its own as soon as
no item for the file is left in the `new` state.

**This robot only runs on Windows.** It drives OPUS through a real Chrome window using Selenium and `pynput`,
so it needs a desktop session — it cannot run headless in practice, and `uv sync` will not build on Linux.

### Arguments

No process arguments. Configuration comes from environment variables:

| Variable | Purpose |
| --- | --- |
| `ATS_URL`, `ATS_TOKEN` | Automation Server API |
| `DBCONNECTIONSTRINGPROD` | SQL Server connection string, used to track each submission's status |
| `TENANT`, `CLIENT_ID`, `APPREG_THUMBPRINT`, `GRAPH_CERT_PEM` | SharePoint certificate authentication |

Everything else is read from the RPA database at runtime: the `egenbefordring_udbetaling` credential (OPUS
login), the `os2_api` credential (downloading receipts from OS2forms), and the `egenbefordring_procargs`
constant, which supplies `naeste_agent` — the OPUS agent the tickets are routed to.

Local paths and SharePoint locations are in `helpers/config.py`. Receipts are downloaded to
`C:\tmp\Koerselsgodtgoerelse`, which is cleared at the start of every `--queue` run.

## What the robot does

1. **Queue** — Looks in `MBU - RPA - Egenbefordring/Delte dokumenter/General/Til udbetaling`, which is where
   personnel move a file once they have reviewed it. The folder must contain exactly one file; the robot fails
   if there are more. Rows whose `godkendt` column contains an `x` are kept, mapped into work items, and queued
   with the reference `<file name without extension>_<uuid>`, so re-running `--queue` cannot queue the same row
   twice.

   Each work item carries the values OPUS needs — encrypted recipient CPR, amount, posteringstekst, PSP element,
   `naeste_agent`, the receipt URL — plus `raw_excel_data`, an untouched copy of the whole spreadsheet row that
   the finalize stage writes back.

2. **Process** — One Chrome and OPUS session is opened for the entire run rather than per item. For each item the
   robot marks the submission `InProgress` in the RPA database, downloads the citizen's receipt from OS2forms,
   fills in and controls the outlay ticket in OPUS, attaches the receipt, and marks the submission `Successful`.

   A transient browser or GUI failure is retried up to `MAX_ITEM_ATTEMPTS` times from a clean "navigate to OPUS"
   state. A `BusinessError` is never retried — a duplicate ticket or a missing kreditor needs a human, so the
   item goes to *pending user action* straight away.

3. **Finalize** — Once no work item for the file is still `new`, the rows are reassembled from `raw_excel_data`
   with `behandlet_ok` or `behandlet_fejl` filled in, written back to Excel, and uploaded to
   `General/Behandlet` — or to `General/Fejlet`, together with the receipts of the failed rows, if anything
   failed. The original file is deleted from `Til udbetaling` and an email is sent to personnel.

## The Excel schema is a contract

The robot reads the sheet by column name, so a rename in the upstream robot's `desired_order` breaks it. Two
places have to agree with that list:

- `CPR_COLUMNS` in `helpers/helper_functions.py` — these columns **must** be read as text. `pd.read_excel`
  silently ignores `dtype` entries for columns it cannot find, so a stale name here does not raise; it reads
  CPR numbers as integers and drops their leading zeros. `load_excel_data` therefore checks the columns are
  present and refuses to continue if they are not.
- `COLUMNS` in `processes/finalize_process.py` — the column order of the file written back to SharePoint.
  `ensure_columns` reindexes onto this list, so a stale name silently produces an empty column.

The recipient of the payment is the citizen who submitted the form (`cpr_beloebsmodtager_mitid`) unless another
recipient was named on the form (`cpr_anden_beloebsmodtager_manuelt`), in which case the named one is paid.

## Development

```bash
uv sync                # install dependencies (Python 3.13, Windows)
uv run ruff check .    # lint — this is what CI enforces
```

Pull requests to `main` must bump `version` in `pyproject.toml`; a GitHub Action fails the PR otherwise.
