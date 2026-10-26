# Why RAPTOR is built this way

Let mathematics reveal the structure of physics. Let modern computing carry the computational burden.

Physics should not have to become tensor-shaped to run efficiently on modern hardware.

## Two ideas

Mathematics should expose and exploit the useful structure of a physical problem, not compensate for the limits of old
computers. Modern heterogeneous hardware should serve that structure as it is.

So the family keeps mathematics where it earns its place: where it exposes structure, improves conditioning or
stability, reduces dimension, gives a guarantee or gives understanding. It adds no complexity only to work around a limit
that current hardware no longer has. It is not against mathematics, and it is not against tensor frameworks. Tensor
frameworks are exceptionally effective for the structures they were designed for; generic physics often is not that
shape. Dense products and large solvers stay with PyTorch, JAX and CuPy, which RAPTOR exchanges arrays with without a copy. Not covered: sparse direct solvers, and several GPUs or MPI ranks (not in the docs yet).

## One job per layer

Each layer has one responsibility, and the engine knows nothing about any domain.

| Layer | Owns |
|---|---|
| [raptor](https://amasat01.github.io/raptor/) | the contracts: manifest, engine and launcher protocols, the interop matrix |
| [aether](https://amasat01.github.io/aether/) | domain-independent numerics: arrays, expressions, per-lane linear algebra, compensated sums |
| [hawk](https://amasat01.github.io/hawk/) | the vocabulary you write in, the IR, differentiation and code generation |
| [eagle](https://amasat01.github.io/eagle/) | graphs, scheduling, divergent execution and the mapping to hardware |

Differentiation, compilation, scheduling, hardware mapping and parallel execution are infrastructure. An application
composes the vocabulary; it does not reimplement any of them.

## Keep the structure

A model keeps the differences that mean something. A stencil stays a stencil, a per-lane solve stays a per-lane solve,
and a sample that finishes early stops costing work. Nothing is reshaped into a tensor program first.

## Does it scale?

The test is one question: can the space of applications grow without the core growing with it? New problems should
usually need new compositions, not new machinery.

The [domain pages](https://amasat01.github.io/hawk/content/domains.html) are that test. Each time one needed more than
the vocabulary had, the answer was a generic primitive every page now uses:

| Page | What it needed | The generic primitive |
|---|---|---|
| [Energy](https://amasat01.github.io/hawk/content/vocabulary/16_energy.html) | a Jacobian built and solved per lane | `m.mat` with per-lane `m.solve` |
| [Molecular dynamics](https://amasat01.github.io/hawk/content/vocabulary/22_molecular_dynamics.html) | gradients through nested loops | nested-loop differentiation |
| [Control](https://amasat01.github.io/hawk/content/vocabulary/21_control.html) | one plant across a grid of gains | [broadcasting](https://amasat01.github.io/hawk/content/broadcasting.html), at `k(...)` and at deploy |
| [Combustion](https://amasat01.github.io/hawk/content/vocabulary/13_combustion.html) | the ignition time recorded where a lane leaves its loop | `if c: <assignments>; break` |
| [Control](https://amasat01.github.io/hawk/content/vocabulary/21_control.html) | the settling time recorded where a lane leaves its loop | `if c: <assignments>; break` |
| [Particle physics](https://amasat01.github.io/hawk/content/vocabulary/17_particle_physics.html) | correlated draws | `m.mvn_sample` |
| [Linear algebra](https://amasat01.github.io/hawk/content/linear_algebra.html), n of 16 and up | products too wide to compile unrolled | the [rolled emit path](https://amasat01.github.io/hawk/content/emit_form.html) |

Domain-specific code added to the engine for these pages: none.

## Relationship with modern computing

Machine learning has demonstrated what becomes possible when algorithms, software abstractions and hardware are designed
together around modern accelerators. RAPTOR explores how analogous benefits can be made available to generic scientific
and engineering computing without requiring scientific workloads to adopt ML-shaped computational abstractions.

How we decide what goes in: [How we build](https://amasat01.github.io/raptor/content/principles.html).
