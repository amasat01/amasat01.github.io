# Building from source

**Build every library of the family yourself, in one prefix.** This page is for contributors, for C++ users who
link `aether::aether` or `eagle::eagle` directly, and for platforms where you want to control the toolchain. The everyday install is `pip` from PyPI; the {ref}`Install <install>` section on the landing page is the short version
and this page is the secondary, from-source route.

## Prerequisites

Every command below installs into one prefix, `${CONDA_PREFIX}` if you use conda (the repos' own docs call this
`PREFIX` — substitute your own install directory everywhere below if you don't use conda).

| Tool | Requirement | Notes |
|---|---|---|
| CMake | ≥ 3.20 | aether, eagle |
| C++ compiler | C++23 — GCC ≥ 12 or Clang ≥ 16 | aether, eagle; stated identically by both |
| CUDA toolkit | CUDA 12.6 or newer (tested with 12.6 and 13.0) | Optional — build with `AETHER_CPP_MODE=ON` / `EAGLE_CPP_MODE=ON` and the libraries run on GPUs or on CPU threads (OpenMP) from the same source. eagle's Python package is always a CUDA build (see Pitfalls). |
| nvcc host-compiler ceiling | GCC 13 for CUDA 12.6 | nvcc accepts a host compiler only up to its own ceiling; pass `-DCMAKE_CUDA_HOST_COMPILER=<g++-13>` if your default compiler is newer |
| Python | ≥ 3.9 for raptor and aether-dsc; ≥ 3.10 for hawk and eagle | hawk and eagle are tested on CPython 3.10–3.13 |

## Install, in dependency order

Clone the four repositories next to each other:

```text
raptor-family/
├── aether/
├── eagle/
├── hawk/
└── raptor/
```

### 1. aether (C++)

```bash
git clone https://github.com/amasat01/aether.git
cd aether

# CUDA mode
cmake -DCMAKE_PREFIX_PATH=${CONDA_PREFIX} -DAETHER_BUILD_TESTS=ON -B build .
# CPU-only mode (no CUDA toolchain needed) — use this instead of the line above:
# cmake -DCMAKE_PREFIX_PATH=${CONDA_PREFIX} -DAETHER_CPP_MODE=ON -DAETHER_BUILD_TESTS=ON -B build .

cmake --build build
cmake --install build --prefix ${CONDA_PREFIX}
cd ..
```

### 2. eagle (C++, then the Python package)

eagle depends only on aether, which must already be installed into the same prefix.

```bash
git clone https://github.com/amasat01/eagle.git
cd eagle

# CUDA/C++ mode, with tests
cmake -DCMAKE_PREFIX_PATH=${CONDA_PREFIX} -DEAGLE_BUILD_TESTS=ON -B build .
# CPU-only mode — needs an AETHER_CPP_MODE aether install (use this instead of the line above):
# cmake -DCMAKE_PREFIX_PATH=${CONDA_PREFIX} -DEAGLE_CPP_MODE=ON -DEAGLE_BUILD_TESTS=ON -B build .

cmake --build build
cmake --install build --prefix ${CONDA_PREFIX}
```

The Python package (`raptor-eagle`, imported as `eagle`) wraps a compiled extension that is always built as CUDA
code — it needs `nvcc` even on a machine without a GPU — and needs aether installed in CUDA mode plus eagle's own
headers, both in the same prefix. It also depends on raptor, installed from a checkout next to this one:

```bash
cmake -DCMAKE_PREFIX_PATH=${CONDA_PREFIX} -B build-hdr . && cmake --install build-hdr --prefix ${CONDA_PREFIX}
pip install ../raptor
export CMAKE_PREFIX_PATH=${CONDA_PREFIX}
# append ;-DCMAKE_CUDA_HOST_COMPILER=<g++-13> if your default compiler is newer than nvcc accepts
export SKBUILD_CMAKE_ARGS="-DCMAKE_CUDA_ARCHITECTURES=<your GPU's arch, e.g. 70>"
pip install -e ./python
cd ..
```

### 3. aether-dsc

`aether-dsc` ships a sealed copy of aether's own headers for Python-only consumers — hawk's device compiler is the
primary one. No CUDA toolchain is needed to install it.

```bash
cd aether
pip install ./dsc
cd ..
```

### 4. hawk

hawk's compiled half (`hawk._core`) resolves the aether/eagle C++ header roots from the sibling checkouts above
(or from `$HAWK_AETHER_INCLUDE` / `$HAWK_EAGLE_INCLUDE` if they live elsewhere). aether-dsc (step 3) must already
be installed. A GPU is optional — required only to compile and run a kernel's device target, not to author one or
run the host path:

```bash
git clone https://github.com/amasat01/hawk.git
cd hawk
pip install -e .[test]
cd ..
```

### 5. raptor

raptor is pure Python with zero hard dependencies — no GPU, no CUDA toolkit, no C or C++ compiler needed.

```bash
cd raptor
pip install -e .
# the `demo` extra pulls in numpy and torch, needed only to run raptor's own examples:
# pip install -e .[demo]
cd ..
```

## Check it worked

```bash
python -c "import aether_dsc; print(aether_dsc.version)"
python -c "import eagle; print(eagle.ABI_VERSION)"
python -c "import hawk; print(hawk.__version__)"
python -c "import raptor; print(raptor.__version__)"
```

None of the four need a GPU to import. hawk additionally reports, with no GPU required to call it, what its device
compiler path can see on the current machine:

```python
from hawk.compile import cubin_available
cubin_available()   # NVRTC importable and a CUDA device present
```

aether has no Python import of its own; verify it by running its test-integrity gate (built with
`AETHER_BUILD_TESTS=ON` above) — run the gate script directly, never the test binary bare:

```bash
aether/tests/check_gate.sh cpp aether/build/tests/aether_tests   # or: cuda, for a CUDA-mode build
```

## Pitfalls

- **nvcc rejects your host compiler.** nvcc accepts host compilers only up to its own ceiling (GCC 13 for CUDA
  12.6). Fix: `-DCMAKE_CUDA_HOST_COMPILER=<g++-13>` on the CMake configure line (or appended to
  `SKBUILD_CMAKE_ARGS` for eagle's Python package).
- **Edited a source file, forgot to rebuild.** `import hawk` refuses a `hawk._core` whose build digest disagrees
  with the sources beside it, naming both digests and the loaded binding's path. Fix: `pip install -e .
  --no-build-isolation --no-deps` (from hawk's checkout), or check for an older hawk earlier on `sys.path`
  shadowing this one.
- **Mixed prefixes.** eagle must be installed into the *same* prefix as aether (`find_package` resolves against
  `CMAKE_PREFIX_PATH`/`CMAKE_INSTALL_PREFIX`). Fix: use one `${CONDA_PREFIX}` for every `cmake --install` and
  `pip install` step above.

## Details

Each repository documents its own build in full — CMake option references, debug builds, every test tier:

- [aether installation](https://amasat01.github.io/aether/content/installation.html)
- [eagle installation](https://amasat01.github.io/eagle/content/userguide/installation.html) and
  [build options](https://amasat01.github.io/eagle/content/userguide/build_options.html)
- [hawk installation](https://amasat01.github.io/hawk/content/installation.html)
- [raptor installation](https://amasat01.github.io/raptor/content/installation.html)
