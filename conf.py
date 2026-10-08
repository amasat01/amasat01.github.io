# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

"""Sphinx configuration for the RAPTOR family landing site (amasat01.github.io)."""

# -- Project information -----------------------------------------------------

project = "RAPTOR family"
copyright = "2026, Alessandro Masat"
author = "Alessandro Masat"
version = release = "1.0"

# -- General configuration ---------------------------------------------------

# This site is a single landing page plus an About page -- no Python/C++ API
# to document, no notebooks to execute, so there is deliberately no autodoc,
# autosummary, breathe or myst_nb here (unlike the four project sites this
# page links to).
extensions = [
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

templates_path = ["_templates"]
# _generated/*.md are card-derived MyST include files (tools/sync_cards.py):
# {include}-d into index.md / where_raptor_fits.md, never a toctree entry of
# their own, so Sphinx must not treat them as standalone documents.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "README.md", "_generated/*.md"]

# notebooks/raptor_start_here.ipynb (start_here.md's trial notebook) is not a
# Sphinx source document (no myst_nb/nbsphinx here -- see conf.py's own note
# above) -- html_extra_path copies it byte-for-byte into the built site so it
# is downloadable straight off this site too, alongside the hero's
# GitHub-raw/Colab links (which point at the git path, notebooks/..., not
# this one). Sphinx flattens a single-level extra_path directory's contents
# to the site root, so the served copy lands at
# amasat01.github.io/raptor_start_here.ipynb, not .../notebooks/....
html_extra_path = ["notebooks"]

# -----------------------------------------------------------------------------
# HTML output
# -----------------------------------------------------------------------------

html_theme = "sphinx_book_theme"
# _static/figures/ holds the hand-authored (and, for the comparison chart,
# generated-from-a-card) explanatory SVGs: light + dark pairs, swapped via
# the theme's .only-light/.only-dark classes against html[data-theme].
# _static/brand/ holds the fixed wide-family mark, resized PNGs only --
# see _static/custom.css's header comment for why dark mode here keys off
# the theme's own toggle attribute rather than prefers-color-scheme.
html_static_path = ["_static"]
html_css_files = ["custom.css"]
# js/thread.js: the hero's thread animation.
# Plays once on index.md; mount() is called inline, right after the figure,
# since no other page loads a <svg id="thread">.
html_js_files = ["js/thread.js"]

html_theme_options = {
    "repository_url": "https://github.com/amasat01/amasat01.github.io",
    "use_repository_button": True,
    "collapse_navigation": True,
    "navigation_with_keys": True,
    "pygments_light_style": "tango",
    "pygments_dark_style": "monokai",
}
# Full-width hero on the front page only: every other page keeps the left
# nav (3 links is little, but build_from_source/about/where_raptor_fits and
# the new compare page are still worth a sidebar). The front page ALSO drops
# the theme's top navbar, article-header icon row and right "Contents"
# sidebar -- see _templates/layout.html -- so its own header (mark + RAPTOR +
# Start here/Docs/Compare/GitHub, index.md) is the only chrome on that page.
html_sidebars = {"index": []}

html_title = "RAPTOR family"
# A wordmark lockup (mark + "RAPTOR") may replace this later; for now the mark alone (in the hero) plus this bold title
# carry the brand in the tab/header chrome.
html_logo = "_static/brand/wide_family_raptor_light.png"
html_favicon = "_static/brand/favicon_32.png"
