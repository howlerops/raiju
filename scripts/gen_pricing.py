#!/usr/bin/env python3
"""Write src/pricing_data.tov from a Bifrost pricing datasheet, or merge audio rates into it.

Usage: scripts/gen_pricing.py DATASHEET.json
       scripts/gen_pricing.py --merge PRICES.json

The datasheet is a JSON object keyed by model name (https://getbifrost.ai/datasheet).
Each entry with a token price becomes one line of a compact table:

    key  provider  input  output  cacheRead  cacheWrite  baseModel  [inputAudio  outputAudio  perSecond]

The last three columns are written only for a model with an audio token rate or a voice rate per second
(realtime and live models); other rows keep seven columns.
Prices are USD per token as plain decimals; a missing rate is an empty field.
Lines are sorted by (key length, key), so the first line for a provider and
base model is the plainest name. Re-run this after replacing the datasheet.
Tov cannot read files at build time, so the table is compiled in as a
template literal.

Merge mode reads the table in place and a price file with Bifrost's field names (LiteLLM's
model_prices_and_context_window.json is one; the Bifrost datasheet descends from it). It fills
only the audio and per-second columns, and only for rows whose key and provider the price file
has too: a row keeps its token rates, and a row whose provider differs is skipped. Every changed
cell and every token rate that disagrees with the price file is reported; the disagreements are
not applied. The header records the price file's name, sha256 and the merge date.
"""
import datetime
import hashlib
import json
import math
import pathlib
import re
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "pricing_data.tov"
EXPORT = "export const PRICING_DATA: string = "
# the token-rate columns (USD per token) and the audio and per-second columns of a row
TOKEN_COLUMNS = (("input_cost_per_token", 2), ("output_cost_per_token", 3), ("cache_read_input_token_cost", 4), ("cache_creation_input_token_cost", 5))
WIDE_COLUMNS = (("input_cost_per_audio_token", 7), ("output_cost_per_audio_token", 8), ("input_cost_per_second", 9))
# header lines that a merge writes; a merge drops them from the header it reads and writes its own
MERGE_NOTE = "// Audio and per-second columns merged from"
NOTES = ("// (The audio columns", MERGE_NOTE)


def plain(value, key):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit("%s: price is not a number: %r" % (key, value))
    if value < 0:
        raise SystemExit("%s: negative price: %r" % (key, value))
    # repr keeps the shortest round-trip digits; Decimal avoids exponent form.
    return format(Decimal(repr(value)), "f")


def text(value, key):
    s = "" if value is None else str(value)
    if "\t" in s or "\n" in s or "\r" in s:
        raise SystemExit("%s: field contains a tab or newline" % key)
    return s


def tov_template(body):
    # Inside a template literal only backslash, backtick and "${" need escaping.
    out = body.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return "`" + out + "`"


def render(header, rows):
    """The table file's text: the header lines, then the rows as a template literal."""
    body = "\n".join("\t".join(r) for r in rows) + "\n"
    return "\n".join(header + [""]) + EXPORT + tov_template(body) + "\n"


def read_table(path):
    """The header lines (without the notes of an earlier merge) and the rows of a table file."""
    head, _, rest = path.read_text(encoding="utf-8").partition(EXPORT)
    header = head.split("\n")[:-1]
    header = header[:next((i for i, line in enumerate(header) if line.startswith(NOTES)), len(header))]
    # the literal is `...`, with the escapes tov_template adds undone
    escaped = rest[1:rest.rindex("`")]
    body = re.sub(r"\\(.)", r"\1", escaped, flags=re.S)
    return header, [line.split("\t") for line in body.split("\n") if line]


def provider_name(p):
    """A provider under the table's name for it: Raiju's normalizeProvider (src/pricing.tov), Vertex's
    model kinds, and Cohere's chat models, which the table files under cohere."""
    if p.startswith("bedrock"):
        return "bedrock"
    if p.startswith("vertex_ai") or p in ("vertex", "google-vertex"):
        return "vertex_ai"
    if p == "cohere_chat":
        return "cohere"
    return p


def price_entry(prices, key, provider):
    """The price file's entry for a table row, or (None, reason) when it files the model under another provider.

    The row's key itself is tried first, then the bare model under the row's provider (gemini/x for x).
    """
    names = [key]
    if "/" not in key and provider:
        names.append(provider + "/" + key)
    for name in names:
        entry = prices.get(name)
        if isinstance(entry, dict):
            filed = provider_name(entry.get("litellm_provider") or "")
            if filed != provider_name(provider):
                return None, "%s: the price file files it under %s, the table under %s" % (name, filed, provider)
            return entry, None
    return None, None


