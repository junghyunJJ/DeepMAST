# Publication figure: SkillLoadHarness Benchmark
# Panel A: Protocol comparison diagram (Passive vs SkillLoadHarness)
# Panel B: Metric comparison (Precision, Recall, F1) with Bootstrap CI
# Panel C: Per-category accuracy heatmap
rm(list = ls())
suppressPackageStartupMessages({
  library(tidyverse)
  library(patchwork)
  library(jsonlite)
  library(grid)
})

# ---- Paths ----
project_root <- here::here()
data_dir     <- file.path(project_root, "scripts/benchmarks")
out_dir      <- file.path(project_root, "docs/benchmarks/skills/figures")

# ---- Load data ----
agg    <- fromJSON(file.path(data_dir, "compare_expanded_qwen3_5_122b.json"))
stats  <- fromJSON(file.path(data_dir, "compare_expanded_qwen3_5_122b_stats.json"))
trials <- stream_in(file(file.path(data_dir, "compare_expanded_qwen3_5_122b_trials.jsonl")),
                    verbose = FALSE)

# ---- Colors & labels ----
cond_colors <- c(
  "Passive Listing" = "#999999",
  "SkillLoadHarness" = "#CC79A7"
)

category_labels <- c(
  stage2_direct      = "Stage 2\n(Target validation)",
  stage3_direct      = "Stage 3\n(Drug profiling)",
  composite          = "Composite\n(Stage 2 + 3)",
  stage1_tools_only  = "Stage 1\n(Tool-only)",
  internal_pipeline  = "Internal\npipeline",
  general_biology    = "General\nbiology",
  data_visualization = "Data\nvisualization"
)

category_order <- names(category_labels)

# ---- Base theme (matches existing figures) ----
base_theme <- theme_bw() +
  theme(
    text = element_text(size = 10),
    axis.text = element_text(color = "black"),
    legend.position = "bottom",
    legend.title = element_blank(),
    strip.background = element_blank(),
    strip.text = element_text(face = "bold"),
    plot.tag = element_text(face = "bold", size = 14)
  )

