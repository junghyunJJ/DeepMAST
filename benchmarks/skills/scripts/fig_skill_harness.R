# Publication figure: SkillActivator Benchmark
# Panel A: Protocol comparison diagram (Passive vs SkillActivator)
# Panel B: Metric comparison (Precision, Recall, F1) with Bootstrap CI
# Panel C: Per-category accuracy heatmap

rm(list = ls())

suppressPackageStartupMessages({
  library(tidyverse)
  library(patchwork)
  library(jsonlite)
  library(grid)
  library(pheatmap)
  library(gtable)
})

# ---- Paths ----
args <- commandArgs(trailingOnly = TRUE)
bench_dir <- if (length(args) >= 1) args[[1]] else file.path(getwd(), "benchmarks/skills")
data_dir <- file.path(bench_dir, "results")
out_dir <- file.path(bench_dir, "figures")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
fig_model <- Sys.getenv("SKILLS_FIG_MODEL", "qwen3.5:122b")
safe_model <- gsub("[.:]", "_", fig_model)
fig_out <- Sys.getenv("SKILLS_FIG_OUT", "fig3.svg")

# ---- Load data ----
agg    <- fromJSON(file.path(data_dir, paste0("compare_expanded_", safe_model, ".json")))
stats  <- fromJSON(file.path(data_dir, paste0("compare_expanded_", safe_model, "_stats.json")))
trials <- stream_in(file(file.path(data_dir, paste0("compare_expanded_", safe_model, "_trials.jsonl"))),
                    verbose = FALSE)
sig_label <- function(p) {
  if (is.null(p) || is.na(p)) {
    return("ns")
  }
  if (p < 0.001) {
    return("***")
  }
  if (p < 0.01) {
    return("**")
  }
  if (p < 0.05) {
    return("*")
  }
  "ns"
}
global_sig_label <- sig_label(stats$mcnemar$p_exact)
target_skills <- sort(unique(unlist(trials$expected_skills)))
condition_labels <- c(
  A_passive = "Passive Skill Listing",
  B_NO_hints = "SkillActivator"
)

