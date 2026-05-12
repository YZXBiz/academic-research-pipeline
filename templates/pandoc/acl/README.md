# Vendored ACL Style Files

These files are vendored verbatim from <https://github.com/acl-org/acl-style-files>
(commit on master at vendor time).

- `acl.sty` — *ACL conference paper style (2-column, 11pt article)
- `acl_natbib.bst` — natbib bibliography style for ACL (author-year, APA-like)

License: LaTeX Project Public License (LPPL).

Used by `compile_pdf_pandoc` in
`src/academic_pipeline/tools/rendering/latex_compiler.py` — both files are
copied into the per-build temp directory alongside `paper.md` so tectonic
can resolve `\usepackage{acl}` and `\bibliographystyle{acl_natbib}` from the
working directory.

To refresh: re-clone <https://github.com/acl-org/acl-style-files> and copy
the updated `acl.sty` / `acl_natbib.bst` into this folder.
