# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0

# Minimal makefile for the RAPTOR family landing site (Sphinx, MyST/Markdown).
# A plain page plus an About page -- no notebooks, no API reference, so there
# is no nbexec/nbcheck here (unlike the four project sites' docs/Makefile).

SPHINXOPTS    ?=
SPHINXBUILD   ?= python -m sphinx
SOURCEDIR     = .
BUILDDIR      = _build

.PHONY: help Makefile clean livehtml media strict linkcheck check

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

clean:
	rm -rf $(BUILDDIR)

# The gallery animations and the landing thumbnails come from the paired hawk and eagle checkouts; they are build
# output and never committed (tools/gallery_gifs.py, tools/landing_thumbs.py).
HAWK ?= hawk
EAGLE ?= eagle
media:
	python3 tools/gallery_gifs.py $(HAWK) $(EAGLE)
	python3 tools/landing_thumbs.py

# Build with warnings promoted to errors, but keep going so a single run
# reports every warning instead of stopping at the first.
strict: media
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" -W --keep-going $(SPHINXOPTS) $(O)

linkcheck:
	@$(SPHINXBUILD) -M linkcheck "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

# The site's own gate: the generated-content tests (tests/test_sync_cards.py,
# self-contained -- no eagle checkout needed) plus a 0-warning strict build.
# The raptor_docs package tests (tests/test_raptor_docs_*.py) are in the same
# discovery: they need Python 3.11+, nbformat and nbclient (pyproject.toml).
# Does NOT re-run tools/sync_cards.py (that is maintenance-time, against a
# real eagle checkout); it checks the _generated/ output already committed. The two first-kernel notebooks
# (hawk's and eagle's copy) must match in cell types and sources: HAWK and EAGLE name the checkouts.
check:
	python3 -m unittest discover -s tests -v
	python3 -m raptor_docs.nb same $(HAWK)/docs/content/tutorials/01_your_first_kernel.ipynb $(EAGLE)/docs/content/userguide/first_kernel.ipynb
	$(MAKE) strict

# Watch for changes and auto-recompile (requires watchdog: pip install watchdog)
livehtml: Makefile
	watchmedo shell-command -p "*.md;*.py" -R \
	    -c "make html" \
	    -i "$(BUILDDIR)/*" \
	    --debug-force-polling .

# Catch-all target: route unknown targets to Sphinx.
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