# ---- Colors & labels ----
cond_colors <- c(
  "Passive Listing" = "#999999",
  "SkillActivator" = "#CC79A7"
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


# ====================================================================
# Panel B: Metric Comparison (Grouped Bar + significance)
# ====================================================================
metric_names <- c("F1", "Precision", "Recall", "Specificity", "Activation\nRate")

calc_metrics <- function(df) {
  tp <- fp <- tn <- fn <- 0
  activation_hits <- 0
  activation_total <- 0

  for (i in seq_len(nrow(df))) {
    expected <- intersect(as.character(df$expected_skills[[i]]), target_skills)
    activated <- intersect(as.character(df$activated_skills[[i]]), target_skills)
    non_expected <- setdiff(target_skills, expected)

    tp <- tp + length(intersect(activated, expected))
    fp <- fp + length(setdiff(activated, expected))
    fn <- fn + length(setdiff(expected, activated))
    tn <- tn + length(setdiff(non_expected, activated))

    if (length(expected) > 0) {
      activation_total <- activation_total + 1
      if (length(intersect(activated, expected)) > 0) {
        activation_hits <- activation_hits + 1
      }
    }
  }

  precision <- if ((tp + fp) > 0) tp / (tp + fp) else 0
  recall <- if ((tp + fn) > 0) tp / (tp + fn) else 0
  specificity <- if ((tn + fp) > 0) tn / (tn + fp) else 0
  f1 <- if ((precision + recall) > 0) 2 * precision * recall / (precision + recall) else 0
  activation_rate <- if (activation_total > 0) activation_hits / activation_total else 0

  tibble(
    metric = metric_names,
    value = c(f1, precision, recall, specificity, activation_rate) * 100
  )
}

bootstrap_condition_metrics <- function(df) {
  n_boot <- as.integer(Sys.getenv("SKILLS_FIG_BOOTSTRAP_N", "10000"))
  observed <- calc_metrics(df)

  set.seed(42)
  boot <- map_dfr(seq_len(n_boot), function(iter) {
    sampled <- df[sample.int(nrow(df), size = nrow(df), replace = TRUE), , drop = FALSE]
    calc_metrics(sampled) %>% mutate(iter = iter)
  })

  ci <- boot %>%
    group_by(metric) %>%
    summarise(
      ci_low = quantile(value, 0.025, na.rm = TRUE),
      ci_high = quantile(value, 0.975, na.rm = TRUE),
      .groups = "drop"
    )

  observed %>% left_join(ci, by = "metric")
}

metrics_df <- trials %>%
  filter(is.na(error) | error == "null" | error == "") %>%
  split(.$condition) %>%
  imap_dfr(function(df, cond) {
    bootstrap_condition_metrics(df) %>%
      mutate(Condition = condition_labels[[cond]])
  }) %>%
  mutate(
    metric = factor(metric, levels = metric_names),
    Condition = factor(Condition, levels = c("SkillActivator", "Passive Skill Listing"))
  )
metrics_df$metric <- factor(metrics_df$metric, levels = c("Activation\nRate", "F1", "Precision", "Recall", "Specificity"))

# Significance bracket position (over F1, which is at x=1)
f1_bracket_x_1 <- 1
f1_bracket_x_2 <- 2
f1_bracket_x_4 <- 4
dodge <- position_dodge(width = 0.78)


panel_b <- ggplot(metrics_df, aes(metric, value, fill = Condition)) +
  geom_col(position = dodge, width = 0.72, colour = "black", linewidth = 0.35, alpha = 0.86) +
  # geom_bar(stat = "identity",  position = position_dodge(width = 0.78), width = 0.7, color = "black", alpha = 0.8, linewidth = 0.4) +
  geom_errorbar(
    aes(ymin = ci_low, ymax = ci_high),
    position = position_dodge(width =0.78),
    width = 0.18,
    linewidth = 0.45
  ) +

  scale_fill_manual(values = c("firebrick3", "grey60")) +
  scale_y_continuous(limits = c(0, 110), breaks = seq(0, 100, 20)) +
  theme_bw() +

  # Significance bracket over 'Activation Rate'
  annotate("segment",
    x = f1_bracket_x_1 - 0.18, xend = f1_bracket_x_1 + 0.18,
    y = 105, yend = 105
  ) +
  annotate("segment",
    x = f1_bracket_x_1 - 0.18, xend = f1_bracket_x_1 - 0.18,
    y = 105, yend = 103
  ) +
  annotate("segment",
    x = f1_bracket_x_1 + 0.18, xend = f1_bracket_x_1 + 0.18,
    y = 105, yend = 103
  ) +
  annotate("text",
    x = f1_bracket_x_1, y = 110,
    label = global_sig_label
  ) +

  # Significance bracket over 'F1'
  annotate("segment",
    x = f1_bracket_x_2 - 0.18, xend = f1_bracket_x_2 + 0.18,
    y = 105, yend = 105
  ) +
  annotate("segment",
    x = f1_bracket_x_2 - 0.18, xend = f1_bracket_x_2 - 0.18,
    y = 105, yend = 103
  ) +
  annotate("segment",
    x = f1_bracket_x_2 + 0.18, xend = f1_bracket_x_2 + 0.18,
    y = 105, yend = 103
  ) +
  annotate("text",
    x = f1_bracket_x_2, y = 110,
    label = global_sig_label
  ) +

  # Significance bracket over 'Recal'
  annotate("segment",
    x = f1_bracket_x_4 - 0.18, xend = f1_bracket_x_4 + 0.18,
    y = 105, yend = 105
  ) +
  annotate("segment",
    x = f1_bracket_x_4 - 0.18, xend = f1_bracket_x_4 - 0.18,
    y = 105, yend = 103
  ) +
  annotate("segment",
    x = f1_bracket_x_4 + 0.18, xend = f1_bracket_x_4 + 0.18,
    y = 105, yend = 103
  ) +
  annotate("text",
    x = f1_bracket_x_4, y = 110,
    label = global_sig_label
  ) +

  labs(x = NULL, y = "Score (%)") +
  theme(
    legend.position = "none",
    axis.text = element_text(color = "black"),
    axis.text.x = element_text(angle = 50, hjust = 1),
    plot.margin = margin(5, 30, 5, 5)
  )
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
    condition = ifelse(condition == "A_passive", "Passive Skill Listing", "SkillActivator"),
    condition = factor(condition, levels = c("SkillActivator", "Passive Skill Listing")),
    category = factor(category, levels = rev(category_order),
                      labels = rev(category_labels[category_order]))
  )

#cat_acc$category[cat_acc$category == "Stage 1\n(Tool-only)"] <- "Tool-only\n(Stage 1)"
#cat_acc$category[cat_acc$category == "Stage 2\n(Target validation)"] <- "Target validation\n(Stage 2)"
#cat_acc$category[cat_acc$category == "Stage 3\n(Drug profiling)"] <- 'Drug profiling\n(Stage 3)'


# Group annotation: TP categories (top 3) vs TN categories (bottom 4)
# Category order (reversed for heatmap): data_vis, general, internal, stage1, composite, stage3, stage2
# So in the plot: stage2=top(7), stage3(6), composite(5), stage1(4), internal(3), general(2), data_vis=bottom(1)
# TP group = positions 5,6,7 (composite, stage3, stage2)
# TN group = positions 1,2,3,4 (data_vis, general, internal, stage1)

# ---- pheatmap: build accuracy matrix ----
# Clean labels (no newlines) for pheatmap row names
pheatmap_labels <- c(
  stage2_direct      = "Target validation\n(Stage 2)",
  stage3_direct      = "Drug profiling\n(Stage 3)",
  composite          = "Composite\n(Stage 2 + 3)",
  stage1_tools_only  = "Tool-only\n(Stage 1)",
  internal_pipeline  = "Internal pipeline",
  general_biology    = "General biology",
  data_visualization = "Data visualization"
)

