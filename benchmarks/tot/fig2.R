rm(list = ls())

library(tidyverse)
library(ggplot2)
library(cowplot)

setwd("/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST")

d_flow_svg <- "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/agent_architecture/4.search_literature_dynamic_compact.svg"
e_flow_svg <- "/Users/jungj2/Dropbox/Metadata/mcp/sgcp-rag/docs/main_sgcp_rag_flow.svg"
fig2_layout_svg <- "benchmarks/tot/fig2_layout.svg"
fig2_base_svg <- "benchmarks/tot/fig2_base.svg"
fig2_out_svg <- "benchmarks/tot/fig2.svg"
fig2_out_png <- "benchmarks/tot/fig2.png"

d0 <- ggdraw()
d <- readRDS('benchmarks/tot/fig2d.rds')

e0 <- ggdraw()
e <- readRDS('benchmarks/tot/fig2e.rds')

dd <- plot_grid(d0, d,
  rel_heights = c(0.65, 0.35),
  nrow=2
)
dd


ee <- plot_grid(e0, e,
  rel_heights = c(0.65, 0.35),
  nrow=2
)
ee

de <- plot_grid(dd, ee,
  align = "hv",
  labels = c("A", "B"),
  rel_widths = c(0.5, 0.5),
  nrow = 1
)
de
ggsave(fig2_layout_svg, de, width = 10, height = 12, bg = "white")

compose_status <- system2(
  "python3",
  c(
    "benchmarks/tot/compose_fig2_mermaid_svg.py",
    fig2_layout_svg,
    d_flow_svg,
    e_flow_svg,
    fig2_base_svg
  )
)
if (!identical(compose_status, 0L)) {
  stop("Failed to compose Mermaid SVG into fig2_base.svg", call. = FALSE)
}

file.copy(fig2_base_svg, fig2_out_svg, overwrite = TRUE)

png_status <- system2("rsvg-convert", c(fig2_out_svg, "-o", fig2_out_png))
if (!identical(png_status, 0L)) {
  stop("Failed to render fig2.svg to fig2.png", call. = FALSE)
}
