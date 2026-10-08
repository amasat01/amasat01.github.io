# Fixture card script: a tiny stand-in for the real benchmarks/rk78_card/rk78_card.py,
# just enough `# >>> code:NAME` / `# <<< code:NAME` marked blocks for the sync tool's
# tests to parse. Not a real benchmark.

# >>> code:eagle_body
def eagle_step(x):
    return x + 1
# <<< code:eagle_body

# >>> code:cupy_body
def cupy_step(x):
    return x + 1
# <<< code:cupy_body

# >>> code:torch_body
def torch_step(x):
    return x + 1
# <<< code:torch_body

# >>> code:jax_body
def jax_step(x):
    return x + 1
# <<< code:jax_body

# >>> code:warp_body
def warp_step(x):
    return x + 1
# <<< code:warp_body
