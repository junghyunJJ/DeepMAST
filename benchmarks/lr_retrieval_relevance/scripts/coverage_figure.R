rm(list = ls())

## Retrieval coverage figure (skill ON vs OFF), qwen3.5:122b LLM coverage.
## Reads CSVs from export_coverage_figure_data.py; writes SVG + PNG.

suppressPackageStartupMessages({
  library(tidyverse)
  library(svglite)
})

args <- commandArgs(trailingOnly = TRUE)
results_dir <- if (length(args) >= 1) args[[1]] else
  "docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live_thinkfalse"

tdir <- file.path(results_dir, "manuscript", "tables")
fdir <- file.path(results_dir, "manuscript", "figures")
dir.create(fdir, recursive = TRUE, showWarnings = FALSE)

if (!file.exists(file.path(tdir, "coverage_group_summary.csv"))) {
  fallback_tdir <- file.path(results_dir, "coverage_tables")
  if (file.exists(file.path(fallback_tdir, "coverage_group_summary.csv"))) {
    tdir <- fallback_tdir
  }
}

summary_df <- read_csv(file.path(tdir, "coverage_group_summary.csv"), show_col_types = FALSE)
sig_df     <- read_csv(file.path(tdir, "coverage_sig.csv"), show_col_types = FALSE)

set_levels <- c(raw = "All retrieved papers", filtered = "Citable set (direct + context)")
strength_levels <- c(weak = "Weak model (qwen3.5:35b)", strong = "Strong model (qwen3.5:122b)")
metric_levels <- c(genes = "Genes\n(LR pair)", pathways = "Pathways", celltypes = "Cell types")
arm_levels <- c(ON = "Skill ON", OFF = "Skill OFF")

prep <- function(df) {
  df %>%
    mutate(
      set = factor(set_levels[set], levels = set_levels),
      strength = factor(strength_levels[strength], levels = strength_levels),
      metric = factor(metric_levels[metric], levels = metric_levels)
    )
}

summary_df <- summary_df %>%
  mutate(arm = factor(arm_levels[arm], levels = arm_levels)) %>%
  prep()

## Per-strength labels (matches facets), placed above each ON/OFF pair.
sig_pos <- sig_df %>%
  filter(strength %in% c("strong", "weak")) %>%
  prep() %>%
  left_join(
    summary_df %>% group_by(set, strength, metric) %>% summarise(top = max(ci_hi), .groups = "drop"),
    by = c("set", "strength", "metric")
  ) %>%
  filter(sig != "ns") %>%
  mutate(
    metric_index = as.numeric(metric),
    bracket_y = pmin(top + 6, 108),
    star_y = bracket_y + 2.5,
    tick_y = bracket_y - 1.5,
    xmin = metric_index - 0.225,
    xmax = metric_index + 0.225,
    label = "***"
  )

dodge <- position_dodge(width = 0.78)

add_sig_brackets <- function(plot_obj, sig_data) {
  plot_obj +
    geom_segment(
      data = sig_data,
      aes(x = xmin, xend = xmax, y = bracket_y, yend = bracket_y),
      inherit.aes = FALSE,
      linewidth = 0.55,
      colour = "black"
    ) +
    geom_segment(
      data = sig_data,
      aes(x = xmin, xend = xmin, y = tick_y, yend = bracket_y),
      inherit.aes = FALSE,
      linewidth = 0.55,
      colour = "black"
    ) +
    geom_segment(
      data = sig_data,
      aes(x = xmax, xend = xmax, y = tick_y, yend = bracket_y),
      inherit.aes = FALSE,
      linewidth = 0.55,
      colour = "black"
    ) +
    geom_text(
      data = sig_data,
      inherit.aes = FALSE,
      aes(x = metric_index, y = star_y, label = label),
      size = 3.4,
      colour = "black"
    )
}

