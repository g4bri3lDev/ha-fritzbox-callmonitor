# AGENTS.md

Guidance for coding agents working in this repository. `CLAUDE.md` is a symlink
to this file, so there is only one document to keep current.

## What this is

A HACS custom integration that **overrides the core `fritzbox_callmonitor`
domain**. Domain `fritzbox_callmonitor`, `integration_type: device`,
`iot_class: local_polling`, config flow, no YAML configuration.

- Home Assistant floor: `2026.7.0` (`hacs.json`), Python `>=3.14.2`
- Integration source: `custom_components/fritzbox_callmonitor/`
- The one runtime library comes from `manifest.json`: `fritzconnection[qr]`.
  Home Assistant installs it at runtime. Never `pip install` it into a HA
  runtime to test a bump: edit `manifest.json` and restart HA.

## Overriding core is the central constraint

Installing this shadows core's integration. Two consequences drive most
decisions here:

1. **An existing core config entry must keep working.** The config flow, the
   entry data keys and the call-state sensor's unique id
   (`f"{serial_number}-{phonebook_id}"`) are contractual. Changing any of them
   orphans the entity and its recorded history. Every option this integration
   adds has a default, because an entry created by core has none of them.
2. **Core fixes do not reach users automatically.** `scripts/diff-core` diffs
   the vendored modules against a core checkout. Run it after a core release,
   triage each hunk, then update the baseline below.

**CORE_BASELINE: `72681140f67` (2026-09-13).**

`base.py` and `config_flow.py` are near-verbatim from core, with one deliberate
change each (see below). `sensor.py` keeps core's two classes untouched and
appends to them. Keeping those files close to core is what makes `diff-core`
useful, so prefer adding a new module over editing a vendored one.

## Commands

```bash
scripts/setup            # uv sync --group dev
scripts/test             # pytest against the pinned latest HA
scripts/test --min-ha    # pytest against the hacs.json floor
scripts/test -k lookup   # any other argument passes through to pytest
scripts/lint             # ruff check --fix, then ruff format
scripts/diff-core        # diff the vendored modules against core
```

CI runs the non-fixing form: `uv run ruff check .` and `uv run ruff format --check .`.

There is **no typecheck command and no mypy configuration**. Never claim a
typecheck passed.

Dependencies are two mutually exclusive uv groups resolved from one lockfile:
`dev` (newest HA) and `min-ha` (the `hacs.json` floor). CI runs both legs and
both must pass.

`scripts/probe.py` talks to a real FRITZ!Box, read-only, and prints the call
list raw and normalized. It is the way to check `CallRecord` against a specific
FRITZ!OS version without running Home Assistant.

## Architecture

| File | Purpose |
|---|---|
| `__init__.py` | Entry setup and unload, `FritzBoxCallMonitorData`, one shared `FritzConnection` |
| `const.py` | Core's constants plus this integration's options, defaults and limits |
| `base.py` | **Vendored.** `FritzBoxPhonebook` and `Contact`. Changed to take a `FritzConnection` instead of building one |
| `config_flow.py` | **Vendored.** Changed so `_try_connect` builds one connection instead of two; options flow extended |
| `models.py` | `CallRecord`: normalizes a `fritzconnection` `Call` into the template contract |
| `coordinator.py` | Polls the call list, resolves names, exposes `calls` / `missed_calls` |
| `lookup/` | Optional reverse lookup: orchestrator, persistent cache, one module per provider |
| `sensor.py` | **Mostly vendored.** Core's call-state sensor and monitor, plus `FritzBoxCallHistorySensor` |
| `services.py` | `get_calls` and `lookup_number`, both response-only |
| `diagnostics.py` | Redacted entry dump; call records are redacted to their shape |

Data flow: one `FritzConnection` is created at setup and shared by
`FritzPhonebook` (names) and `FritzCall` (history). The coordinator polls every
5 minutes; separately, `FritzBoxCallMonitor._parse` sees `DISCONNECT` on its own
thread and pushes a delayed refresh, so a finished call reaches a display in
seconds rather than minutes.

## Conventions

- **`CallRecord.as_dict()` is a public contract.** Its keys end up in a state
  attribute that user templates loop over. Adding a key is safe; renaming or
  removing one breaks dashboards. Every key is always present, so templates
  never need `default()`.
- **Name resolution order is phonebook → the box's own `Name` → lookup.**
  Checking the phonebook first is not just an optimization: it is what keeps
  known contacts from being sent to a third party.
- **Reverse lookup is opt-in and must stay inert when off.** With
  `lookup_provider: none` there are no requests and no cache file. A test
  asserts this.
- **Lookup providers must fail soft.** Any network, parse or format problem
  returns `None`. A scraper that raises would take down the coordinator refresh
  and with it the whole history. Providers also warn once, then drop to debug.
- **Ambiguity is not a result.** If a directory returns several different names
  for one number, return none. A wrong name on a display is worse than none.
- **The monitor runs on its own thread.** Anything it touches on the Home
  Assistant side goes through `hass.loop.call_soon_threadsafe`, and anything
  scheduled from there must be a `@callback`, or Home Assistant will run it in
  an executor and the thread-safety check will fire.
- **`history_limit` is capped at 50** to stay under the recorder's
  `MAX_STATE_ATTRS_BYTES` (16 KiB). A test asserts the worst case.

## The display blueprint

`blueprints/automation/fritzbox_callmonitor/call_list_400x300.yaml` draws the
call list on a 400x300 BWRY OpenDisplay tag. Two things about it are easy to
get wrong:

