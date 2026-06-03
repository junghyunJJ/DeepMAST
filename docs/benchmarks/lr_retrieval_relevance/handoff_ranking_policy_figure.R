#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  required <- c("ggplot2", "dplyr", "tidyr", "gridExtra", "grid")
  missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing) > 0) {
    stop(sprintf("Missing required R packages: %s", paste(missing, collapse = ", ")))
  }
})

library(ggplot2)
library(dplyr)
library(tidyr)
library(gridExtra)
library(grid)

args <- commandArgs(trailingOnly = TRUE)
results_dir <- if (length(args) >= 1) {
  args[[1]]
} else {
  "docs/benchmarks/lr_retrieval_relevance/results/cci_handoff_ranking_policy_benchmark_20260603"
}

root <- normalizePath(results_dir, mustWork = TRUE)
summary_path <- file.path(root, "ranking_policy_summary.csv")
percase_path <- file.path(root, "ranking_policy_percase.csv")
overlap_path <- file.path(root, "ranking_policy_overlap.csv")

for (path in c(summary_path, percase_path, overlap_path)) {
  if (!file.exists(path)) {
    stop(sprintf("Missing required input: %s", path))
  }
}

summary_df <- read.csv(summary_path, stringsAsFactors = FALSE)
percase_df <- read.csv(percase_path, stringsAsFactors = FALSE)
overlap_df <- read.csv(overlap_path, stringsAsFactors = FALSE)

policy_levels <- c(
  "baseline_current",
  "bucket_lr_coverage",
  "bucket_lr_coverage_journal_tiebreak"
)
policy_labels <- c(
  baseline_current = "Baseline\ncurrent",
  bucket_lr_coverage = "Coverage\naware",
  bucket_lr_coverage_journal_tiebreak = "Coverage +\njournal tie-break"
)
policy_colors <- c(
  baseline_current = "#3B6FB6",
  bucket_lr_coverage = "#2D8A5E",
  bucket_lr_coverage_journal_tiebreak = "#8A63B3"
)
policy_plot_colors <- setNames(policy_colors, policy_labels[names(policy_colors)])
bucket_colors <- c(
  Direct = "#2F5597",
  Context = "#70AD47",
  Leakage = "#C00000"
)
metric_colors <- c(
  "LR pairs" = "#2F5597",
  Genes = "#ED7D31",
  Pathways = "#70AD47",
  "Cell types" = "#8064A2"
)

percase_df <- percase_df %>%
  mutate(
    policy = factor(policy, levels = policy_levels, labels = policy_labels[policy_levels])
  )

summary_df <- summary_df %>%
  mutate(
    policy = factor(policy, levels = policy_levels, labels = policy_labels[policy_levels])
  )

composition_df <- percase_df %>%
  select(policy, selected_direct_count, selected_context_count, leakage_count) %>%
  pivot_longer(
    cols = c(selected_direct_count, selected_context_count, leakage_count),
    names_to = "bucket",
    values_to = "count"
  ) %>%
  mutate(
    bucket = recode(
      bucket,
      selected_direct_count = "Direct",
      selected_context_count = "Context",
      leakage_count = "Leakage"
    ),
    bucket = factor(bucket, levels = c("Direct", "Context", "Leakage"))
  )

coverage_df <- percase_df %>%
  select(
    policy,
    lr_pair_coverage_pct,
    gene_coverage_pct,
    pathway_coverage_pct,
    celltype_coverage_pct
  ) %>%
  pivot_longer(
    cols = c(
      lr_pair_coverage_pct,
      gene_coverage_pct,
      pathway_coverage_pct,
      celltype_coverage_pct
    ),
    names_to = "metric",
    values_to = "coverage_pct"
  ) %>%
  mutate(
    metric = recode(
      metric,
      lr_pair_coverage_pct = "LR pairs",
      gene_coverage_pct = "Genes",
      pathway_coverage_pct = "Pathways",
      celltype_coverage_pct = "Cell types"
    ),
    metric = factor(metric, levels = c("LR pairs", "Genes", "Pathways", "Cell types"))
  )