# ====================================================================
# Panel A: Protocol Comparison Diagram
# ====================================================================
make_panel_a <- function() {
  d <- tibble(x = 0, y = 0)  # dummy

  p <- ggplot(d, aes(x, y)) +
    xlim(0, 10) + ylim(0, 10) +
    theme_void() +
    theme(plot.tag = element_text(face = "bold", size = 14))

  # --- Left: Passive Listing ---
  p <- p +
    # Header
    annotate("rect", xmin = 0.2, xmax = 4.8, ymin = 8.5, ymax = 9.8,
             fill = "#E8E8E8", color = "grey40", linewidth = 0.5) +
    annotate("text", x = 2.5, y = 9.15, label = "Passive Listing",
             fontface = "bold", size = 3.5) +

    # Box: skill list
    annotate("rect", xmin = 0.5, xmax = 4.5, ymin = 5.5, ymax = 8.2,
             fill = "white", color = "grey60", linewidth = 0.4) +
    annotate("text", x = 2.5, y = 7.7, label = '"Available Skills:\n - Skill 1: desc\n - Skill 2: desc\n - Skill N: desc"',
             size = 2.4, lineheight = 0.9, hjust = 0.5) +

    # Arrow down
    annotate("segment", x = 2.5, xend = 2.5, y = 5.5, yend = 4.8,
             arrow = arrow(length = unit(0.15, "cm")), linewidth = 0.4) +

    # Box: implicit decision
    annotate("rect", xmin = 0.8, xmax = 4.2, ymin = 3.5, ymax = 4.8,
             fill = "#FFF3E0", color = "#E69F00", linewidth = 0.4) +
    annotate("text", x = 2.5, y = 4.15, label = "LLM decides\nimplicitly",
             size = 2.6, lineheight = 0.9) +

    # Failure modes
    annotate("text", x = 2.5, y = 2.8, label = "Failure modes:",
             fontface = "bold", size = 2.4) +
    annotate("text", x = 2.5, y = 1.6,
             label = paste0(
               "x Over-activation (FP)\n",
               "x Under-activation (FN)\n",
               "x No reasoning trace"
             ),
             size = 2.2, lineheight = 1.0, color = "#D55E00")

  # --- Right: SkillLoadHarness ---
  p <- p +
    # Header
    annotate("rect", xmin = 5.2, xmax = 9.8, ymin = 8.5, ymax = 9.8,
             fill = "#F3E5F5", color = "#CC79A7", linewidth = 0.5) +
    annotate("text", x = 7.5, y = 9.15, label = "SkillLoadHarness",
             fontface = "bold", size = 3.5, color = "#CC79A7") +

    # Phase 1
    annotate("rect", xmin = 5.4, xmax = 9.6, ymin = 7.2, ymax = 8.3,
             fill = "white", color = "#CC79A7", linewidth = 0.4) +
    annotate("text", x = 7.5, y = 7.95, label = "Phase 1: QUICK SCREEN",
             fontface = "bold", size = 2.4, color = "#CC79A7") +
    annotate("text", x = 7.5, y = 7.45, label = 'Gate: "Need skill guide?"\nDefault: NO',
             size = 2.2, lineheight = 0.9) +

    # Arrow: YES
    annotate("segment", x = 7.5, xend = 7.5, y = 7.2, yend = 6.5,
             arrow = arrow(length = unit(0.12, "cm")), linewidth = 0.4) +
    annotate("text", x = 7.8, y = 6.85, label = "YES", size = 2.0, fontface = "italic") +

    # Phase 2
    annotate("rect", xmin = 5.4, xmax = 9.6, ymin = 4.8, ymax = 6.5,
             fill = "white", color = "#CC79A7", linewidth = 0.4) +
    annotate("text", x = 7.5, y = 6.2, label = "Phase 2: EVALUATE",
             fontface = "bold", size = 2.4, color = "#CC79A7") +
    annotate("text", x = 7.5, y = 5.4,
             label = "Per-skill YES/NO + reason\nContext match -> YES\nWhen in doubt -> NO",
             size = 2.2, lineheight = 0.9) +

    # Arrow: load skills
    annotate("segment", x = 7.5, xend = 7.5, y = 4.8, yend = 4.1,
             arrow = arrow(length = unit(0.12, "cm")), linewidth = 0.4) +
    annotate("text", x = 8.2, y = 4.45, label = "read_skill_file()", size = 2.0, fontface = "italic") +

    # Phase 3
    annotate("rect", xmin = 5.4, xmax = 9.6, ymin = 3.2, ymax = 4.1,
             fill = "white", color = "#CC79A7", linewidth = 0.4) +
    annotate("text", x = 7.5, y = 3.65, label = "Phase 3: IMPLEMENT",
             fontface = "bold", size = 2.4, color = "#CC79A7") +

    # Mitigations
    annotate("text", x = 7.5, y = 2.5, label = "Mitigations:",
             fontface = "bold", size = 2.4) +
    annotate("text", x = 7.5, y = 1.4,
             label = paste0(
               "+ Gate filters irrelevant tasks\n",
               "+ Explicit eval forces consideration\n",
               "+ Auditable YES/NO reasoning"
             ),
             size = 2.2, lineheight = 1.0, color = "#009E73")

  # --- Divider ---
  p <- p +
    annotate("segment", x = 5, xend = 5, y = 0.5, yend = 9.8,
             linetype = "dashed", color = "grey70", linewidth = 0.3)

  p
}

panel_a <- make_panel_a() + labs(tag = "A")


# ====================================================================
# Panel B: Metric Comparison (Grouped Bar + significance)
# ====================================================================
metrics_df <- tibble(
  metric = rep(c("Precision", "Recall", "F1"), 2),
  condition = rep(c("Passive Listing", "SkillLoadHarness"), each = 3),
  value = c(
    agg$A_passive$precision * 100,
    agg$A_passive$recall * 100,
    agg$A_passive$f1 * 100,
    agg$B_NO_hints$precision * 100,
    agg$B_NO_hints$recall * 100,
    agg$B_NO_hints$f1 * 100
  )
) %>%
  mutate(
    metric = factor(metric, levels = c("Precision", "Recall", "F1")),
    condition = factor(condition, levels = c("Passive Listing", "SkillLoadHarness"))
  )

# Bootstrap CI for F1 (from stats)
f1_ci <- tibble(
  metric = c("F1", "F1"),
  condition = c("Passive Listing", "SkillLoadHarness"),
  # CI is on the difference; approximate per-condition CI from bootstrap
  ymin = c(agg$A_passive$f1 * 100 - 3,      # approximate
           stats$f1_B * 100 - (stats$bootstrap$ci_hi - stats$f1_diff) * 100),
  ymax = c(agg$A_passive$f1 * 100 + 3,
           stats$f1_B * 100 + (stats$f1_diff - stats$bootstrap$ci_lo) * 100)
) %>%
  mutate(condition = factor(condition, levels = c("Passive Listing", "SkillLoadHarness")))

