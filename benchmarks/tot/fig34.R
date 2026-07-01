rm(list = ls())

library(tidyverse)
library(ggplot2)
library(cowplot)

setwd("/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST")

figs3b <- readRDS('benchmarks/tot/fig2c.rds')

figs3c <- readRDS("benchmarks/tot/fig3a.rds")
figs3d <- readRDS("benchmarks/tot/fig3b.rds")
figs3c <- figs3c + theme(axis.text.x = element_text(angle = 45, hjust = 1))
figs3d <- figs3d + theme(axis.text.x = element_text(angle = 45, hjust = 1))

fig3_2 <- plot_grid(figs3b, figs3c, figs3d,
                     align = "h",
                     # rel_widths = c(0.6, 0.3),
                     labels = c("B", "C", ""),
                     nrow = 1
)
fig3_2
ggsave('benchmarks/tot/fig3_2.svg', fig3_2, width = 6, height = 4, bg = "white")


##################################################


figs3a <- readRDS("benchmarks/tot/sfig2c.rds")
figs3b <- readRDS("benchmarks/tot/sfig2d.rds")
figs3c <- readRDS("benchmarks/tot/figs3d.rds")
figs3d <- readRDS("benchmarks/tot/figs3e.rds")

sfig3_1 <- plot_grid(figs3b, figs3a,
                   align = "vh",
                   axis = "b",
                   rel_widths = c(0.4, 0.6),
                   labels = c("A", "B"),
                   nrow = 1
)
sfig3_1
ggsave('benchmarks/tot/sfig3_1.svg', sfig3_1, width = 15, height = 4.5, bg = "white")

sfig3_2 <- plot_grid(figs3c, figs3d,
                   align = "v",
                   # rel_widths = c(0.6, 0.3),
                   labels = c("C", "D"),
                   nrow = 1
)
sfig3_2
ggsave('benchmarks/tot/sfig3_2.svg', sfig3_2, width = 10, height = 4, bg = "white")

