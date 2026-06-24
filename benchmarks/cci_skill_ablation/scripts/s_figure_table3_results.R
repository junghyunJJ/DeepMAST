rm(list = ls())

args <- commandArgs(trailingOnly = TRUE)
bench_dir <- if (length(args) >= 1) args[[1]] else getwd()

suppressPackageStartupMessages({
  library(tidyverse)
  library(patchwork)
})

score_table <- file.path(bench_dir, "results", "figure_tables", "supplementary_condition_scores.csv")
score_table <- "benchmarks/cci_skill_ablation/results/figure_tables/supplementary_condition_scores.csv"

fabrication_table <- file.path(bench_dir, "results", "figure_tables", "fabrication_counts.csv")
fabrication_table <- "benchmarks/cci_skill_ablation/results/figure_tables/fabrication_counts.csv"

out_dir <- file.path(bench_dir, "figures")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

condition_levels <- c(
  "Structured SKILLs (Guide-Compliant)",
  "Structured SKILLs (Basic)",
  "Unstructured Prose",
  "No Skills"
)

condition_labels <- c(
  "Structured SKILLs\n(Guide-Compliant)",
  "Structured SKILLs\n(Basic)",
  "Unstructured Prose",
  "No Skills"
)

condition_colors <- c(
  "Structured SKILLs (Guide-Compliant)" = "firebrick3",
  "Structured SKILLs (Basic)" = "tomato",
  "Unstructured Prose" = "pink",
  "No Skills" = "gray60"
)

condition_colors2 <- c(
  "Structured SKILLs\n(Guide-Compliant)" = "firebrick3",
  "Structured SKILLs\n(Basic)" = "tomato",
  "Unstructured Prose" = "pink",
  "No Skills" = "gray60"
)

base_theme <- theme_bw() +
  theme(
    axis.text = element_text(color = "black"),
    axis.text.x = element_text(angle = 45, hjust = 1)
    ,
    # legend.position = "bottom",
    # legend.title = element_blank(),
    # strip.background = element_blank(),
    # strip.text = element_text(face = "bold"),
    # plot.tag = element_text(face = "bold"),
    # plot.title = element_text(face = "bold", hjust = 0.5, size = 11)
  )

df_scores <- readr::read_csv(score_table, show_col_types = FALSE) %>%
  mutate(
    condition = factor(condition, levels = condition_levels),
    dimension = factor(
      dimension,
      levels = c("Composite", "Faithfulness", "Uncertainty Handling", "Spatial Calibration", "Overclaiming")
    ),
    dimension_label = stringr::str_replace_all(dimension, " ", "\n"),
    condition_label = stringr::str_replace_all(condition, " \\(", "\n(")
  )

fig_composite <- ggplot(filter(df_scores, dimension == "Composite"), aes(x = condition, y = mean, fill = condition)) +
  geom_bar(stat = "identity", alpha = 0.8, color = "black", linewidth = 0.3) +
  geom_errorbar(aes(ymin = mean - se, ymax = mean + se), width = 0.2) +
  scale_fill_manual(values = condition_colors) +
  labs(y = "Composite Score", x = NULL) +
  base_theme +
  theme(legend.position = "none") +
  annotate("segment", x = 1, xend = 2, y = 4.25, yend = 4.25, linewidth = 0.4) +
  annotate("segment", x = 1, xend = 1, y = 4.20, yend = 4.25, linewidth = 0.4) +
  annotate("segment", x = 2, xend = 2, y = 4.20, yend = 4.25, linewidth = 0.4) +
  annotate("text", x = 1.5, y = 4.33, label = "'ns'", parse = TRUE, size = 3) +
  annotate("segment", x = 2, xend = 3, y = 4.55, yend = 4.55, linewidth = 0.4) +
  annotate("segment", x = 2, xend = 2, y = 4.50, yend = 4.55, linewidth = 0.4) +
  annotate("segment", x = 3, xend = 3, y = 4.50, yend = 4.55, linewidth = 0.4) +
  annotate("text", x = 2.5, y = 4.63, label = "'***'", parse = TRUE, size = 3) +
  annotate("segment", x = 3, xend = 4, y = 4.85, yend = 4.85, linewidth = 0.4) +
  annotate("segment", x = 3, xend = 3, y = 4.80, yend = 4.85, linewidth = 0.4) +
  annotate("segment", x = 4, xend = 4, y = 4.80, yend = 4.85, linewidth = 0.4) +
  annotate("text", x = 3.5, y = 4.93, label = "'***'", parse = TRUE, size = 3) +
  annotate("segment", x = 1, xend = 4, y = 5.15, yend = 5.15, linewidth = 0.4) +
  annotate("segment", x = 1, xend = 1, y = 5.10, yend = 5.15, linewidth = 0.4) +
  annotate("segment", x = 4, xend = 4, y = 5.10, yend = 5.15, linewidth = 0.4) +
  annotate("text", x = 2.5, y = 5.23, label = "'***'", parse = TRUE, size = 3)

p_left <- ggplot(filter(df_scores, dimension != "Composite"), aes(x = dimension_label, y = mean, fill = condition)) +
  geom_bar(stat = "identity", position = position_dodge(), alpha = 0.8, color = "black", linewidth = 0.3) +
  geom_errorbar(aes(ymin = mean - se, ymax = mean + se), position = position_dodge(width = 0.9), width = 0.2) +
  scale_fill_manual(values = condition_colors) +
  labs(y = "Score", x = NULL) +
  base_theme +
  theme(
    # legend.position = c(0.82, 0.82),
    axis.text.x = element_text(angle = 0, hjust = 0.5),
    legend.background = element_rect(colour = "black"),
    legend.position = "none"
    )
p_left

df_fab <- readr::read_csv(fabrication_table, show_col_types = FALSE) %>%
  mutate(condition = factor(condition, levels = condition_levels, labels = condition_labels))


p_right <- ggplot(df_fab, aes(x = condition, y = mean, fill = condition)) +
  geom_bar(stat = "identity", alpha = 0.8, color = "black", linewidth = 0.4) +
  geom_errorbar(aes(ymin = mean - se, ymax = mean + se), width = 0.2) +
  scale_fill_manual(values = condition_colors2) +
  labs(y = "Fabrication Count", x = NULL) +
  base_theme +
  theme(legend.key.spacing.y = unit(1, "mm"))
p_right

p_combined <- p_left + p_right + plot_layout(widths = c(0.7, 0.25)) + plot_annotation(tag_levels = "A")
p_combined
saveRDS(p_combined, "benchmarks/tot/sfig2c.rds")

ggsave(file.path("benchmarks/cci_skill_ablation/figures", "s_SkillAblation.png"), p_combined, width = 11, height = 5, dpi = 300, bg = "white")
ggsave(file.path("benchmarks/cci_skill_ablation/figures", "s_SkillAblation.svg"), p_combined, width = 11, height = 5, bg = "white")
# ggsave(file.path(out_dir, "s_SkillAblation_composite.png"), fig_composite, width = 4, height = 5.5, dpi = 300, bg = "white")
# ggsave(file.path(out_dir, "s_SkillAblation_composite.svg"), fig_composite, width = 4, height = 5.5, bg = "white")