concentration_df <- percase_df %>%
  select(policy, receptor_hhi, pathway_hhi) %>%
  pivot_longer(
    cols = c(receptor_hhi, pathway_hhi),
    names_to = "metric",
    values_to = "hhi"
  ) %>%
  mutate(
    metric = recode(
      metric,
      receptor_hhi = "Receptor HHI",
      pathway_hhi = "Pathway HHI"
    ),
    metric = factor(metric, levels = c("Receptor HHI", "Pathway HHI"))
  )

overlap_plot_df <- overlap_df %>%
  filter(scope == "aggregate") %>%
  mutate(
    policy_a = factor(policy_a, levels = policy_levels, labels = policy_labels[policy_levels]),
    policy_b = factor(policy_b, levels = policy_levels, labels = policy_labels[policy_levels]),
    label = sprintf("%d/40\nJ=%.3f", overlap_count, jaccard)
  )

baseline <- percase_df %>% filter(policy == policy_labels["baseline_current"])
coverage <- percase_df %>% filter(policy == policy_labels["bucket_lr_coverage"])
journal <- percase_df %>% filter(policy == policy_labels["bucket_lr_coverage_journal_tiebreak"])

stats_df <- data.frame(
  statistic = c(
    "candidate_files",
    "cap",
    "available_direct_count",
    "available_context_count",
    "baseline_selected_direct_count",
    "coverage_selected_direct_count",
    "baseline_gene_coverage_pct",
    "coverage_gene_coverage_pct",
    "gene_coverage_delta_coverage_minus_baseline",
    "pathway_hhi_delta_coverage_minus_baseline",
    "baseline_vs_coverage_overlap_count",
    "coverage_vs_journal_overlap_count",
    "inferential_test"
  ),
  value = c(
    nrow(percase_df) / length(policy_levels),
    unique(percase_df$cap)[1],
    baseline$available_direct_count[1],
    baseline$available_context_count[1],
    baseline$selected_direct_count[1],
    coverage$selected_direct_count[1],
    sprintf("%.4f", baseline$gene_coverage_pct[1]),
    sprintf("%.4f", coverage$gene_coverage_pct[1]),
    sprintf("%.4f", coverage$gene_coverage_pct[1] - baseline$gene_coverage_pct[1]),
    sprintf("%.4f", coverage$pathway_hhi[1] - baseline$pathway_hhi[1]),
    overlap_df %>%
      filter(
        scope == "aggregate",
        policy_a == "baseline_current",
        policy_b == "bucket_lr_coverage"
      ) %>%
      pull(overlap_count) %>%
      .[1],
    overlap_df %>%
      filter(
        scope == "aggregate",
        policy_a == "bucket_lr_coverage",
        policy_b == "bucket_lr_coverage_journal_tiebreak"
      ) %>%
      pull(overlap_count) %>%
      .[1],
    "not_run_n1_descriptive_only"
  ),
  stringsAsFactors = FALSE
)

