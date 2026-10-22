# How the family fits together

**Four libraries, one direction of dependency, two things that cross between them.** This page is a map. Each "how does it work" question below links to the repository that owns the answer, so nothing is explained twice.

```{raw} html
:file: _static/ecosystem/ecosystem_cards_family.html
```

## The four libraries

- **aether** lays out arrays in C++ and runs the same code on GPU threads or CPU threads.
- **eagle** launches kernels, records them into CUDA graphs and replays them, and loads compiled kernels through a plugin registry.
- **hawk** is where you write the per-sample kernel in Python; it differentiates it, generates the code and compiles it.
- **raptor** holds the shared contracts: the manifest schema, the engine and provider protocols and the interop certification matrix. It depends on none of the others.

Dependencies point one way. eagle and hawk build on aether's arrays and on raptor's contracts, and raptor never imports them. Each library works alone; a companion adds speed, derivatives or a deployment route.

## What crosses between them

**Files.** hawk compiles a kernel and writes a manifest and a sidecar next to it; eagle reads them and launches the kernel. Neither imports the other for this: both follow raptor's schema.

**Buffers.** Arrays cross by DLPack, the standard way for one library to hand another an array without copying it. That is how a kernel runs inside a JAX, PyTorch, Warp or CuPy program, and how your code runs as a step in an eagle batch.

## Where each question is answered

| You want to know | Read | Repository |
|---|---|---|
| How to add a native math function | [Add a native function](https://amasat01.github.io/hawk/content/contributing/add_a_native_function.html) | hawk |
| How a graph is recorded, instantiated and replayed | [Capture and replay](https://amasat01.github.io/eagle/content/devguide/graph_capture_replay.html) | eagle |
| How eagle is built, tested and organised | [Developer guide](https://amasat01.github.io/eagle/content/devguide/dev_guide.html) | eagle |
| What the manifest and sidecar contain | [Plugin schema](https://amasat01.github.io/raptor/content/devguide/plugin_schema.html) | raptor |
| What each contract pins, and which test | [Concepts](https://amasat01.github.io/raptor/content/concepts.html) | raptor |
| How an interop crossing is certified | [Contributing a certification row](https://amasat01.github.io/raptor/content/devguide/contributing_a_certification_row.html) | raptor |

<!-- add: hawk contributing chapters once they land -->

To build all four from source, see [Building from source](build_from_source.md). To contribute, start at the repository's own Contributing page: [eagle](https://amasat01.github.io/eagle/content/contributing.html), [hawk](https://amasat01.github.io/hawk/content/contributing.html), [raptor](https://amasat01.github.io/raptor/content/contributing.html) or [aether](https://amasat01.github.io/aether/).