- **Commas go in front of every element**, not after. The loop emits
  conditional elements (the missed/VIP edge marker, the SPAM badge, the
  divider), and a trailing comma after the last one is invalid JSON. Leading
  commas are immune to which branches fire.
- **It may only use Home Assistant template functions.** `now`, `timedelta`,
  `as_timestamp` and `timestamp_custom` are available; custom filters are not.
- **Python literals, never JSON literals.** Write `True`/`False`/`None`, not
  `true`/`false`/`null`. Home Assistant renders a templated service field to a
  string and then runs `ast.literal_eval` on it; that is *Python* syntax, so a
  JSON `true` makes the parse fail, the field stays a string, and
  `opendisplay.drawcustom` (schema `vol.Required("payload"): list`) rejects the
  call with `expected list at 'payload'`. The payload therefore looks like JSON
  but is not JSON -- do not "fix" it by validating with `json.loads`, which
  accepts payloads Home Assistant refuses.

- **Redraw as rarely as the content allows.** The tag is battery powered and
  every redraw is a panel refresh. The blueprint draws on a new call, on Home
  Assistant start, and once at 00:01 -- that last one only because relative
  dating goes stale at midnight, when last night's call has to stop saying
  "23:50" and start saying "Gestern". For the same reason the header carries
  the date rather than a clock: a clock redrawn daily would sit there lying,
  while a date that is not today is a useful sign that something is stuck.
- **Never commit a font.** The blueprint takes a font by *name*, and the repo
  ships none. `ppb.ttf` (Poppins Bold) and `rbm.ttf` (Roboto Medium) come from
  odl-renderer. Anything else is the user's own licence to hold: Gotham, for
  one, is a commercial typeface, and putting the file in a public repository
  would be redistributing it.
- **`number` stays raw, `number_formatted` is for display.** German area codes
  run from two to five digits (`030`, `0871`, `01511`, `08704`), so the split
  cannot be done by slicing and `phonenumbers` does it. Formatting is cosmetic,
  so anything unparseable or invalid falls back to the raw number rather than
  erroring or going empty. The region comes from the box's own `Country` field,
  falling back to `DE`.
- **Say where a name came from.** `name_source` distinguishes the user's own
  phonebook from a directory's guess, and the blueprint marks the latter with a
  globe. Treating the two as interchangeable on screen is how a wrong lookup
  becomes a wrong caller nobody questions.
- **Never red on black.** The panel's inks are measured, not idealised: black
  `(10, 7, 14)`, white `(173, 178, 174)`, yellow `(172, 128, 0)`, red
  `(85, 24, 14)`. That red is a dark maroon, so against the black header bar it
  reaches **1.45:1** and all but vanishes, while yellow gets 5.57:1 and white
  9.29:1. Red is still the right colour for a missed call *in the rows*, where
  it sits on white at 6.4:1. Ink values come from py-opendisplay's
  `DISPLAY_PALETTE_MAP` (panel `0x0037`, `ColorScheme.BWRY`).
- **Fine detail must use a solid ink.** The 4.1" tag is a BWRY panel -- black,
  white, red, yellow, no grey -- and `drawcustom` error-diffusion dithers
  anything else before sending. A 14px grey label survives that; a 1px grey
  hairline does not, because it has no area for the dither pattern to average
  over. Measured on the real layout, a `ltgray` separator kept 1-12% of its
  pixels. Greys are fine for text, never for hairlines.

`scripts/preview-blueprint.py` renders the blueprint's own payload to a PNG with
sample data and no Home Assistant, reimplementing those four helpers so it
renders exactly the shipped text. Run it after touching the template; the images
in `docs/images/` come from it. It also dithers every render to the BWRY
palette and warns about lines that do not survive, because the RGB PNG (and the
`image.` entity in Home Assistant, which shows the same pre-dither frame) looks
perfect while the hardware does not; `--panel` saves that simulation. The
sample data deliberately covers an unknown
number, a long VIP name, a spam-scored caller, an outgoing call, a withheld
caller and a name long enough to truncate.

**A withheld caller has an empty `number` and the box's own placeholder in
`name`** (3 of 16 calls on a real box). `_async_resolve` already skips a record
with no number, so nothing is looked up for it; templates have to handle it
too, or they print a blank line where the number goes.

## Brand assets

`custom_components/fritzbox_callmonitor/brand/` exists because the HACS brands
check looks for a *custom* integration of this domain in the brands repository,
and `fritzbox_callmonitor` is listed there as a **core** integration instead --
so the lookup fails and the check falls back to local assets. They are the same
FRITZ! images the brands repository publishes for this integration. Do not
remove them: the HACS workflow fails without them.

## Testing

`pytest-homeassistant-custom-component`. `tests/conftest.py` mocks only the
`fritzconnection` classes — `FritzBoxPhonebook` and the config flow stay real,
so tests exercise the actual prefix and normalization logic.

- `tests/fritz.py` reproduces `Call`'s awkward shape on purpose: raw AVM node
  names, lowercase converted accessors, and the library's habit of returning the
  raw string when a conversion fails. `CallRecord` exists to absorb that, so the
  fakes have to reproduce it faithfully.
- `tests/fixtures/dasoertliche_hits.html` is trimmed from a real response, and
  is the ambiguous case: several businesses sharing one hotline number.
- The event-reading thread is patched out in `mock_fritz`; tests drive
  `FritzBoxCallMonitor._parse` directly instead, since the real thread blocks on
  a 10 s queue timeout that outlives a test.
