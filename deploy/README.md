# Running the inbox on a schedule

An example of the delivered flow on one Linux machine: documents arrive in a folder, a [systemd timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html) runs `scripts.run_inbox` every 15 minutes, and each run leaves `results.csv` and the processed documents in a folder of its own. What a run does is described in [`doc_intake.batch`](../src/doc_intake/batch.py); the design is [D19](../docs/ARCHITECTURE.md#d19-execução-agendada-sobre-uma-pasta-de-entrada-decidida-na-53).

This is the public example. Deploying in a client's own account (their cloud, their secrets store, their connectors) is delivery work, outside this repository ([D18](../docs/ARCHITECTURE.md#d18-fronteira-entre-núcleo-kit-de-entrega-e-código-do-cliente-decidida-na-52)).

## Layout

| Path | What |
| --- | --- |
| `doc-intake` | The system user the service runs as. Its home, `/var/lib/doc-intake`, holds uv's cache and the Python uv installs |
| `/opt/doc-intake-pipeline` | A checkout of a release tag, owned by `doc-intake`, with its `.env` (API key and settings) readable by that user only |
| `/usr/local/bin/uv` | uv, at the version `required-version` in `pyproject.toml` asks for |
| `/srv/doc-intake/inbox` | Where documents arrive: saved there, or a folder a Drive or Dropbox client keeps in sync |
| `/srv/doc-intake/runs` | One folder per run: `results.csv` and `documents/` |

Everything is installed as `doc-intake`, the user the service runs as: uv keeps its cache and the Python it downloads in the home of whoever runs it, so a `sudo uv sync` as root would leave the service without a Python it can read.

## Install

```bash
sudo useradd --system --create-home --home-dir /var/lib/doc-intake --shell /usr/sbin/nologin doc-intake
sudo mkdir -p /srv/doc-intake/inbox /srv/doc-intake/runs
sudo chown -R doc-intake: /srv/doc-intake /opt/doc-intake-pipeline
sudo chmod 600 /opt/doc-intake-pipeline/.env
cd /opt/doc-intake-pipeline
sudo -u doc-intake -H uv sync --locked --no-dev
sudo -u doc-intake -H uv run --locked --no-dev python -m scripts.fetch_tessdata  # OCR model, into .cache/tessdata
sudo cp deploy/doc-intake-inbox.service deploy/doc-intake-inbox.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now doc-intake-inbox.timer
```

Check it:

```bash
systemctl list-timers doc-intake-inbox.timer      # next and last run
sudo systemctl start doc-intake-inbox.service     # one run now
journalctl -u doc-intake-inbox.service            # summary line and run log
```

## Why these settings

- **No two runs at once.** With `Type=oneshot`, the service stays active until the run ends, and a timer does not start a service that is still active: "it is not restarted, but simply left running" ([systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)). No lock file is needed.
- **A run missed while the machine was off** starts at the next boot (`Persistent=true`, same page).
- **A failed run is visible.** The command exits 1 when a document failed, so `systemctl status` and `systemctl --failed` show it. A field to review is not a failure.
- **Files still arriving are left alone.** A file is taken once it has not changed for 60 seconds (`--settle`). Neither [Dropbox](https://help.dropbox.com/delete-restore/cache-folder) nor [Google Drive for desktop](https://support.google.com/drive/answer/16631477) documents how it writes a synced file, so the run does not assume a file appears whole.
- **Keep `inbox` and `runs` on one filesystem.** Within one filesystem a move is a rename; across filesystems it copies the file and then deletes it ([`shutil.move`](https://docs.python.org/3.14/library/shutil.html#shutil.move)), and a crash in between can leave a file in both places.

CI checks both unit files with `systemd-analyze verify` (unknown keys, a missing `ExecStart` binary). It does not start them: user, paths and permissions are checked on the machine, with the commands above.

## Other schedulers

- **cron:** a crontab line does not prevent overlap by itself. Wrap the command in [`flock -n`](https://man7.org/linux/man-pages/man1/flock.1.html), which gives up when the previous run still holds the lock:

  ```cron
  */15 * * * * cd /opt/doc-intake-pipeline && flock -n /tmp/doc-intake-inbox.lock /usr/local/bin/uv run --locked --no-dev python -m scripts.run_inbox /srv/doc-intake/inbox /srv/doc-intake/runs
  ```

- **Windows Task Scheduler:** keep the default "Do not start a new instance" ([`MultipleInstancesPolicy` `IgnoreNew`](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-multipleinstancespolicy-settingstype-element)), set "Start in" to the checkout, and run `uv run --locked --no-dev python -m scripts.run_inbox <inbox> <runs>`.
