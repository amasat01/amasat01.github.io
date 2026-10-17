# Contributing

Read [How we build](https://amasat01.github.io/raptor/content/principles.html) first: the twelve rules every pull request in the
family is read against, plus the style and license terms.

**This repo:** the family's front door at <https://amasat01.github.io/>. Plain pages that help a reader pick the right tool in
ten seconds. It holds no library code.

## Build and run the gate

```bash
pip install -r requirements.txt
make check        # the generated-content tests, then a strict build (zero warnings)
make linkcheck    # every external link
```

`make check` is what `.github/workflows/pages.yml` runs. It does not re-run `tools/sync_cards.py`: that script reads a real eagle
checkout when the cards change, and `make check` verifies the committed `_generated/` output against it.

## What a PR here must show

- **The voice.** The reader has a working JAX, PyTorch, CuPy/NumPy or Warp program and decides in ten seconds whether to stay.
  The title, the first line and the first thing on screen say what they get. Plain words, short sentences, a small example early.
- **Friendly to every tool.** Say what another tool is the right choice for. Never "replace your tool", never "lacks".
- **One number, one source.** A measured number reaches a page by `{include}` of a generated file, never typed by hand
  (`tests/test_one_number_rule.py`).
- **Generated pages are regenerated, not edited.** Change the card or the generator, run it, commit both.
- The family checklist from [How we build](https://amasat01.github.io/raptor/content/principles.html), nothing more.