# Reverse-lookup: map factor labels (with \n) back to category_order keys
label_to_key <- setNames(names(category_labels), category_labels)

# Accuracy matrix (rows = categories top→bottom, cols = conditions)
acc_mat <- cat_acc %>%
  mutate(
    cat_key  = pheatmap_labels[label_to_key[as.character(category)]],
    cond_str = as.character(condition)
  ) %>%
  select(cond_str, cat_key, accuracy) %>%
  pivot_wider(names_from = cond_str, values_from = accuracy) %>%
  column_to_rownames("cat_key") %>%
  as.matrix()
acc_mat <- acc_mat[pheatmap_labels, , drop = FALSE]

# Display-number matrix (n_correct / n_total)
lab_mat <- cat_acc %>%
  mutate(
    cat_key  = pheatmap_labels[label_to_key[as.character(category)]],
    cond_str = as.character(condition)
  ) %>%
  select(cond_str, cat_key, label) %>%
  pivot_wider(names_from = cond_str, values_from = label) %>%
  column_to_rownames("cat_key") %>%
  as.matrix()
lab_mat <- lab_mat[pheatmap_labels, , drop = FALSE]




# Row annotation — group bar for Skill Reading Expected / Not Expected
row_ann <- data.frame(
  Group = factor(
    c(rep("Skill Reading Expected", 3),
      rep("No Skill Reading Expected", 4)),
    levels = c("Skill Reading Expected", "No Skill Reading Expected")
  ),
  row.names = pheatmap_labels
)

# Column annotation — Condition
col_ann <- data.frame(
  Condition = factor(
    colnames(acc_mat),
    levels = c("SkillActivator", "Passive Skill Listing")
  ),
  row.names = colnames(acc_mat)
)

ann_colors <- list(
  Group = c("Skill Reading Expected"    = "purple",
            "No Skill Reading Expected" = "royalblue1"),
  Condition = c("SkillActivator"       = "firebrick3",
                "Passive Skill Listing"  = "grey60")
)

# Color ramp matching original gradient2
ph_breaks <- seq(60, 100, length.out = 101)
ph_colors <- colorRampPalette(c("#009E73", "#FFF9C4", "#D55E00"))(100)

panel_c_obj <- pheatmap(
  acc_mat[,c("SkillActivator", "Passive Skill Listing")],
  display_numbers   = lab_mat[,c("SkillActivator", "Passive Skill Listing")],
  number_color      = "black",
  cluster_rows      = FALSE,
  cluster_cols      = FALSE,
  annotation_row    = row_ann,
  annotation_col    = col_ann,
  annotation_colors = ann_colors,
  annotation_names_row = FALSE,
  annotation_names_col = FALSE,
  color             = ph_colors,
  breaks            = ph_breaks,
  gaps_row          = 3,
  border_color      = "black",
  angle_col         = "45",
  legend_breaks     = seq(60, 100, 10),
  legend_labels     = paste0(seq(60, 100, 10), "%"),
  main              = "",
  silent            = TRUE
)
# Bold cell numbers via gtable grob manipulation
panel_c <- panel_c_obj$gtable

# # ---- Move Group legend position via gtable manipulation ----
# gt <- panel_c_obj$gtable

# # Find the annotation legend grob and move it below the heatmap
# # gt$layout$name shows all grob names; "annotation_legend" is the Group legend
# leg_idx <- which(gt$layout$name == "annotation_legend")
# if (length(leg_idx) > 0) {
#   # Move legend: place it at the bottom of the heatmap
#   # Get matrix row range for reference
#   mat_idx <- which(gt$layout$name == "matrix")
#   mat_bottom <- gt$layout$b[mat_idx]

#   # Add a new row at the bottom for the legend
#   gt <- gtable_add_rows(gt, unit(1.5, "cm"), pos = mat_bottom + 1)

#   # Copy legend grob to the new bottom row, spanning all columns
#   gt <- gtable_add_grob(
#     gt,
#     grobs = gt$grobs[[leg_idx]],
#     t = mat_bottom + 2,
#     l = gt$layout$l[mat_idx],
#     b = mat_bottom + 2,
#     r = gt$layout$r[mat_idx] + 2,
#     name = "annotation_legend_bottom"
#   )

#   # Remove original legend
#   gt$grobs[[leg_idx]] <- nullGrob()
# }

# panel_c <- gt
# # ====================================================================
# Compose & Save
# ====================================================================
# cowplot handles both ggplot and gtable objects
fig3 <- cowplot::plot_grid(panel_b, panel_c,
  align = "h",
  labels = c("A", "B"),
  rel_widths = c(0.4, 0.5)
)
fig3
ggsave(file.path(out_dir, fig_out), fig3, width = 10, height = 5, bg = "white")

saveRDS(list(panel_b, panel_c), "benchmarks/tot/fig2ab.rds")
