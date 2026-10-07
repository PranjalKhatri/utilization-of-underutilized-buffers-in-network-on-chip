# B.Tech Project Mid-Evaluation Report

The report source is `main.tex`.

The topology slide uses `config.system.ruby.dot.pdf`; the matching original
SVG is included as `config.system.ruby.dot.svg` for standalone display.
Both were copied from the validated 4x4, six-VC baseline run in
`PAPER_TESTS/o3_4x4_6vc_roi_20261005/corners-4x4-6vc/baseline/namd_m5out/`.

Before submission, replace `[Supervisor Name]` in `main.tex` and insert the
validated result plots/tables in Chapter 6.

Build on a machine with a TeX Live installation:

```bash
latexmk -pdf -interaction=nonstopmode main.tex
```

Alternatively:

```bash
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex
```

The second pass resolves the table of contents and cross-references.
