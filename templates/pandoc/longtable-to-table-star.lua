-- longtable-to-table-star.lua
--
-- Pandoc Lua filter that rewrites every Table AST node into a RawBlock
-- containing \begin{table*}\begin{tabular}...\end{tabular}\end{table*}
-- so it spans both columns under acl.sty/IEEEtran (where longtable
-- refuses to compile in 2-column mode).
--
-- The filter renders the table BODY through pandoc's built-in writer
-- and substitutes the longtable wrapper with a table* + tabular wrapper.
-- Pandoc emits TWO header sections in longtable form: the firsthead
-- (used on first occurrence) and the regular head (repeated on page
-- breaks). Tabular is single-page so we keep the firsthead and strip
-- the duplicate — otherwise the rendered PDF shows the header row
-- twice in a row, which is the historic "duplicated columns" bug.

function Table(tbl)
    local rendered = pandoc.write(pandoc.Pandoc({tbl}), "latex")

    -- The pandoc longtable layout is roughly:
    --   \toprule\noalign{}
    --   <firsthead row>\\
    --   \midrule\noalign{}
    --   \endfirsthead
    --   \toprule\noalign{}
    --   <repeat-head row — IDENTICAL to firsthead>\\
    --   \midrule\noalign{}
    --   \endhead
    --   <body rows>
    --   \bottomrule\noalign{}
    --   \end{longtable}
    --
    -- Strategy: drop everything from \endfirsthead through \endhead
    -- (inclusive). This removes the duplicate header block. If the
    -- firsthead/endhead structure isn't present (rare, table with no
    -- header), the substitution is a no-op.
    rendered = rendered:gsub("\\endfirsthead.-\\endhead", "")

    -- Strip any remaining longtable-only markers.
    rendered = rendered:gsub("\\endhead", "")
    rendered = rendered:gsub("\\endfirsthead", "")
    rendered = rendered:gsub("\\endfoot", "")
    rendered = rendered:gsub("\\endlastfoot", "")

    -- Replace the outer longtable environment with table* + tabular.
    rendered = rendered:gsub(
        "\\begin{longtable}%[%]{(.-)}",
        "\\begin{table*}[t]\\centering\\begin{tabular}{%1}"
    )
    rendered = rendered:gsub(
        "\\end{longtable}",
        "\\end{tabular}\\end{table*}"
    )

    return pandoc.RawBlock("latex", rendered)
end
