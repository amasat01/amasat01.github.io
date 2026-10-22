# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Sphinx extension: the family skin. Add ``extensions += ["raptor_docs.sphinx"]`` to a docs ``conf.py``.

It adds the font and the three ``raptor-*.css`` files (shipped in this package, so a build needs no network), the favicon
links, the shared theme options, heading anchors and ``llms.txt``. A repo's own ``html_theme_options`` keys win; its own
``html_static_path`` and ``html_css_files`` are kept (an ``*accent.css`` file is placed before the skin, the rest after).
"""
import pathlib

from raptor_docs.llms import write as write_llms

STATIC = pathlib.Path(__file__).resolve().parent / "_static"
#: the favicon files each repo keeps under its own ``_static/brand``
ICONS = (("icon", "brand/favicon.ico", 'sizes="any"'), ("icon", "brand/favicon.svg", 'type="image/svg+xml"'),
         ("apple-touch-icon", "brand/app_icon_180.png", ""))
FOOTER = '<div class="raptor-family-chip">part of <a href="https://amasat01.github.io/">RAPTOR</a></div>'
THEME_DEFAULTS = {
    "repository_branch": "main", "path_to_docs": "docs", "use_repository_button": True, "collapse_navigation": True,
    "navigation_with_keys": True, "pygments_light_style": "tango", "pygments_dark_style": "monokai", "extra_footer": FOOTER,
    "launch_buttons": {"colab_url": "https://colab.research.google.com", "notebook_interface": "classic"},
}


def _config_inited(app, config):
    config.html_static_path = [*config.html_static_path, str(STATIC)]
    own = list(config.html_css_files)
    accent = [f for f in own if str(f).endswith("accent.css")]
    config.html_css_files = ["raptor-tokens.css", *accent, "raptor-theme.css", "raptor-reveal.css", *[f for f in own if f not in accent]]
    config.html_theme_options = {**THEME_DEFAULTS, **config.html_theme_options}
    config.myst_heading_anchors = max(getattr(config, "myst_heading_anchors", None) or 0, 3)


def _icons(app, pagename, templatename, context, doctree):
    pathto = context.get("pathto")
    if pathto is not None:
        links = "".join(f'<link rel="{rel}" href="{pathto("_static/" + path, 1)}" {extra}>\n' for rel, path, extra in ICONS)
        context["metatags"] = context.get("metatags", "") + links


def setup(app):
    app.connect("config-inited", _config_inited)
    app.connect("html-page-context", _icons)
    app.connect("build-finished", write_llms)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
