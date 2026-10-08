# About

**Author:** Alessandro Masat.

The RAPTOR family exists to make GPU numerics — kernels, graph capture,
automatic differentiation, zero-copy array exchange — accessible on modest
and edge hardware, for research and education, without forcing a choice
between writing a kernel once and running it on CPU threads when a GPU
isn't there. Four libraries split that problem cleanly: aether lays out the
arrays, eagle launches and captures what runs on them, raptor is the
dependency-free spine that lets a kernel producer and an executor agree
without depending on each other, and hawk authors and compiles the kernels.
Each works alone; adding a companion buys speed or a deployment option,
never a capability class.

**Contact:** via GitHub — [github.com/amasat01](https://github.com/amasat01).
If you want to build on this, or apply these ideas to a new problem, get in
touch: collaboration is the point, and a citation is the currency.
