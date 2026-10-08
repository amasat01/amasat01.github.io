# Where RAPTOR fits

See which kinds of GPU problems RAPTOR makes easy, and when another tool is
the better choice — see the [front page](index.md) for the elevator pitch
and the headline numbers; this page is the longer story: where RAPTOR sits,
what it is not, and the same task in five tools, side by side.

## The four principles

1. **Efficient on the GPU.** Whole pipelines replay as **CUDA graphs** — a
   GPU's sequence of launches recorded once and replayed without
   re-issuing each one — so this class of problem makes full use of the
   hardware.
2. **Written at the level of your application.** A hawk **kernel** (a small
   GPU/CPU function, written once per sample) runs once per sample and
   declares, in its own signature, what each argument is
   (a per-sample state, a read-only table, an output); hawk works out the
   launch layout from that. CUDA C++, Warp, Numba and Triton still work
   right alongside it.
3. **Differentiable, forward and backward.** Every kernel's reverse- and forward-mode derivatives are generated from
   the same source and run on the GPU or the CPU like the kernel itself.
4. **Works with the code you already have.** Arrays cross without copies through DLPack (a standard, framework-neutral
   way for one library to hand another an array without copying it), and a compiled kernel
   deploys into any program that reads its manifest.

## The shape of it

```{image} _static/figures/where_raptor_fits_light.svg
:alt: A two-axis map. The horizontal axis is how you write the code, from whole-array operations to per-thread kernels to per-sample application code; the vertical axis is how independently each sample may branch or stop, from a lockstep batch to divergent, adaptive samples. Tensor frameworks and CuPy sit at the whole-array, lockstep corner and overlap each other. Warp sits toward per-thread kernels and spans toward divergent control. RAPTOR sits at per-sample application code and divergent, adaptive control, overlapping Warp.
:class: only-light
:width: 440px
```

```{image} _static/figures/where_raptor_fits_dark.svg
:alt: A two-axis map. The horizontal axis is how you write the code, from whole-array operations to per-thread kernels to per-sample application code; the vertical axis is how independently each sample may branch or stop, from a lockstep batch to divergent, adaptive samples. Tensor frameworks and CuPy sit at the whole-array, lockstep corner and overlap each other. Warp sits toward per-thread kernels and spans toward divergent control. RAPTOR sits at per-sample application code and divergent, adaptive control, overlapping Warp.
:class: only-dark
:width: 440px
```

*Tensor frameworks and CuPy write whole-array code for a lockstep batch; Warp and RAPTOR write closer to the
thread or the sample and let samples branch and stop independently — the overlaps are complementary, not a
ranking.*

```{image} _static/figures/stack_light.svg
:alt: A stack diagram. At the top, "you write" a hawk kernel in Python. Below it, eagle runs the kernel with launches, graphs and compaction, on CPU or GPU, and hawk kernels run through eagle. At the base are the two foundations, aether (a header-only C++23 numerics core that eagle builds on) and raptor (the dependency-free contracts foundation that both eagle and hawk declare). At the very bottom, "it runs on" CPU and GPUs.
:class: only-light
:width: 400px
```

```{image} _static/figures/stack_dark.svg
:alt: A stack diagram. At the top, "you write" a hawk kernel in Python. Below it, eagle runs the kernel with launches, graphs and compaction, on CPU or GPU, and hawk kernels run through eagle. At the base are the two foundations, aether (a header-only C++23 numerics core that eagle builds on) and raptor (the dependency-free contracts foundation that both eagle and hawk declare). At the very bottom, "it runs on" CPU and GPUs.
:class: only-dark
:width: 400px
```

*hawk is what you write; eagle runs it; aether and raptor are the two foundations underneath, and everything
ultimately runs on CPU or GPUs — arrows follow the real dependencies, including raptor declared directly by both
eagle and hawk.*

aether lays out arrays and provides the device-safe vector-algebra vocabulary; eagle launches and captures what
runs on top of it; raptor is the dependency-free foundation that defines the manifest and protocol contracts eagle and
hawk both build to without depending on each other; hawk authors and compiles the kernels eagle deploys. A neural
runtime built on this family is in development and not yet public.

## Why it matters: keeping the GPU busy

Per-sample work is a demanding pattern for any parallel machine, and the arithmetic is rarely the hard part. The
time tends to go to:

- **launch overhead**: one kernel launch per step, per stage, per sample group;
- **host round-trips**: the CPU checks "are we done yet?" between launches;
- **dead lanes**: in a vectorised batch, finished samples keep occupying the batch until the slowest one ends;
- **two codebases**: a GPU version and a CPU version that drift apart.

