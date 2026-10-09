# RAPTOR

```{raw} html
<header class="rpt-bar">
  <a class="rpt-brand" href="#"><img src="_static/brand/family_raptor.svg" alt=""><span>RAPTOR</span></a>
  <nav aria-label="Main"><a href="start_here.html">Start here</a><a href="https://amasat01.github.io/eagle/">Docs</a><a href="compare.html">Compare</a><a href="https://github.com/amasat01">GitHub</a>
  <script>
  document.write(`
    <button class="btn btn-sm nav-link pst-navbar-icon theme-switch-button rpt-theme-toggle" title="light/dark" aria-label="light/dark" data-bs-placement="bottom" data-bs-toggle="tooltip">
      <i class="theme-switch fa-solid fa-sun fa-lg" data-mode="light"></i>
      <i class="theme-switch fa-solid fa-moon fa-lg" data-mode="dark"></i>
      <i class="theme-switch fa-solid fa-circle-half-stroke fa-lg" data-mode="auto"></i>
    </button>
  `);
  </script>
  </nav>
</header>
<div class="rpt-hero">
  <h1><span>Write the code for one sample.</span> <span>Run a million of them.</span></h1>
</div>
```

```{include} _generated/lead_sentence.md
```

```{raw} html
<div class="rpt-actions" id="start">
  <a class="btn" href="start_here.html">Start here</a>
  <a class="quiet" href="https://amasat01.github.io/raptor_start_here.ipynb" download>Download the notebook</a>
  <a class="quiet" href="https://colab.research.google.com/github/amasat01/amasat01.github.io/blob/main/notebooks/raptor_start_here.ipynb">Open in Colab</a>
  <code>pip install "raptor-hawk[cuda12]" "raptor-eagle[cuda12]"</code>
</div>
```

```{raw} html
<figure class="rpt-thread">
  <svg id="thread" role="img" aria-label="One ink stroke splits into many thin lines, one per sample; each line stops at its own length and ends in a drop, and most stop early."></svg>
  <figcaption>Each line is a sample; each drop is where it finished.</figcaption>
</figure>
<script>RaptorThread.mount(document.getElementById("thread"), { desktopSamples: 150, phoneSamples: 60, seed: 20261001 });</script>
```

(what-you-write)=
## What you write

::::{grid} 1 1 2 2
:gutter: 3
:class-container: rpt-pair

:::{grid-item}
:columns: 12 12 8 8
```python
import cupy as cp

import eagle
import hawk
from hawk import Mutable, Param, Scalar, Terminated


@hawk.kernel
def oscillator(
    omega: Scalar, t_end: Param, dt: Param,
    terminated: Terminated,
    x: Mutable[Scalar], v: Mutable[Scalar],
    t: Mutable[Scalar],
):
    x, v = x + dt * v, v - dt * omega * omega * x
    t += dt
    terminated = t >= t_end


n = 1_000_000
result = eagle.simulate(
    oscillator,
    omega=cp.linspace(1.0, 3.0, n), t_end=1.0, dt=1e-3,
    x=cp.ones(n), v=cp.zeros(n), t=cp.zeros(n),
    max_steps=10_000,
)
print(result.status, result.steps, result.x[:3])
# needs a GPU to run (1,000,000 cupy samples); the output is not shown here
```
:::

:::{grid-item}
:columns: 12 12 4 4
### What happened

Pass the kernel's arguments as you would call it; give an array where each sample has its own value.

eagle captured the step loop as a CUDA graph and replayed it on the GPU, so one call did all the launching.

Samples that finished were dropped from the next launch, so the batch shrank as it ran.

Pass NumPy arrays instead of CuPy and the same call runs on your CPU threads.
:::
::::

(how-it-compares)=
## How it compares

```{include} _generated/compare_time_chart.md
```

```{raw} html
<div class="rpt-mem-chart">
<h4>Memory, as a multiple of what the samples need</h4>
</div>
```

```{include} _generated/compare_memory_chart.md
```

```{include} _generated/landing_honest.md
```

````{dropdown} Full numbers, every arm
```{include} _generated/why_raptor.md
```
````

## Four libraries

```{raw} html
:file: _static/ecosystem/ecosystem_cards_family.html
```

(install)=
````{dropdown} Install
```bash
pip install raptor-core                                     # the protocol spine: Python 3.9+, no dependencies
pip install raptor-hawk                                     # hawk, CPU only (Linux x86_64, CPython 3.9-3.14, host g++ 11+)
pip install "raptor-hawk[cuda12]" "raptor-eagle[cuda12]"    # GPU route; use [cuda13] on both for CUDA 13
```

```{important}
**NVIDIA's GPU packages come only through the extras.** `raptor-hawk[cuda12]` pulls `cuda-bindings` 12,
`nvidia-cuda-nvrtc-cu12` and `nvidia-cuda-cccl-cu12`; `raptor-hawk[cuda13]` pulls `cuda-bindings` 13,
`nvidia-cuda-nvrtc` 13 and `nvidia-cuda-cccl` 13 (CUDA 13's wheels have no `-cu13` suffix);
`raptor-eagle[cuda12]` / `[cuda13]` pull CuPy (`cupy-cuda12x` / `cupy-cuda13x`, with the CUDA headers CuPy compiles against). Without an extra pip installs no NVIDIA package: you get the CPU route, or the GPU route through a CUDA setup you already have. Pick the extra matching the CUDA version your driver reports (`nvidia-smi`, top right). No `nvcc` or CUDA
toolkit is needed.
```

**Platforms:** built and tested on Linux x86_64 only so far (CPython 3.9–3.14, including free-threaded 3.13t and 3.14t), on NVIDIA GPUs from Pascal (Quadro P2000) and Turing (Tesla T4). There are no wheels for macOS, Windows or ARM yet, and WSL2 is untested. `raptor-core` and `aether-dsc` are pure Python and install anywhere. Free-threaded builds (3.13t, 3.14t) currently re-enable the GIL when `hawk` or `eagle` is imported and print a RuntimeWarning; results are correct, just not parallel.

`raptor-hawk` pulls `aether-dsc` (the sealed C++ headers hawk compiles against) automatically. eagle alone:
`pip install "raptor-eagle[cuda12]"` (`[torch]` adds PyTorch interop); its wheel ships GPU code for Pascal, Volta,
Ampere and Hopper (sm_61/70/80/90) plus PTX for newer GPUs. aether is a header-only C++ library used through CMake;
`aether-dsc` on PyPI is not something C++ users install. To build everything from source (contributors, C++ users,
your own toolchain), see [Building from source](build_from_source.md).
````

````{dropdown} Citing
Each repository is cited independently: its own `CITATION.cff` carries the metadata (GitHub shows it under "Cite
this repository"), and every tagged release is archived on Zenodo: hawk [doi:10.5281/zenodo.23250242](https://doi.org/10.5281/zenodo.23250242), eagle [doi:10.5281/zenodo.23250240](https://doi.org/10.5281/zenodo.23250240), aether [doi:10.5281/zenodo.23250238](https://doi.org/10.5281/zenodo.23250238), raptor [doi:10.5281/zenodo.23250234](https://doi.org/10.5281/zenodo.23250234).
````

````{dropdown} License
All four repositories — aether, raptor, eagle and hawk — are licensed under the Apache License, Version 2.0: free
for any use, commercial or not, with attribution. See each repository's own `LICENSE` for the full text.
````

```{raw} html
<div class="rpt-footer">Apache-2.0. <a href="https://github.com/amasat01">GitHub</a>.</div>
```

```{toctree}
:maxdepth: 1
:hidden:

start_here
where_raptor_fits
compare
build_from_source
about
```
