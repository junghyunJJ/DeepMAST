rm(list = ls())

args <- commandArgs(trailingOnly = TRUE)
bench_dir <- if (length(args) >= 1) args[[1]] else getwd()

suppressPackageStartupMessages({
  library(tidyverse)
})

# figure_table <- file.path(bench_dir, "results", "figure_tables", "main_condition_scores.csv")
figure_table <- "benchmarks/cci_skill_ablation/results/figure_tables/main_condition_scores.csv"
out_dir <- file.path(bench_dir, "figures")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

df_scores <- readr::read_csv(figure_table, show_col_types = FALSE) %>%
  mutate(
    condition = factor(condition, levels = c("Structured SKILLs", "Unstructured Prose", "No Skills")),
    dimension = factor(
      dimension,
      levels = c("Composite", "Faithfulness", "Uncertainty Handling", "Spatial Calibration", "Overclaiming")
    )
  )

condition_colors <- c(
  "Structured SKILLs" = "firebrick3",
  "Unstructured Prose" = "pink",
  "No Skills" = "gray60"
)

base_theme <- theme_bw() +
  theme(
    axis.text = element_text(color = "black"),
    axis.text.x = element_text(angle = 45, hjust = 1),
    legend.position = "none",
    legend.title = element_blank(),
    strip.background = element_blank(),
    strip.text = element_text(face = "bold"),
    plot.tag = element_text(face = "bold"),
    plot.title = element_text(face = "bold", hjust = 0.5, size = 11)
  )

fig3b <- ggplot(filter(df_scores, dimension == "Composite"), aes(x = condition, y = mean, fill = condition)) +
  # geom_bar(stat = "identity", alpha = 0.8, color = "black", linewidth = 0.3) +
  geom_bar(stat = "identity", color = "black", alpha = 0.8, linewidth = 0.4) +
  geom_errorbar(aes(ymin = mean - se, ymax = mean + se), width = 0.2) +
  scale_fill_manual(values = condition_colors) +
  labs(y = "Composite Score", x = NULL) +
  base_theme +
  annotate("segment", x = 1, xend = 2, y = 4.25, yend = 4.25, linewidth = 0.4) +
  annotate("segment", x = 1, xend = 1, y = 4.20, yend = 4.25, linewidth = 0.4) +
  annotate("segment", x = 2, xend = 2, y = 4.20, yend = 4.25, linewidth = 0.4) +
  annotate("text", x = 1.5, y = 4.33, label = "'***'", parse = TRUE) +
  annotate("segment", x = 2, xend = 3, y = 4.55, yend = 4.55, linewidth = 0.4) +
  annotate("segment", x = 2, xend = 2, y = 4.50, yend = 4.55, linewidth = 0.4) +
  annotate("segment", x = 3, xend = 3, y = 4.50, yend = 4.55, linewidth = 0.4) +
  annotate("text", x = 2.5, y = 4.63, label = "'***'", parse = TRUE) +
  annotate("segment", x = 1, xend = 3, y = 4.85, yend = 4.85, linewidth = 0.4) +
  annotate("segment", x = 1, xend = 1, y = 4.80, yend = 4.85, linewidth = 0.4) +
  annotate("segment", x = 3, xend = 3, y = 4.80, yend = 4.85, linewidth = 0.4) +
  annotate("text", x = 2, y = 4.93, label = "'***'", parse = TRUE)
fig3b
saveRDS(fig3b, "benchmarks/tot/fig2c.rds")

ggsave(file.path(out_dir, "SkillAblation.png"), fig3b, width = 3, height = 5, dpi = 300, bg = "white")
ggsave(file.path(out_dir, "SkillAblation.svg"), fig3b, width = 3, height = 5, bg = "white")