RAPTOR addresses each of these by construction:

- whole pipelines replay as captured CUDA graphs, removing the per-launch overhead;
- termination is decided on the device — each sample carries its own `terminated` flag and stops doing work once it's set, removing the host round-trip;
- a finished sample does no further work, and active-set compaction (packing the still-running samples together so finished ones stop occupying GPU lanes) keeps the live samples packed, removing the dead lanes;
- one source serves both machines, so there is no second codebase to drift.

The point is to bring this class of problems toward the efficiency the hardware already delivers on dense tensor work, measured
against the device's own peak.

### What happens to finished samples

A batch rarely finishes all at once: most samples stop at their own step, not the batch's last one. What happens to
a sample once it stops depends on how the loop is written. Masked array code keeps computing every sample every
step, finished ones included, because the array doesn't shrink. A hand-written per-thread kernel lets a finished
thread exit, but the threads around it are grouped into warps of 32, and a warp only finishes once its slowest
thread does — so an idle thread can still hold up its warp. eagle takes a third path: a finished sample leaves the
active set, and the next launch covers only the samples still running, so the batch's live set visibly shrinks as
samples finish.

```{image} _static/figures/finished_samples_light.svg
:alt: Three rows showing the same illustrative batch of 16 samples at four points in time. Masked array code keeps all 16 cells drawn every step, with finished samples shown faded and still occupying the batch. Per-thread kernel keeps all 16 cells drawn too, with finished samples shown as empty because the warp still waits for its slowest lane. Eagle with compaction shows fewer and fewer cells as samples finish, from 16 active at the start down to 4 active by the last snapshot.
:class: only-light
:width: 400px
```

```{image} _static/figures/finished_samples_dark.svg
:alt: Three rows showing the same illustrative batch of 16 samples at four points in time. Masked array code keeps all 16 cells drawn every step, with finished samples shown faded and still occupying the batch. Per-thread kernel keeps all 16 cells drawn too, with finished samples shown as empty because the warp still waits for its slowest lane. Eagle with compaction shows fewer and fewer cells as samples finish, from 16 active at the start down to 4 active by the last snapshot.
:class: only-dark
:width: 400px
```

*Illustration, not a measurement: a batch of 16 samples that stop at different steps, shown three ways.*

