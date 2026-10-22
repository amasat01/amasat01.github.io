# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Notebook tools: ``python -m raptor_docs.nb <check|execute|run_gate|colab_setup|hosted> [args]``."""
import importlib
import sys

COMMANDS = ("check", "execute", "run_gate", "colab_setup", "hosted")


def discover(roots):
    """Every notebook of each checkout, by glob (see ``run_gate.discover``); Kaggle's driver imports it from here."""
    from raptor_docs.nb import run_gate
    return run_gate.discover(roots)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: python -m raptor_docs.nb {{{'|'.join(COMMANDS)}}} [args]", file=sys.stderr)
        return 2
    mod = importlib.import_module(f"raptor_docs.nb.{argv[0]}")
    # the moved tools take their own argv with the program name first; hosted takes the arguments only
    return mod.main(argv[1:] if argv[0] == "hosted" else argv) or 0
