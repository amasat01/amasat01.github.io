# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""``llms.txt``: the built site's pages as a plain list, in toctree order, for tools that read a site without rendering it."""
import pathlib


def pages(env, doc=None, seen=None):
    """Docnames reachable from ``doc`` (default: the root document) through toctrees, depth first, each once."""
    doc = doc or env.config.root_doc
    seen = [] if seen is None else seen
    if doc in seen or doc not in env.titles:
        return seen
    seen.append(doc)
    for child in env.toctree_includes.get(doc, []):
        pages(env, child, seen)
    return seen


def write(app, exception):
    if exception or app.builder.format != "html":
        return
    env, cfg = app.env, app.config
    base = (cfg.html_baseurl or "").rstrip("/") + ("/" if cfg.html_baseurl else "")
    lines = [f"# {cfg.project}", "", f"> {cfg.html_title or cfg.project}", ""]
    for doc in pages(env):
        lines.append(f"- [{env.titles[doc].astext()}]({base}{doc}.html)")
    (pathlib.Path(app.outdir) / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
