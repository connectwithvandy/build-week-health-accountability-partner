# Machine-level files Ted depends on

Ted runs on a Mac through Hermes, so two files outside this repo change how
it behaves. Both were edited on 2 Sep 2026 and neither was tracked anywhere,
which is how a folder rename silently disabled every safety gate that day.

## `plugin-shim.py`

Lives at `~/.hermes/plugins/ted-safety-gates/__init__.py`. Hermes loads it as
a plugin; it loads `hermes/ted_safety_gates/__init__.py` from this repo by
absolute path, which is what makes the repo the live safety code.

It tries the current project folder name first and the previous one second,
and raises if neither exists. **Hermes does not stop when a plugin fails to
load** — it keeps serving WhatsApp with the gates unloaded and logs nothing
about it, so `register()` announces itself on every boot.

Do not check that by eye. Run `npm run gates:guard` (or
`python3 scripts/ted-gate-guard.py`) after every restart, rename or gate edit.
It imports this shim the way Hermes does, confirms `ted_safety_gates_registered`
appears in `~/.hermes/logs/agent.log` *after* the last line of
`~/.hermes/gateway-starts.log`, and **stops the gateway** if it does not.
`--check-only` reports without touching anything. With the gateway down it exits 3 and says the gates are unverified rather than reporting green — nothing ungated is not the same as gates confirmed on.

This file is a symlink to the repo copy, so there is one file, not two.

## `hermes-config.yaml`

A **snapshot** of `~/.hermes/config.yaml`, not a symlink — Hermes owns that
file and may rewrite it. It will drift; re-copy it when it matters.

Re-copied 3 Sep 2026, and the drift was not harmless: the live file had gained
`display.provider_messages` and this snapshot had not, so reading the snapshot
said Ted still answered a provider outage with "check gateway logs for
diagnostics". It does not. **A stale snapshot does not read as stale — it reads
as the truth.** Re-copy it before trusting it:

```bash
cp ~/.hermes/config.yaml hermes/machine/hermes-config.yaml && git diff --stat
```

Three settings here are Ted-specific:

- `plugins.enabled: [ted-safety-gates]` — without this the gates never load.
- `cron.wrap_response: false` — Hermes otherwise wraps every scheduled
  reminder in a "Cronjob Response" header, the raw job_id, and footer
  instructions. SOUL.md forbids exposing internal status to the user, and a
  job_id in a health chat breaks the product.
- `display.provider_messages` — what a real user sees when the model provider
  fails. Without it they get the shipped defaults, which say "check gateway
  logs for diagnostics" to someone who came here to log their dinner. `stall`
  is deliberately empty: mid-call stall notices name the model and the context
  size and repeat once per reconnect (five copies reached one tester's thread),
  and a turn that ultimately fails still delivers the `generic` line, so
  suppressing them is not the same as going silent.