The [performance card](https://amasat01.github.io/eagle/content/performance.html) has the real numbers, at real
batch sizes, for the regime sketched above and several others — see
{ref}`Going deeper <going-deeper-optional>` below for the worked-through figures.

## What you write, side by side

```{image} _static/figures/what_you_write_light.svg
:alt: Two side-by-side columns for the same batch-of-trajectories task. Left, Warp: you write the thread program, a tiny wp.kernel with a per-thread while-loop and its own exit test, launched once over all threads. Right, RAPTOR: you write one step of one sample, a tiny hawk.kernel that writes the per-sample math and sets its own terminated flag, with eagle driving the repeated launches. Below each code sketch, a list of six run-time decisions -- the per-sample loop and exit, launch timing, compaction and reorder, graph capture, running on CPU and GPU, and derivatives -- each marked 'you' where the author writes it explicitly or 'engine' where eagle decides it at run time.
:class: only-light
:width: 600px
```

```{image} _static/figures/what_you_write_dark.svg
:alt: Two side-by-side columns for the same batch-of-trajectories task. Left, Warp: you write the thread program, a tiny wp.kernel with a per-thread while-loop and its own exit test, launched once over all threads. Right, RAPTOR: you write one step of one sample, a tiny hawk.kernel that writes the per-sample math and sets its own terminated flag, with eagle driving the repeated launches. Below each code sketch, a list of six run-time decisions -- the per-sample loop and exit, launch timing, compaction and reorder, graph capture, running on CPU and GPU, and derivatives -- each marked 'you' where the author writes it explicitly or 'engine' where eagle decides it at run time.
:class: only-dark
:width: 600px
```

*The same per-sample task written two ways: Warp's explicit thread program next to a RAPTOR (hawk) kernel for one sample, with the run-time decisions each leaves to the author and each hands to the engine.*

One level down, a kernel compiled elsewhere deploys through
`eagle.deploy(kernel)` (or `eagle.plan.auto`, the same function) and loads by its manifest through
`eagle.registry.load_manifest`. [Full, runnable notebook](https://amasat01.github.io/eagle/content/userguide/quickstart_python.html).

## What RAPTOR is for

- **Many small problems, one per thread.** Propagate ten thousand trajectories, integrate a batch of ODEs, step
  a population of agents. Each sample keeps its own state, takes its own branches and stops when it is done.
- **One source, two machines.** The same kernel compiles for a CUDA GPU or for CPU threads (parallelised with OpenMP,
  vectorised with SIMD — both standard ways to use multiple CPU cores and lanes at once). No second
  implementation to keep in sync, and the CPU build is the reference you test the GPU against.
- **Kernels written in Python, compiled to native code.** hawk traces a Python function into a **typed intermediate
  representation** (an internal, typed form of the code, not Python itself, that the compiler works from), derives
  its reverse- and forward-mode derivatives, and emits C++ for the GPU and the CPU.
- **Launch overhead taken off the table.** eagle captures whole pipelines as CUDA graphs and replays them, re-tuning
  **launch geometry** (how the work is split across GPU threads) between replays.
- **Contracts, not glue.** raptor's manifest describes what a compiled kernel computes and how to call it, so a kernel
  built once can be deployed into any host that speaks the contract.

## What RAPTOR is not

Not a deep-learning framework, not an autograd engine for whole programs, not a replacement for cuBLAS or cuDNN
(NVIDIA's own tuned dense-matrix and neural-network libraries) or any other tuned dense-tensor library. If your problem is one large dense tensor operation, the frameworks below will serve you
better, and RAPTOR will happily consume their output.

## Where we overlap, and what RAPTOR streamlines

Several jobs RAPTOR does are also done elsewhere. These are the ones where we think RAPTOR makes the path shorter
or clearer:

| You want to… | Common approaches | What RAPTOR adds |
|---|---|---|
| Write a custom GPU kernel from Python | write a CUDA C string for CuPy's `RawKernel`, a Numba CUDA kernel, a Triton kernel (GPU-focused), or an NVIDIA Warp kernel (one source for CPU and CUDA) | write a typed Python function once; hawk emits it for the GPU and the CPU, with per-sample state and termination declared in the signature |
| Differentiate a custom kernel | write the backward pass yourself (e.g. a `torch.autograd.Function` or `jax.custom_vjp`), or use NVIDIA Warp, which differentiates its kernels in reverse mode | hawk derives both reverse- and forward-mode derivatives of the kernel itself, as kernels you can run anywhere the **primal** (the original kernel) runs |
| Run a batch where each sample branches and stops early | vectorise with `vmap`/masks, so finished samples keep occupying the batch | each sample owns its state and a `terminated` flag; finished samples stop working |
| Run the same algorithm on CPU and GPU | keep two code paths or two programming models (Warp is a notable exception) | one source, two compile targets, same results to within floating point; the CPU build doubles as the reference you test the GPU against |
| Remove launch overhead from a pipeline | use each framework's own capture API (e.g. `torch.cuda.graph`, Warp's `ScopedCapture`) around the calls | eagle captures and replays the pipeline, with microsecond-class re-tuning of launch sizes between replays |
| Pass arrays between libraries | DLPack, with the stream ordering left to you | DLPack with an explicit stream contract, ownership and access flags, and a certified interop matrix |

(hawk-next-to-warp)=
## hawk next to Warp

Warp and hawk both turn Python functions into CPU and GPU kernels, and both differentiate them. Each offers its own
way of working:

- **Termination lives in the signature.** In hawk a sample's `terminated` flag is part of the kernel's declared
  vocabulary: the body writes the per-sample math, and finished samples stop committing results. In a
  thread-indexed kernel the same logic is explicit (a done flag, an early return, a guarded write-back), which gives
  full control over it; in hawk it follows from the signature.
- **Authoring by declaration, not by indexing.** A hawk kernel declares what each argument *is* (a per-sample
  state, a read-only table, a writable output, an accumulator), and hawk derives the indexing, the launch shape and
  the memory roles from those declarations.
- **Kernels compose.** **Kernel kinds** (named families of kernels that share a signature vocabulary) give a family
  of kernels a shared vocabulary; a kernel and its derived reverse- and forward-mode kernels are ordinary kernels
  you can deploy anywhere the **primal** (the original, undifferentiated kernel) runs; eagle captures several of
  them into one replayable graph; and raptor's manifest lets a compiled kernel be dropped into another program.

Warp is the better choice when you want its built-in geometry, mesh and simulation library, or reverse-mode
gradients of a whole simulation recorded on its **tape** (a runtime-recorded log of operations that a
reverse-mode pass replays backward). The two work together: arrays pass between them zero-copy in
both directions, with writes seen in the order they were issued — certified by three rows in
[raptor's interoperability matrix](https://amasat01.github.io/raptor/content/interop_protocols.html)
(`WP-IN-CUDA-ALIAS`, `WP-OUT-CUDA-ALIAS`, `STREAM-WARP-PRODUCER-ORDER` — the matrix names and defines what each row id
means). A side-by-side
notebook — the same per-sample problem, with early termination, written in both and executed on the GPU, with the
two results checked to agree — is
[`04_hawk_next_to_warp`](https://amasat01.github.io/hawk/content/examples/04_hawk_next_to_warp.html).

## When another tool is the better choice

| Tool | Choose it when… | Use it with RAPTOR by… |
|---|---|---|
| **numpy** | your data fits on the CPU and vectorised array code is fast enough | passing arrays in and out zero-copy (DLPack / array interface) |
| **CuPy** | you want numpy semantics on the GPU, or a hand-written CUDA kernel is fine | passing CuPy arrays zero-copy; RAPTOR kernels can run on CuPy's stream |
| **PyTorch** | you train neural networks or need its ecosystem of models and operators | handing tensors over DLPack; a RAPTOR kernel can feed or consume a torch model |
| **JAX** | you want whole-program transformations (`jit`, `grad`, `vmap`) over array code, compiled through XLA (Google's whole-program compiler) | exchanging arrays over DLPack (JAX support is on our roadmap; see below) |
| **TensorFlow / Keras** | you build and serve models in that ecosystem | exchanging tensors over DLPack (on our roadmap) |
| **Numba** | you want to JIT (just-in-time compile — turn a Python function into machine code the first time it runs) ordinary Python loops on the CPU, or write CUDA kernels in Python's CUDA dialect | either side can consume the other's arrays |
| **Triton** | you are writing high-performance dense GPU operators, especially for machine learning | composing at the array level |
| **Warp** | you want differentiable simulation kernels from Python for graphics, robotics or physics, with its rich built-in geometry and simulation library; it already offers one source for CPU and CUDA, reverse-mode kernel autodiff, CUDA-graph capture and DLPack | passing `wp.array`s zero-copy both ways; see {ref}`hawk-next-to-warp` for what each makes easier |

## How they combine

Arrays cross the boundary through **DLPack**, zero-copy, with explicit stream ordering: the producer's work is ordered
before the consumer's by a CUDA event, never by a device-wide synchronize. Every view reports who owns the memory,
which library produced it, and whether it may be written.

- **Supported today**: CuPy, PyTorch and Warp, certified row by row in raptor's interop matrix; numpy too,
  certified separately by an executable cuda-free dispatch test rather than a matrix row.
- **Foreseen** (same protocol, certification rows to come): JAX, TensorFlow/Keras and any other DLPack-capable library.

See [raptor's interoperability protocols](https://amasat01.github.io/raptor/content/interop_protocols.html) for the
full, cited statement of what is certified today versus foreseen, and
[eagle's interoperability contract](https://amasat01.github.io/eagle/content/interop_contract.html) for the stream and lifetime rules.

(going-deeper-optional)=
## Going deeper (optional)

The worked compaction numbers, and the same task written in five tools side by side — neither needed to follow the
page above.

### What compaction and `eagle.simulate` actually save

<!-- stale-prose-gate:
benchmarks/perf_card/card_quadro-p2000.json: d37837fb31567858848e5f1830f19431
-->

The [performance card](https://amasat01.github.io/eagle/content/performance.html) measures this on a development GPU
(Quadro P2000), one million samples integrated for up to 1000 steps.

On a batch where samples finish at different times:

- the compacted graph takes 415 ms, against 625 ms for the identical workload run without compaction — what
  compaction itself saves at fixed work;
- an occasional physical reorder layered on top, opt-in and triggered only once the live samples have thinned and
  scattered, cuts that further to 279 ms;
- `eagle.simulate` — the policy that picks between these approaches at run time, so nobody has to choose by hand —
  reaches 156 ms on this same batch, ahead of NVIDIA Warp (609 ms), JAX (1.36 s), CuPy (7.38 s) and PyTorch (7.4 s)
  on this card.

On a batch where every sample runs the full 1000 steps instead, there is nothing to compact, and the plain graph is
the better fit: 703 ms against 862 ms for the compacted graph, whose periodic active-set scan runs with no idle
lanes left to recover. NVIDIA Warp's per-thread kernel and `eagle.simulate` tie here (693 ms and 699 ms), and the two are level at N = 10,000
(7.22 ms against 7.22 ms) — worth knowing about. The card also lists the regimes where another approach
is the better fit: on this FP64-weak development card the 8-thread CPU build is faster than every GPU arm on the dense
batch (191 ms against 699 ms), and the same computation written as masked CuPy array code is the better fit when
array-style code matters more than wall time.

(same-task-five-ways)=
### Same task, five ways

```{include} _generated/same_task_full.md
```
