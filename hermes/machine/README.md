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
about it, so `register()` announces itself on every boot. Check for
`ted_safety_gates_registered` in `~/.hermes/logs/agent.log` after a restart.

This file is a symlink to the repo copy, so there is one file, not two.

## `hermes-config.yaml`

A **snapshot** of `~/.hermes/config.yaml`, not a symlink — Hermes owns that
file and may rewrite it. It will drift; re-copy it when it matters.

Two settings here are Ted-specific:

- `plugins.enabled: [ted-safety-gates]` — without this the gates never load.
- `cron.wrap_response: false` — Hermes otherwise wraps every scheduled
  reminder in a "Cronjob Response" header, the raw job_id, and footer
  instructions. SOUL.md forbids exposing internal status to the user, and a
  job_id in a fitness chat breaks the product.