def cell(text_value):
    return float(text_value) if text_value else 0.0


def amount(value):
    return 0.0 if value is None else float(value)


def merge(table, prices_path, day):
    """Fills the audio and per-second columns of the table from a price file.

    Returns (changes, disagreements, skipped): changes are (key, field, old, new), disagreements are
    (key, field, table, price file) for token rates that differ and are not applied, skipped are reasons.
    """
    raw = prices_path.read_bytes()
    prices = json.loads(raw)
    if not isinstance(prices, dict):
        raise SystemExit("price file must be a JSON object keyed by model")
    header, rows = read_table(table)
    changes, disagreements, skipped = [], [], []
    for row in rows:
        key, provider = row[0], row[1]
        entry, why = price_entry(prices, key, provider)
        if why is not None:
            skipped.append(why)
            continue
        if entry is None:
            continue
        for field, col in TOKEN_COLUMNS:
            if not math.isclose(cell(row[col]), amount(entry.get(field))):
                disagreements.append((key, field, row[col] or None, entry.get(field)))
        row.extend([""] * (10 - len(row)))
        for field, col in WIDE_COLUMNS:
            value = entry.get(field)
            if value is None:
                continue
            new = plain(value, key)
            old = row[col]
            if old != "" and math.isclose(float(old), float(new), rel_tol=1e-9):
                continue
            changes.append((key, field, old or None, new))
            row[col] = new
        # as the generator writes them: a row has the audio columns only when one of them has a rate
        if not any(row[7:10]):
            del row[7:]
    digest = hashlib.sha256(raw).hexdigest()
    note = [
        "%s %s (sha256 %s, %s) by scripts/gen_pricing.py --merge." % (MERGE_NOTE, prices_path.name, digest, day),
        "// Its price file is LiteLLM's model_prices_and_context_window.json, which the Bifrost datasheet descends from.",
        "// Token rates are the datasheet's; the merge never changes them.",
    ]
    table.write_text(render(header + note, rows), encoding="utf-8")
    return changes, disagreements, skipped


def generate(src):
    raw = src.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("datasheet must be a JSON object keyed by model")

    rows = []
    for key in data:
        entry = data[key]
        if not isinstance(entry, dict):
            continue
        inp = entry.get("input_cost_per_token")
        out = entry.get("output_cost_per_token")
        sec = entry.get("input_cost_per_second")
        if inp is None and out is None and sec is None:
            continue
        text(key, key)
        row = (
            key,
            text(entry.get("provider"), key),
            plain(inp, key),
            plain(out, key),
            plain(entry.get("cache_read_input_token_cost"), key),
            plain(entry.get("cache_creation_input_token_cost"), key),
            text(entry.get("base_model"), key),
        )
        # realtime and live models carry audio token rates and a voice rate per second: three more columns
        wide = (
            plain(entry.get("input_cost_per_audio_token"), key),
            plain(entry.get("output_cost_per_audio_token"), key),
            plain(sec, key),
        )
        rows.append(row + wide if any(wide) else row)
    rows.sort(key=lambda r: (len(r[0].encode("utf-8")), r[0]))

    digest = hashlib.sha256(raw).hexdigest()
    header = [
        "// Generated by scripts/gen_pricing.py from a Bifrost pricing datasheet. Do not edit.",
        "// Source: %s, sha256 %s, %d priced entries." % (src.name, digest, len(rows)),
        "// Columns, tab-separated: key, provider, input, output, cacheRead, cacheWrite, baseModel, and for",
        "// a realtime or live model inputAudio, outputAudio, perSecond (a row has 7 or 10 columns).",
        "// Prices are USD per token (perSecond: per second); an empty field means the datasheet has no such rate.",
    ]
    OUT.write_text(render(header, rows), encoding="utf-8")
    print("wrote %s: %d entries" % (OUT, len(rows)))


def main(argv):
    if len(argv) == 3 and argv[1] == "--merge":
        changes, disagreements, skipped = merge(OUT, pathlib.Path(argv[2]), datetime.date.today().isoformat())
        for key, field, old, new in changes:
            print("changed %s %s: %s -> %s" % (key, field, old or "(none)", new))
        for key, field, have, file_rate in disagreements:
            print("disagrees (not applied) %s %s: table %s, price file %s" % (key, field, have or "(none)", file_rate))
        for why in skipped:
            print("skipped %s" % why)
        print("merged %s: %d cells changed, %d token rates disagree, %d rows skipped" % (OUT, len(changes), len(disagreements), len(skipped)))
        return
    if len(argv) != 2:
        raise SystemExit(__doc__)
    generate(pathlib.Path(argv[1]))


if __name__ == "__main__":
    main(sys.argv)