tables_dir <- file.path(root, "manuscript", "tables")
figures_dir <- file.path(root, "manuscript", "figures")
dir.create(tables_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(figures_dir, recursive = TRUE, showWarnings = FALSE)
write.csv(
  stats_df,
  file.path(tables_dir, "handoff_policy_descriptive_stats.csv"),
  row.names = FALSE
)

base_theme <- theme_bw(base_size = 10) +
  theme(
    panel.grid.minor = element_blank(),
    axis.text = element_text(color = "black"),
    axis.title = element_text(color = "black"),
    plot.title = element_text(face = "bold", size = 11),
    legend.title = element_blank(),
    legend.position = "bottom",
    plot.margin = margin(5, 8, 5, 8)
  )

panel_a <- ggplot(composition_df, aes(x = policy, y = count, fill = bucket)) +
  geom_col(color = "black", linewidth = 0.2, width = 0.72) +
  geom_text(
    data = composition_df %>% filter(count > 0),
    aes(label = count),
    position = position_stack(vjust = 0.5),
    color = "white",
    size = 3
  ) +
  geom_hline(yintercept = 40, linetype = "dashed", linewidth = 0.4, color = "grey25") +
  scale_fill_manual(values = bucket_colors) +
  scale_y_continuous(limits = c(0, 42), breaks = seq(0, 40, 10), expand = c(0, 0)) +
  labs(
    title = "A. cap=40 selected composition",
    x = NULL,
    y = "Selected papers"
  ) +
  base_theme +
  theme(axis.text.x = element_text(size = 8))

panel_b <- ggplot(coverage_df, aes(x = metric, y = coverage_pct, fill = policy)) +
  geom_col(
    position = position_dodge(width = 0.78),
    color = "black",
    linewidth = 0.2,
    width = 0.72
  ) +
  geom_text(
    aes(label = sprintf("%.1f", coverage_pct)),
    position = position_dodge(width = 0.78),
    vjust = -0.35,
    size = 2.6
  ) +
  scale_fill_manual(values = policy_plot_colors) +
  scale_y_continuous(limits = c(0, 112), breaks = seq(0, 100, 25), expand = c(0, 0)) +
  labs(
    title = "B. Coverage of handoff evidence",
    x = NULL,
    y = "Coverage (%)"
  ) +
  base_theme

panel_c <- ggplot(concentration_df, aes(x = metric, y = hhi, fill = policy)) +
  geom_col(
    position = position_dodge(width = 0.76),
    color = "black",
    linewidth = 0.2,
    width = 0.7
  ) +
  geom_text(
    aes(label = sprintf("%.3f", hhi)),
    position = position_dodge(width = 0.76),
    vjust = -0.45,
    size = 2.7
  ) +
  scale_fill_manual(values = policy_plot_colors) +
  scale_y_continuous(limits = c(0, 0.28), expand = c(0, 0)) +
  labs(
    title = "C. Redundancy / concentration",
    x = NULL,
    y = "Herfindahl-Hirschman index"
  ) +
  base_theme

panel_d <- ggplot(overlap_plot_df, aes(x = policy_a, y = policy_b, fill = jaccard)) +
  geom_tile(color = "white", linewidth = 1.2) +
  geom_text(aes(label = label), size = 3.3, lineheight = 0.9) +
  scale_fill_gradient(low = "#F2F2F2", high = "#3B6FB6", limits = c(0, 1)) +
  labs(
    title = "D. Selected PMID overlap",
    x = "Policy A",
    y = "Policy B",
    fill = "Jaccard"
  ) +
  base_theme +
  theme(
    legend.position = "right",
    axis.text.x = element_text(size = 8),
    axis.text.y = element_text(size = 8)
  )

subtitle <- textGrob(
  "Breast cancer CCI production candidate artifact (n=1); descriptive comparison only, no inferential p-values.",
  gp = gpar(fontsize = 9)
)

figure <- arrangeGrob(
  arrangeGrob(panel_a, panel_b, ncol = 2),
  arrangeGrob(panel_c, panel_d, ncol = 2),
  subtitle,
  ncol = 1,
  heights = c(1, 1, 0.08)
)

svg_path <- file.path(figures_dir, "fig_handoff_ranking_policy.svg")
png_path <- file.path(figures_dir, "fig_handoff_ranking_policy.png")

svg(svg_path, width = 10.5, height = 7.2)
grid.draw(figure)
dev.off()

png(png_path, width = 2100, height = 1440, res = 200, type = "cairo")
grid.draw(figure)
dev.off()

default_pdf <- file.path(getwd(), "Rplots.pdf")
if (file.exists(default_pdf)) {
  unlink(default_pdf)
}

message("wrote:\n  ", svg_path, "\n  ", png_path, "\n  ",
        file.path(tables_dir, "handoff_policy_descriptive_stats.csv"))
