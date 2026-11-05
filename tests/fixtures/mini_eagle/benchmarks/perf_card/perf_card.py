# Fixture card script: a tiny stand-in for the real benchmarks/perf_card/perf_card.py.
# Not a real benchmark. Block line counts match code_lines in the fixture cards.

# >>> code:shared_scheme
def scheme(x):
    return x + 1
# <<< code:shared_scheme

# >>> code:hawk_kernel
def kernel(x):
    return scheme(x)
# <<< code:hawk_kernel

# >>> code:hawk_launch
launch(kernel)
# <<< code:hawk_launch

# >>> code:eagle_simulate
simulate(kernel)
# <<< code:eagle_simulate

# >>> code:cupy_masked
def masked(x):
    return scheme(x)
# <<< code:cupy_masked