p <- ggplot(summary_df, aes(x = metric, y = mean, fill = arm)) +
  # geom_col(position = dodge, width = 0.72, colour = "black", linewidth = 0.35, alpha = 0.86) +
  geom_bar(stat = "identity",  position = dodge, width = 0.7, color = "black", alpha = 0.8, linewidth = 0.4) +
  geom_errorbar(aes(ymin = ci_lo, ymax = ci_hi), position = dodge, width = 0.18,
                linewidth = 0.45, colour = "black") +
  facet_grid(set ~ strength) +
  scale_fill_manual(values = c("Skill ON" = "darkgreen", "Skill OFF" = "grey60"), name = NULL) +
  scale_y_continuous(limits = c(0, 116), breaks = seq(0, 100, 25), expand = expansion(mult = c(0, 0))) +
  labs(
    x = NULL,
    y = "Coverage of case entities (%)"
  ) +
  theme_bw(base_size = 12) +
  theme(
    plot.title = element_blank(),
    plot.subtitle = element_blank(),
    plot.caption = element_blank(),
    panel.border = element_rect(colour = "grey20", fill = NA, linewidth = 0.55),
    panel.grid.major = element_line(colour = "grey90", linewidth = 0.45),
    panel.grid.minor = element_line(colour = "grey94", linewidth = 0.25),
    strip.background = element_rect(fill = "white", colour = NA),
    strip.text = element_text(face = "bold", size = 9.5),
    legend.position = c(0.985, 0.985),
    legend.justification = c(1, 1),
    legend.background = element_rect(fill = "white", colour = "black", linewidth = 0.45),
    legend.key = element_rect(fill = "white", colour = NA),
    legend.margin = margin(4, 6, 4, 6),
    legend.text = element_text(size = 8.8),
    axis.title.y = element_text(size = 12, colour = "black"),
    axis.text.x = element_text(size = 8.6, colour = "black"),
    axis.text.y = element_text(size = 9.5, colour = "black")
  )
p <- add_sig_brackets(p, sig_pos)
p

svg_path <- file.path(fdir, "fig_retrieval_coverage.svg")
png_path <- file.path(fdir, "fig_retrieval_coverage.png")
ggsave(svg_path, p, width = 8.6, height = 6.4, units = "in")
ggsave(png_path, p, width = 8.6, height = 6.4, units = "in", dpi = 200)

summary_figure2d <- summary_df %>%
  filter(
    set == set_levels[["filtered"]]
  )

sig_pos_figure2d <- sig_pos %>%
  filter(
    set == set_levels[["filtered"]]
  )

p_figure2d <- ggplot(summary_figure2d, aes(x = metric, y = mean, fill = arm)) +
  geom_col(position = dodge, width = 0.72, colour = "black", linewidth = 0.35, alpha = 0.86) +
  geom_errorbar(aes(ymin = ci_lo, ymax = ci_hi), position = dodge, width = 0.18,
                linewidth = 0.45, colour = "black") +
  facet_grid(. ~ strength) +
  scale_fill_manual(values = c("Skill ON" = "darkgreen", "Skill OFF" = "grey60"), name = NULL) +
  scale_y_continuous(limits = c(0, 116), breaks = seq(0, 100, 25), expand = expansion(mult = c(0, 0))) +
  labs(
    x = NULL,
    y = "Coverage of case entities (%)"
  ) +
  theme_bw() +
  theme(
    # plot.title = element_blank(),
    # plot.subtitle = element_blank(),
    # plot.caption = element_blank(),
    # panel.border = element_rect(colour = "grey20", fill = NA, linewidth = 0.55),
    # panel.grid.major = element_line(colour = "grey90", linewidth = 0.45),
    # panel.grid.minor = element_line(colour = "grey94", linewidth = 0.25),
    strip.background = element_rect(fill = "white", colour = NA),
    strip.text = element_text(face = "bold"),
    legend.position = c(0.985, 0.985),
    legend.justification = c(1, 1),
    legend.background = element_rect(fill = "white", colour = "black", linewidth = 0.3),
    legend.key = element_rect(fill = "white", colour = NA),
    legend.margin = margin(4, 6, 4, 6),
    legend.text = element_text(colour = "black")
    # ,
    # legend.text = element_text(size = 8.8),
    # axis.title.y = element_text(size = 12, colour = "black"),
    # axis.text.x = element_text(size = 8.6, colour = "black"),
    # axis.text.y = element_text(size = 9.5, colour = "black")
  )
p_figure2d <- add_sig_brackets(p_figure2d, sig_pos_figure2d)
p_figure2d
saveRDS(p_figure2d, "benchmarks/tot/fig2d.rds")

