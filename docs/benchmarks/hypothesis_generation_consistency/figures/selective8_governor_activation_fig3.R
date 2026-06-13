#!/usr/bin/env Rscript

# Generate a Fig. 3-style activation-fidelity figure for the selective8
# Governor production benchmark.

suppressPackageStartupMessages({
  library(dplyr)
  library(ggplot2)
  library(jsonlite)
  library(patchwork)
  library(svglite)
  library(tidyr)
})

parse_args <- function(args) {
  parsed <- list()
  i <- 1
  while (i <= length(args)) {
    key <- args[[i]]
    if (!startsWith(key, "--")) {
      stop("unexpected positional argument: ", key, call. = FALSE)
    }
    if (i == length(args)) {
      stop("missing value for argument: ", key, call. = FALSE)
    }
    parsed[[substring(key, 3)]] <- args[[i + 1]]
    i <- i + 2
  }
  parsed
}

script_dir <- function() {
  cmd_args <- commandArgs(trailingOnly = FALSE)
  file_arg <- "--file="
  match <- grep(file_arg, cmd_args, fixed = TRUE, value = TRUE)
  if (length(match) == 0) {
    return(getwd())
  }
  dirname(normalizePath(sub(file_arg, "", match[[1]], fixed = TRUE)))
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
root <- normalizePath(file.path(script_dir(), "../../../.."))
default_results_dir <- file.path(
  root,
  "docs/benchmarks/hypothesis_generation_consistency/results",
  "selective8_governor_production_20260611_142352"
)
default_output <- file.path(
  root,
  "docs/benchmarks/hypothesis_generation_consistency/figures",
  "selective8_governor_activation_fig3.svg"
)

results_dir <- normalizePath(args[["results-dir"]] %||% default_results_dir)
output_svg <- args[["output"]] %||% default_output
dir.create(dirname(output_svg), recursive = TRUE, showWarnings = FALSE)

summary_path <- file.path(results_dir, "selective_activation_summary.json")
benchmark_path <- file.path(results_dir, "benchmark_results.json")
if (!file.exists(summary_path)) {
  stop("missing selective activation summary: ", summary_path, call. = FALSE)
}
if (!file.exists(benchmark_path)) {
  stop("missing benchmark results: ", benchmark_path, call. = FALSE)
}

summary_payload <- fromJSON(summary_path, simplifyVector = FALSE)
benchmark_payload <- fromJSON(benchmark_path, simplifyVector = FALSE)

mode_levels <- c(
  "middleware_only",
  "middleware_plus_activator",
  "middleware_plus_governor"
)
mode_labels <- c(
  "middleware_only" = "Middleware only",
  "middleware_plus_activator" = "+ Activator",
  "middleware_plus_governor" = "+ Governor"
)
mode_colors <- c(
  "Middleware only" = "#8A8F98",
  "+ Activator" = "#CC79A7",
  "+ Governor" = "#009E73"
)

model_labels <- c(
  "qwen3.5:35b" = "qwen3.5:35b",
  "qwen3.5:122b" = "qwen3.5:122b"
)

parse_group_key <- function(key) {
  parts <- strsplit(key, "::", fixed = TRUE)[[1]]
  if (length(parts) != 2) {
    stop("unexpected aggregate group key: ", key, call. = FALSE)
  }
  list(model = parts[[1]], mode = parts[[2]])
}

group_items <- summary_payload$aggregate$groups
metric_rows <- bind_rows(lapply(names(group_items), function(key) {
  group <- group_items[[key]]
  parsed <- parse_group_key(key)
  tibble(
    model = parsed$model,
    mode = parsed$mode,
    runs = as.integer(group$runs),
    exact = as.numeric(group$selective_exact_matches) / as.numeric(group$runs),
    precision = as.numeric(group$mean_precision),
    recall = as.numeric(group$mean_recall),
    f1 = as.numeric(group$mean_f1),
    specificity = as.numeric(group$mean_specificity)
  )
}))

metric_order <- c(
  "Exact activation",
  "F1",
  "Recall",
  "Precision",
  "Specificity"
)
metric_plot_df <- metric_rows %>%
  transmute(
    model,
    mode,
    `Exact activation` = exact,
    F1 = f1,
    Recall = recall,
    Precision = precision,
    Specificity = specificity
  ) %>%
  pivot_longer(
    cols = all_of(metric_order),
    names_to = "metric",
    values_to = "value"
  ) %>%
  mutate(
    model = factor(model, levels = names(model_labels), labels = model_labels),
    mode = factor(mode, levels = mode_levels, labels = mode_labels[mode_levels]),
    metric = factor(metric, levels = metric_order),
    value_pct = value * 100
  )

expected_active <- unlist(summary_payload$expected_active_skills, use.names = FALSE)
expected_inactive <- unlist(summary_payload$expected_inactive_skills, use.names = FALSE)
skill_levels <- c(expected_active, expected_inactive)
skill_group <- c(
  rep("Expected active", length(expected_active)),
  rep("Expected inactive", length(expected_inactive))
)
names(skill_group) <- skill_levels
skill_labels <- c(
  "drug-target-hypothesis" = "drug-target\nhypothesis",
  "opentargets-database" = "Open Targets",
  "chembl-database" = "ChEMBL",
  "compare-census-gene-pair-by-cell-type" = "CELLxGENE\npair compare",
  "string-database" = "STRING",
  "gwas-database" = "GWAS",
  "biomedical-literature-search" = "Literature\nsearch",
  "html-report-generator" = "HTML report"
)

rate_for_skill <- function(rates, skill) {
  value <- rates[[skill]]
  if (is.null(value)) {
    return(0)
  }
  as.numeric(value)
}

benchmark_groups <- benchmark_payload$aggregate$groups
skill_rows <- bind_rows(lapply(names(benchmark_groups), function(key) {
  group <- benchmark_groups[[key]]
  parsed <- parse_group_key(key)
  rates <- group$skill_activation_rates
  bind_rows(lapply(skill_levels, function(skill) {
    tibble(
      model = parsed$model,
      mode = parsed$mode,
      skill = skill,
      expected = skill_group[[skill]],
      rate = rate_for_skill(rates, skill)
    )
  }))
}))

skill_plot_df <- skill_rows %>%
  mutate(
    model = factor(model, levels = names(model_labels), labels = model_labels),
    mode = factor(mode, levels = mode_levels, labels = mode_labels[mode_levels]),
    skill = factor(skill, levels = rev(skill_levels), labels = rev(skill_labels[skill_levels])),
    expected = factor(expected, levels = c("Expected active", "Expected inactive")),
    rate_pct = rate * 100,
    label = sprintf("%.0f%%", rate_pct)
  )

base_theme <- theme_bw(base_size = 10) +
  theme(
    plot.title = element_text(face = "bold", size = 11),
    plot.subtitle = element_text(size = 8.5, color = "grey30"),
    axis.text = element_text(color = "black"),
    strip.background = element_rect(fill = "grey92", color = "grey40"),
    strip.text = element_text(face = "bold", color = "black"),
    panel.grid.minor = element_blank(),
    legend.position = "bottom",
    legend.title = element_text(face = "bold")
  )

panel_a <- ggplot(metric_plot_df, aes(metric, value_pct, fill = mode)) +
  geom_col(
    position = position_dodge(width = 0.78),
    width = 0.72,
    color = "black",
    linewidth = 0.25
  ) +
  facet_wrap(~model, nrow = 1) +
  scale_fill_manual(values = mode_colors, name = "Mode") +
  scale_y_continuous(
    limits = c(0, 108),
    breaks = seq(0, 100, 20),
    labels = function(x) paste0(x, "%"),
    expand = c(0, 0)
  ) +
  labs(
    title = "A. Selective activation metrics",
    subtitle = "Governor reaches exact expected active-skill coverage in 35B, but not in 122B.",
    x = NULL,
    y = "Score"
  ) +
  base_theme +
  theme(
    axis.text.x = element_text(angle = 35, hjust = 1),
    legend.position = "bottom"
  )

panel_b <- ggplot(skill_plot_df, aes(mode, skill, fill = rate_pct)) +
  geom_tile(color = "white", linewidth = 0.8) +
  geom_text(aes(label = label), size = 2.8, color = "black") +
  facet_grid(expected ~ model, scales = "free_y", space = "free_y") +
  scale_fill_gradientn(
    colors = c("#F7FBFF", "#9ECAE1", "#08519C"),
    limits = c(0, 100),
    breaks = c(0, 50, 100),
    labels = function(x) paste0(x, "%"),
    name = "Activation\nrate"
  ) +
  labs(
    title = "B. Skill-level activation rates",
    subtitle = "Expected inactive controls remain at 0%; 35B Governor uniquely activates all selective8 expected-active skills.",
    x = NULL,
    y = NULL
  ) +
  base_theme +
  theme(
    axis.text.x = element_text(angle = 35, hjust = 1),
    panel.grid = element_blank(),
    legend.position = "right"
  )

caption <- paste(
  "Activation trace checkpoint benchmark; n = 3 port replicates per model and mode.",
  "Scores are activation-fidelity metrics only and do not evaluate final hypothesis_report.json quality."
)

figure <- panel_a / panel_b +
  plot_layout(heights = c(1.0, 1.28), guides = "collect") +
  plot_annotation(
    title = "Selective8 governor activation fidelity",
    subtitle = "Production hypothesis-writer activation trace benchmark",
    caption = caption,
    theme = theme(
      plot.title = element_text(face = "bold", size = 15),
      plot.subtitle = element_text(size = 10.5, color = "grey25"),
      plot.caption = element_text(size = 8, color = "grey35", hjust = 0)
    )
  )

ggsave(
  filename = output_svg,
  plot = figure,
  width = 10.5,
  height = 7.2,
  units = "in",
  device = svglite::svglite
)

message("wrote ", normalizePath(output_svg))
