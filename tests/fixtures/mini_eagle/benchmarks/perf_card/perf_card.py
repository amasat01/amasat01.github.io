# Fixture card script: a tiny stand-in for the real benchmarks/perf_card/perf_card.py.
# Not a real benchmark.

# >>> code:eagle_body
def eagle_step(x):
    return x + 1
# <<< code:eagle_body

# >>> code:cupy_body
def cupy_step(x):
    return x + 1
# <<< code:cupy_body