figure2d_svg_path <- file.path("benchmarks/lr_retrieval_relevance/figures", "figure2d_lr_retrieval_citable_set.svg")
ggsave(figure2d_svg_path, p_figure2d, width = 8, height = 4, units = "in")




summary_sfigure <- summary_df %>%
  filter(
    set == set_levels[["raw"]]
  )
sig_pos_sfigure <- sig_pos %>%
  filter(
    set == set_levels[["raw"]]
  )

p_sfigure <- ggplot(summary_sfigure, aes(x = metric, y = mean, fill = arm)) +
  geom_col(position = dodge, width = 0.72, colour = "black", linewidth = 0.35, alpha = 0.86) +
  geom_errorbar(aes(ymin = ci_lo, ymax = ci_hi), position = dodge, width = 0.18,
                linewidth = 0.45, colour = "black") +
  facet_grid(. ~ strength) +
  scale_fill_manual(values = c("Skill ON" = "darkgreen", "Skill OFF" = "grey60"), name = NULL) +
  scale_y_continuous(limits = c(0, 116), breaks = seq(0, 100, 25), expand = expansion(mult = c(0, 0))) +
  labs(
    x = NULL,
    y = "Coverage of case entities (%)"
  ) +
  theme_bw() +
  theme(
    # plot.title = element_blank(),
    # plot.subtitle = element_blank(),
    # plot.caption = element_blank(),
    # panel.border = element_rect(colour = "grey20", fill = NA, linewidth = 0.55),
    # panel.grid.major = element_line(colour = "grey90", linewidth = 0.45),
    # panel.grid.minor = element_line(colour = "grey94", linewidth = 0.25),
    strip.background = element_rect(fill = "white", colour = NA),
    strip.text = element_text(face = "bold"),
    legend.position = c(0.985, 0.985),
    legend.justification = c(1, 1),
    legend.background = element_rect(fill = "white", colour = "black", linewidth = 0.3),
    legend.key = element_rect(fill = "white", colour = NA),
    legend.margin = margin(4, 6, 4, 6),
    legend.text = element_text(colour = "black")
    # ,
    # legend.text = element_text(size = 8.8),
    # axis.title.y = element_text(size = 12, colour = "black"),
    # axis.text.x = element_text(size = 8.6, colour = "black"),
    # axis.text.y = element_text(size = 9.5, colour = "black")
  )
p_sfigure <- add_sig_brackets(p_sfigure, sig_pos_sfigure)
p_sfigure
saveRDS(p_sfigure, "benchmarks/tot/sfig2d.rds")

sfigure2d_svg_path <- file.path("benchmarks/lr_retrieval_relevance/figures", "sfigure2d_lr_retrieval_citable_set.svg")
ggsave(sfigure2d_svg_path, p_sfigure, width = 8, height = 4, units = "in")




figure2d_35b_svg_path <- file.path(fdir, "figure2d_lr_retrieval_35b_citable_set.svg")
if (file.exists(figure2d_35b_svg_path)) {
  invisible(file.remove(figure2d_35b_svg_path))
}

bundle_fig_dir <- file.path(dirname(results_dir), "figures")
if (basename(results_dir) == "results") {
  dir.create(bundle_fig_dir, recursive = TRUE, showWarnings = FALSE)
  bundle_figure2d_svg_path <- file.path(bundle_fig_dir, "figure2d_lr_retrieval_citable_set.svg")
  ggsave(bundle_figure2d_svg_path, p_figure2d, width = 8.6, height = 6.4, units = "in")
  bundle_figure2d_35b_svg_path <- file.path(bundle_fig_dir, "figure2d_lr_retrieval_35b_citable_set.svg")
  if (file.exists(bundle_figure2d_35b_svg_path)) {
    invisible(file.remove(bundle_figure2d_35b_svg_path))
  }
} else {
  bundle_figure2d_svg_path <- NA_character_
}

cat("wrote:\n  ", svg_path, "\n  ", png_path, "\n  ", figure2d_svg_path, "\n", sep = "")
if (!is.na(bundle_figure2d_svg_path)) {
  cat("  ", bundle_figure2d_svg_path, "\n", sep = "")
}
