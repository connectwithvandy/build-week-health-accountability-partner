# T09 — deletion, and the proof that it happened

**Status: the deletion works. The verification did not exist, and building it
found that one real erasure did not hold.**

T09's definition of done:

> One confirmed deletion request leaves no active user data or scheduled action
> in any declared store, **verified by an automated post-delete search**.

Everything before that last clause was already built: `_delete_user_data`
behind three guards, the exact-match confirmation list that closed the "Ges"
typo, `_forget_user` for gate state, `ted-forget-user.py` for the machine half,
media matched by arrival time (7 of 7 photos, 29 of 29 voice notes). What was
missing is the clause itself. Nothing checked afterwards — and a deletion that
half worked looks exactly like one that worked, from the outside, forever.

`npm run deletion:audit` is that search.

---

## 1. What it found on its first run

One person has ever asked Ted to forget them. **Udayan, 3 September 2026,
22:59.** Four things still hold him, sixteen days later.

```
Udayan
  1 gate key(s), 1 identifier(s), 2 session(s) known.
  LIVE  ted-safety-gates-onboarding.json: record marked forgotten still holds name='UD'
  LIVE  state.db messages: 25 row(s)
  LIVE  state.db sessions: 2 row(s)
  LIVE  channel_directory.json: names <his chat id, redacted here>
```

### The name is the one that should not be possible

`_forget_user` empties the record and then writes back a tombstone on purpose.
Its own comment is explicit about the size of it:

> a hashed key and a time, no profile and nothing they told Ted. Keeping
> strictly less than the deletion removed is the trade that makes the deletion
> hold.

The live record is `{"forgotten_at": 1788456543.297, "name": "UD"}`.

The snapshots date it. The two from before the deletion — 3 Sep 15:19 and 3 Sep
21:05 — have no record for him at all. Every snapshot from 4 Sep 12:27 onward
has the name. **Something wrote a name back into an erased record within about
thirteen hours**, and the transcript rules out the innocent explanation: his
last exchange is Ted saying *"haha no idea yet, that's got wiped along with
everything else"*, and he never wrote again, so he did not come back and
introduce himself.

Which writer did it is not yet known. Nine repair scripts write these files and
several ran in that window. What is already clear is the class: **the deletion
path and the repair paths do not know about each other**, and a tombstone is
just another record to a script iterating users.

### The messages are a known gap, and that is not the same as an acceptable one

`src/app/privacy/page.tsx` says plainly that the conversation Ted holds on his
own machine sits outside what "delete my data" reaches, and that a person has
to do that half. It is honest. `ted-forget-user.py` is the tool for it, and
**for the one person who ever asked, it was never run.**

That is the real shape of T09's failure here. Not a bug in the code: a workflow
with a manual step, and the manual step did not happen, and nothing anywhere
said so for sixteen days.

### channel_directory.json was never declared

22 routing targets, one per chat, and nothing removes a deleted person.
`ted-forget-user.py` does not mention it because nobody knew it was a store.
Found by grepping one live user's id across `~/.hermes` and getting 25 files
back, against the four the script declares.

*His chat id is redacted in the block above, and appears nowhere in this
repository. This is a public repo, and publishing the identifier of the one
person who asked to be forgotten is the precise thing this task exists to
prevent. `npm run deletion:audit` prints it in full on the machine, which is
where it belongs.*

## 2. Every store, declared

The list the audit searches. Live stores must be empty after a deletion;
retention is named rather than emptied.

| store | what it holds | cleaned by |
| --- | --- | --- |
| `state.db` messages, sessions | the conversation | `ted-forget-user.py` |
| `state.db` delivery_obligations | reply text queued for a chat | `ted-forget-user.py` |
| `state.db` gateway_routing | session key, an identifier | `ted-forget-user.py` |
| `~/.hermes/sessions/` | request dumps, whole API calls | `hermes sessions delete` |
| `cache/images`, `cache/audio` | photos and voice notes | `ted-forget-user.py` |
| `state/ted-safety-gates-*.json` | onboarding, disclosures | `_forget_user` (live pair) |
| `cron/jobs.json` | **scheduled reminders** | **nothing** |
| `channel_directory.json` | routing targets | **nothing** |
| `whatsapp/lid-phone-map-*.json` | phone ↔ lid mapping | **nothing** |
| `state/*.bak*`, `cron/*.bak*` | pre-repair snapshots | retention, by design |
| `profiles/backup*/` | whole profile copies | retention, by design |
| `~/ted-backups/` | daily backup, drilled | retention, by design |
| Convex | profile, facts, targets, logs | `_delete_user_data` |

**Cron is the one that would be felt.** T09 asks for future reminders to be
cancelled, and nothing in either half of the deletion touches `jobs.json`. A
deleted person with an enabled job hears from Ted after asking to be erased.
Udayan has none, so this has never happened — it is unexercised, not safe.

**The retention rows are a decision, not a leak.** A backup that forgets on
demand is not a backup, and `ted-backup.py` exists because a host move is when
data is lost. The audit reports them under `kept` and never fails on them. What
matters is that they are named: an undeclared store is the one nobody empties.

## 3. What the audit does not do

- **It does not delete.** It is the check, not the cure. Every finding above is
  still true as of this commit.
- **It does not reach Convex.** The remote half has its own guards and its own
  check (`npm run convex:check`). A local search that silently skipped a remote
  store would be the exact failure this file exists to prevent, so it is said
  here instead of implied.
- **It cannot reverse a hash.** Gate keys are `sha256("whatsapp:" + id)`, so
  the audit hashes every known id and compares. A key with no match means the
  sessions table no longer knows that person, which is the outcome asked for.
  The key count is printed next to the findings so a derivation that drifted
  reads as "1 key, 0 records" rather than as success.

## 4. Open, and each one is somebody's decision

1. **Run `ted-forget-user.py` for Udayan.** It is what the privacy page
   promises and it is fifteen days overdue. Irreversible, so it is not run
   from here.
2. **Clear the name from the tombstone**, and find which writer put it there.
   The fix is the class, not the record: a repair script must skip a record
   marked `forgotten_at`.
3. **Cancel cron jobs on deletion.** Nothing does this today.
4. **Remove a deleted person from `channel_directory.json`.**
5. **Decide the backup answer.** A deletion request and a seven-day backup
   retention are in genuine tension, and the honest options are to say so in
   the privacy page or to exclude erased users on restore. Not a code question.

## Re-verify

```bash
npm run deletion:audit               # everyone marked forgotten
python3 scripts/ted-deletion-audit.py --who Udayan --all-stores
python3 scripts/ted-forget-user.py --who Udayan     # dry run, shows the plan
```