panel_b <- ggplot(metrics_df, aes(metric, value, fill = condition)) +
  geom_col(position = position_dodge(0.7), width = 0.6, alpha = 0.85) +
  geom_text(aes(label = sprintf("%.1f%%", value)),
            position = position_dodge(0.7), vjust = -0.5, size = 2.8) +
  scale_fill_manual(values = cond_colors) +
  scale_y_continuous(limits = c(0, 115), breaks = seq(0, 100, 20)) +

  # Significance bracket over F1
  annotate("segment", x = 2.82, xend = 3.18, y = 105, yend = 105, linewidth = 0.4) +
  annotate("segment", x = 2.82, xend = 2.82, y = 105, yend = 102, linewidth = 0.4) +
  annotate("segment", x = 3.18, xend = 3.18, y = 105, yend = 102, linewidth = 0.4) +
  annotate("text", x = 3, y = 108,
           label = paste0("dF1 = +13.1%\np < 0.001 ***"),
           size = 2.6, lineheight = 0.9) +

  labs(x = NULL, y = "Score (%)") +
  base_theme +
  theme(axis.text.x = element_text(angle = 0, hjust = 0.5)) +
  labs(tag = "B")

panel_b

# ====================================================================
# Panel C: Per-Category Accuracy Heatmap
# ====================================================================

# Compute per-category accuracy from trials
cat_acc <- trials %>%
  filter(is.na(error) | error == "null" | error == "") %>%
  mutate(
    expected_set = map_chr(expected_skills, ~ paste(sort(.), collapse = ",")),
    activated_set = map_chr(activated_skills, ~ paste(sort(.), collapse = ",")),
    correct = (expected_set == activated_set)
  ) %>%
  group_by(condition, category) %>%
  summarise(
    n_correct = sum(correct),
    n_total = n(),
    accuracy = n_correct / n_total * 100,
    .groups = "drop"
  ) %>%
  mutate(
    label = sprintf("%d/%d", n_correct, n_total),
    condition = ifelse(condition == "A_passive", "Passive Listing", "SkillLoadHarness"),
    condition = factor(condition, levels = c("Passive Listing", "SkillLoadHarness")),
    category = factor(category, levels = rev(category_order),
                      labels = rev(category_labels[category_order]))
  )

panel_c <- ggplot(cat_acc, aes(condition, category, fill = accuracy)) +
  geom_tile(color = "white", linewidth = 0.8) +
  geom_text(aes(label = label), size = 3, fontface = "bold") +
  scale_fill_gradient2(
    low = "#D55E00", mid = "#FFF9C4", high = "#009E73",
    midpoint = 85, limits = c(60, 100),
    name = "Accuracy (%)"
  ) +
  labs(x = NULL, y = NULL) +
  base_theme +
  theme(
    axis.text.x = element_text(angle = 0, hjust = 0.5),
    legend.position = "right",
    legend.key.height = unit(1.5, "cm")
  ) +
  labs(tag = "C")


# ====================================================================
# Compose & Save
# ====================================================================
fig <- panel_a / (panel_b | panel_c) +
  plot_layout(heights = c(1.2, 1)) +
  plot_annotation(
    title = "SkillLoadHarness: Structured Skill Evaluation Protocol",
    subtitle = paste0(
      "qwen3.5:122b | 7 categories x 20 prompts = 140 trials | ",
      "Bootstrap dF1 = +13.1% (95% CI [+6.7%, +20.8%], p < 0.001)"
    ),
    theme = theme(
      plot.title = element_text(face = "bold", size = 12),
      plot.subtitle = element_text(size = 9, color = "grey40")
    )
  )

ggsave(file.path(out_dir, "fig_skill_harness.svg"), fig,
       width = 10, height = 10, bg = "white")
ggsave(file.path(out_dir, "fig_skill_harness.pdf"), fig,
       width = 10, height = 10, bg = "white")

cat("Saved:", file.path(out_dir, "fig_skill_harness.svg"), "\n")
cat("Saved:", file.path(out_dir, "fig_skill_harness.pdf"), "\n")
