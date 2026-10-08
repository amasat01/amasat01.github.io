# amasat01.github.io

Source for the RAPTOR family landing site, published at
<https://amasat01.github.io/>. A GitHub user site: a single Sphinx page
(`index.md`) introducing the family — [aether](https://github.com/amasat01/aether),
[raptor](https://github.com/amasat01/raptor), [eagle](https://github.com/amasat01/eagle)
and [hawk](https://github.com/amasat01/hawk) — plus a short `about.md`.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="_static/ecosystem/ecosystem_family_dark.svg">
    <img src="_static/ecosystem/ecosystem_family_light.svg" alt="The RAPTOR family: hawk (write it), eagle (run it), aether (the C++/CUDA numerics underneath) and raptor (the shared contract)." width="760">
  </picture>
</p>

<p align="center">

[aether](https://amasat01.github.io/aether/) · [hawk](https://amasat01.github.io/hawk/) · [eagle](https://amasat01.github.io/eagle/) · [raptor](https://amasat01.github.io/raptor/) · [the family](https://amasat01.github.io/)

</p>

## Build

```bash
pip install -r requirements.txt
make html       # build into _build/html
make strict     # same, with warnings promoted to errors
make linkcheck  # verify every external link
```

`.github/workflows/pages.yml` runs `make strict` and deploys `_build/html`
to GitHub Pages on every push to `main`.

## License

Licensed under the Apache License, Version 2.0: free for any use,
commercial or not, with attribution. See `LICENSE` for the full text.

Copyright 2026 Alessandro Masat.
