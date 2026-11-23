# Running the inbox on a schedule

An example of the delivered flow on one Linux machine: documents arrive in a folder, a [systemd timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html) runs `scripts.run_inbox` every 15 minutes, and each run leaves `results.csv`, its machine copy `results.jsonl` and the processed documents in a folder of its own. What a run does is described in [`doc_intake.batch`](../src/doc_intake/batch.py); the design is [D19](../docs/ARCHITECTURE.md#d19-execução-agendada-sobre-uma-pasta-de-entrada-decidida-na-53).

This is the public example. Deploying in a client's own account (their cloud, their secrets store, their connectors) is delivery work, outside this repository ([D18](../docs/ARCHITECTURE.md#d18-fronteira-entre-núcleo-kit-de-entrega-e-código-do-cliente-decidida-na-52)).

## Layout

| Path | What |
| --- | --- |
| `doc-intake` | The system user the service runs as. Its home, `/var/lib/doc-intake`, holds uv's cache and the Python uv installs |
| `/opt/doc-intake-pipeline` | A checkout of a release tag, owned by `doc-intake`, with its `.env` (API key and settings) readable by that user only |
| `/usr/local/bin/uv` | uv, at the version `required-version` in `pyproject.toml` asks for |
| `/srv/doc-intake/inbox` | Where documents arrive: saved there, or a folder a Drive or Dropbox client keeps in sync |
| `/srv/doc-intake/runs` | One folder per run: `results.csv`, `results.jsonl` and `documents/` |

Everything is installed as `doc-intake`, the user the service runs as: uv keeps its cache and the Python it downloads in the home of whoever runs it, so a `sudo uv sync` as root would leave the service without a Python it can read.

## Install

```bash
# uv, at the version pyproject.toml requires, checked against its published SHA-256
curl -LsSf -o /tmp/uv.tar.gz https://github.com/astral-sh/uv/releases/download/0.13.9/uv-x86_64-unknown-linux-gnu.tar.gz
echo "a7fbaff2b9a271d85c1bdb540941090fd1ce011797b4abeb48e4dcd39c2471d5  /tmp/uv.tar.gz" | sha256sum --check --strict
sudo tar -xzf /tmp/uv.tar.gz -C /usr/local/bin --strip-components=1 uv-x86_64-unknown-linux-gnu/uv
rm /tmp/uv.tar.gz
sudo git clone --branch v0.2.0 --depth 1 https://github.com/brunoccalmeida/doc-intake-pipeline /opt/doc-intake-pipeline
cd /opt/doc-intake-pipeline
sudo cp .env.example .env
sudoedit .env    # the API key and any DOC_INTAKE_* setting
sudo useradd --system --create-home --home-dir /var/lib/doc-intake --shell /usr/sbin/nologin doc-intake
sudo mkdir -p /srv/doc-intake/inbox /srv/doc-intake/runs
sudo chown -R doc-intake: /srv/doc-intake /opt/doc-intake-pipeline
sudo chmod 600 .env
sudo -u doc-intake -H uv sync --locked --no-dev
sudo -u doc-intake -H uv run --locked --no-dev python -m scripts.fetch_tessdata  # OCR model, into .cache/tessdata
sudo cp deploy/doc-intake-inbox.service deploy/doc-intake-inbox.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now doc-intake-inbox.timer
```

The uv file is for x86-64 Linux. On another machine, take its file and checksum from the same [release](https://github.com/astral-sh/uv/releases/tag/0.13.9); the release also documents checking the download with `gh attestation verify <file> --repo astral-sh/uv`.

Check it:

```bash
systemctl list-timers doc-intake-inbox.timer      # next and last run
sudo systemctl start doc-intake-inbox.service     # one run now
journalctl -u doc-intake-inbox.service            # summary line and run log
```

## Reviewing a run

Each run folder holds `results.csv`, the spreadsheet a person reviews, and `results.jsonl`, the results exactly as the run produced them. Leave `results.jsonl` as it is: a confirmed value is read from it, because a spreadsheet may rewrite a value it shows (a date in the local format).

In `results.csv`, record a decision only for the rows you checked on the page; an empty `verdict` means not reviewed, never "looks right":

| `verdict` | When | `correct_value` |
| --- | --- | --- |
| `confirmed` | The value is right as written, or the field is empty and the document does not have it | empty |
| `corrected` | The value is wrong, or empty while the document has it | the right value: a total as `19.90` (a dot, no currency), a date as `2026-03-04`, a currency as its ISO code (`MYR`) |
| `not_on_page` | The value is filled, but the document does not have that field | empty |

Check each value against the page itself, with `page` and `quote` saying where to look: the suggestion is what is being checked, not a starting point. Write a right value only in `correct_value`: the `value` column is not read back, so a value fixed there and marked `confirmed` would record the run's wrong value as right.

To keep the file readable afterwards:

- **Excel:** open it with **Data > From Text/CSV**, set every column to **Text**, and save as **CSV UTF-8 (Comma delimited)**. Opened with a double click, Excel converts cells as it reads them (it drops leading zeros, for one), and the CSV it saves keeps what it converted; importing the columns as Text is Microsoft's way around it ([Microsoft: keep leading zeros and large numbers](https://support.microsoft.com/en-us/office/keep-leading-zeros-and-large-numbers-1bf7b935-36e1-4985-842f-5dfa51f85fe7)). A sheet saved with `;` between cells, as Excel does in regions with a decimal comma, is read too.
- **Google Sheets:** import it, then download it again as CSV and put the download in the run folder as `results.csv`, replacing the original: the download has another name, and the original has no verdicts.

`doc_intake.review.read_reviewed_run` reads a reviewed folder back as labeled fields. It stops at the first row it cannot use (an unknown verdict, a corrected value it cannot read, a row the run did not write) and names that row; fix it in the sheet and read again.

## Why these settings

- **No two runs at once.** With `Type=oneshot`, the service stays active until the run ends, and a timer does not start a service that is still active: "it is not restarted, but simply left running" ([systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)). No lock file is needed.
- **A run missed while the machine was off** starts at the next boot (`Persistent=true`, same page).
- **A failed run is visible.** The command exits 1 when a document failed, so `systemctl status` and `systemctl --failed` show it. A field to review is not a failure.
- **Files still arriving are left alone.** A file is taken once it has not changed for 60 seconds (`--settle`). Neither [Dropbox](https://help.dropbox.com/delete-restore/cache-folder) nor [Google Drive for desktop](https://support.google.com/drive/answer/16631477) documents how it writes a synced file, so the run does not assume a file appears whole.
- **Keep `inbox` and `runs` on one filesystem.** Within one filesystem a move is a rename; across filesystems it copies the file and then deletes it ([`shutil.move`](https://docs.python.org/3.14/library/shutil.html#shutil.move)), and a crash in between can leave a file in both places.

CI checks both unit files with `systemd-analyze verify` (unknown keys, a missing `ExecStart` binary), and the `deploy-smoke` job runs the two blocks above, as written, on an Ubuntu machine with systemd: it installs from the checkout under test instead of the release tag and writes a dummy API key instead of opening an editor. It then starts the service over an empty inbox (exit 0) and over a document (the provider refuses the dummy key at no cost: exit 1, the document stays in the inbox).

## Other schedulers

- **cron:** a crontab line does not prevent overlap by itself. Wrap the command in [`flock -n`](https://man7.org/linux/man-pages/man1/flock.1.html), which gives up when the previous run still holds the lock:

  ```cron
  */15 * * * * cd /opt/doc-intake-pipeline && flock -n /tmp/doc-intake-inbox.lock /usr/local/bin/uv run --locked --no-dev python -m scripts.run_inbox /srv/doc-intake/inbox /srv/doc-intake/runs
  ```

- **Windows Task Scheduler:** keep the default "Do not start a new instance" ([`MultipleInstancesPolicy` `IgnoreNew`](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-multipleinstancespolicy-settingstype-element)), set "Start in" to the checkout, and run `uv run --locked --no-dev python -m scripts.run_inbox <inbox> <runs>`.
