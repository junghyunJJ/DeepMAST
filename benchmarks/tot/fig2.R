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

a <- readRDS('benchmarks/tot/fig2ab.rds')[[1]]
b <- readRDS('benchmarks/tot/fig2ab.rds')[[2]]
c <- readRDS('benchmarks/tot/fig2c.rds')

d0 <- ggdraw()
d <- readRDS('benchmarks/tot/fig2d.rds')

e0 <- ggdraw()
e <- readRDS('benchmarks/tot/fig2e.rds')


abc <- plot_grid(a, b, c,
  align = "hv",
  labels = c("A", "", "B"),
  rel_widths = c(0.4, 0.4, 0.2),
  nrow = 1
)
abc

dd <- plot_grid(d0, d,
  rel_heights = c(0.60, 0.40),
  nrow=2
)
dd


ee <- plot_grid(e0, e,
  rel_heights = c(0.60, 0.40),
  nrow=2
)
ee

de <- plot_grid(dd, ee,
  align = "hv",
  labels = c("C", "D"),
  rel_widths = c(0.5, 0.5),
  nrow = 1
)
de


fig2 <- plot_grid(abc, de,
  align = "hv",
  rel_heights = c(0.3, 0.7),
  nrow = 2
)
ggsave(fig2_layout_svg, fig2, width = 14, height = 18, bg = "white")

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

s_a <- readRDS('benchmarks/tot/sfig2c.rds')
s_d <- readRDS('benchmarks/tot/sfig2d.rds')

sfig2 <- plot_grid(s_a, s_d,
  align = "v",
  rel_widths = c(0.6, 0.3),
  labels = c("", "C"),
  nrow = 1
)
ggsave('benchmarks/tot/sfig2.svg', sfig2, width = 14, height = 4, bg = "white")
