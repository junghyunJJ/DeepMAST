# Publication-style figure for the selective8 hypothesis-generation benchmark.
# Panel A: F1 by dataset, model, and middleware mode.
# Panel B: Precision, recall, specificity, and F1 heatmap.

rm(list = ls())

suppressPackageStartupMessages({
  library(dplyr)
  library(ggplot2)
  library(jsonlite)
  library(patchwork)
  library(purrr)
  library(scales)
  library(tidyr)
})

check <- function(label, condition, detail = NULL) {
  if (!isTRUE(condition)) {
    message <- paste0("check failed: ", label)
    if (!is.null(detail) && nzchar(detail)) {
      message <- paste0(message, " (", detail, ")")
    }
    stop(message, call. = FALSE)
  }
  cat("check:", label, "ok\n")
}

default_stamp <- "selective8_lung_breast_120run_20260614_072904"

get_arg <- function(flag, default = NULL) {
  args <- commandArgs(trailingOnly = TRUE)
  idx <- match(flag, args)
  if (is.na(idx) || idx == length(args)) {
    return(default)
  }
  args[[idx + 1]]
}
results_root <- get_arg(
  "--results-root",
  file.path("docs", "benchmarks", "hypothesis_generation_consistency", "results")
)
svg_out <- get_arg(
  "--output",
  file.path(results_root, paste0(default_stamp, "_fig3.svg"))
)
png_out <- get_arg(
  "--png-output",
  file.path(results_root, paste0(default_stamp, "_fig3.png"))
)
copy_out <- get_arg("--copy-output", NULL)


check(
  "arguments",
  dir.exists(results_root) &&
    nzchar(svg_out) &&
    (is.null(png_out) || is.character(png_out)) &&
    (is.null(copy_out) || is.character(copy_out)),
  paste("results_root =", results_root)
)

datasets <- tibble::tribble(
  ~dataset,         ~dataset_short, ~result_dir,
  "Lung/IPF",       "lung",         paste0(default_stamp, "_lung"),
  "Breast cancer", "breast",       paste0(default_stamp, "_breast")
)



check(
  "datasets",
  nrow(datasets) == 2 &&
    all(c("dataset", "dataset_short", "result_dir") %in% names(datasets)) &&
    !anyDuplicated(datasets$dataset_short),
  paste("rows =", nrow(datasets))
)

models <- tibble::tribble(
  ~model,          ~model_label,
  "qwen3.5:35b",  "35B",
  "qwen3.5:122b", "122B"
)

check(
  "models",
  nrow(models) == 2 &&
    all(c("model", "model_label") %in% names(models)) &&
    !anyDuplicated(models$model),
  paste("rows =", nrow(models))
)

modes <- tibble::tribble(
  ~mode,                         ~mode_label,  ~mode_short,
  "middleware_only",             "Middleware", "Middleware",
  "middleware_plus_activator",   "+Activator", "+Activator",
  "middleware_plus_governor",    "+Governor",  "+Governor"
)

check(
  "modes",
  nrow(modes) == 3 &&
    all(c("mode", "mode_label", "mode_short") %in% names(modes)) &&
    !anyDuplicated(modes$mode),
  paste("rows =", nrow(modes))
)

read_dataset_summary <- function(dataset, dataset_short, result_dir) {
  summary_path <- file.path(results_root, result_dir, "selective_activation_summary.json")
  check(paste(dataset_short, "summary file"), file.exists(summary_path), summary_path)

  payload <- fromJSON(summary_path, simplifyVector = FALSE)

  groups <- payload$aggregate$groups
  check(
    paste(dataset_short, "summary groups"),
    !is.null(groups) && length(groups) > 0,
    summary_path
  )

  expected_group_keys <- tidyr::crossing(models, modes) %>%
    mutate(group_key = paste(model, mode, sep = "::")) %>%
    pull(group_key)
  missing_group_keys <- setdiff(expected_group_keys, names(groups))
  check(
    paste(dataset_short, "expected groups"),
    length(missing_group_keys) == 0,
    paste(missing_group_keys, collapse = ", ")
  )

  tidyr::crossing(models, modes) %>%
    mutate(
      dataset = dataset,
      dataset_short = dataset_short,
      group_key = paste(model, mode, sep = "::"),
      group = map(group_key, ~ groups[[.x]]),
      valid_trace_runs = map_int(group, "valid_trace_runs"),
      exact_matches = map_int(group, "selective_exact_matches"),
      precision = map_dbl(group, "mean_precision") * 100,
      recall = map_dbl(group, "mean_recall") * 100,
      specificity = map_dbl(group, "mean_specificity") * 100,
      f1 = map_dbl(group, "mean_f1") * 100
    ) %>%
    select(
      dataset, dataset_short, model, model_label, mode, mode_label, mode_short,
      valid_trace_runs, exact_matches, precision, recall, specificity, f1
    )
}

records <- pmap_dfr(datasets, read_dataset_summary) %>%
  mutate(
    dataset = factor(dataset, levels = datasets$dataset),
    model = factor(model, levels = models$model),
    mode = factor(mode, levels = modes$mode),
    mode_label = factor(mode_label, levels = modes$mode_label),
    condition_label = factor(
      paste(dataset, model_label, sep = "\n"),
      levels = as.vector(t(outer(datasets$dataset, models$model_label, paste, sep = "\n")))
    ),
    heatmap_label = factor(
      paste(dataset_short, model_label, mode_short),
      levels = paste(
        rep(datasets$dataset_short, each = nrow(models) * nrow(modes)),
        rep(models$model_label, each = nrow(modes), times = nrow(datasets)),
        rep(modes$mode_short, times = nrow(datasets) * nrow(models))
      )
    )
  )

metric_columns <- c("precision", "recall", "specificity", "f1")
check(
  "records",
  nrow(records) == nrow(datasets) * nrow(models) * nrow(modes) &&
    all(metric_columns %in% names(records)) &&
    !anyNA(records[metric_columns]) &&
    all(unlist(records[metric_columns]) >= 0) &&
    all(unlist(records[metric_columns]) <= 100),
  paste("rows =", nrow(records))
)

mode_colors <- c(
  "Middleware" = "#999999",
  "+Activator" = "#CC79A7",
  "+Governor" = "#D55E00"
)

panel_a <- ggplot(records, aes(mode_label, f1, fill = mode_label)) +
  theme_bw() +
  geom_col(
    position = position_dodge(width = 0.78),
    width = 0.72,
    colour = "black",
    linewidth = 0.35,
    alpha = 0.88
  ) +
  scale_fill_manual(values = mode_colors, drop = FALSE) +
  scale_y_continuous(limits = c(0, 110), breaks = seq(0, 100, 20), expand = c(0, 0)) +
  labs(
    title = "A  F1 by dataset, model, and middleware",
    x = NULL,
    y = "F1 score (%)",
    fill = NULL
  ) +
  facet_grid(dataset ~ model)
  # theme(
    # plot.title = element_text(face = "bold", hjust = 0, size = 10),
    # legend.position = c(0.15, 0.92),
    # legend.background = element_blank(),
    # legend.key.size = unit(0.36, "cm"),
    # axis.text = element_text(colour = "black"),
    # axis.text.x = element_text(size = 8),
    # panel.grid.major.x = element_blank(),
    # panel.grid.minor = element_blank(),
    # plot.margin = margin(5, 8, 5, 5)
  # )
panel_a
check("panel A", inherits(panel_a, "ggplot"))

heatmap_df <- records %>%
  select(heatmap_label, precision, recall, specificity, f1) %>%
  pivot_longer(
    cols = c(precision, recall, specificity, f1),
    names_to = "metric",
    values_to = "value"
  ) %>%
  mutate(
    metric = factor(
      metric,
      levels = c("precision", "recall", "specificity", "f1"),
      labels = c("Precision", "Recall", "Specificity", "F1")
    ),
    label = sprintf("%.0f", value),
    label_color = ifelse(value <= 35, "white", "black")
  )

check(
  "heatmap data",
  nrow(heatmap_df) == nrow(records) * length(metric_columns) &&
    !anyNA(heatmap_df$value) &&
    !anyNA(heatmap_df$label),
  paste("rows =", nrow(heatmap_df))
)

panel_b <- ggplot(heatmap_df, aes(metric, heatmap_label, fill = value)) +
  geom_tile(colour = "black", linewidth = 0.22) +
  geom_text(aes(label = label, colour = label_color), size = 2.7) +
  scale_colour_identity() +
  scale_fill_gradient2(
    low = "#009E73",
    mid = "#FFF9C4",
    high = "#D55E00",
    midpoint = 50,
    limits = c(0, 100),
    breaks = seq(0, 100, 20),
    labels = label_number(suffix = ""),
    name = "Score (%)"
  ) +
  scale_y_discrete(limits = rev(levels(records$heatmap_label))) +
  labs(
    title = "B  Selective8 activation metrics",
    x = NULL,
    y = NULL
  ) +
  theme_bw(base_size = 9) +
  theme(
    plot.title = element_text(face = "bold", hjust = 0, size = 10),
    axis.text = element_text(colour = "black"),
    axis.text.x = element_text(size = 8),
    axis.text.y = element_text(size = 6.8),
    panel.grid = element_blank(),
    legend.title = element_text(size = 8),
    legend.text = element_text(size = 7),
    plot.margin = margin(5, 5, 5, 8)
  )

check("panel B", inherits(panel_b, "ggplot"))

fig3 <- panel_a + panel_b +
  plot_layout(widths = c(0.42, 0.58)) +
  plot_annotation(
    title = "DeepMAST selective8 hypothesis benchmark",
    caption = "Values are valid-trace means across 10 repeats per condition.",
    theme = theme(
      plot.title = element_text(face = "bold", size = 13, hjust = 0),
      plot.caption = element_text(size = 7.5, hjust = 0, colour = "#333333"),
      plot.margin = margin(4, 4, 4, 4)
    )
  )

check("fig3", inherits(fig3, "patchwork"))

dir.create(dirname(svg_out), recursive = TRUE, showWarnings = FALSE)
ggsave(svg_out, fig3, width = 10, height = 5, bg = "white")
check(
  "output svg",
  file.exists(svg_out) && file.info(svg_out)$size > 0,
  svg_out
)

if (!is.null(png_out) && nzchar(png_out)) {
  dir.create(dirname(png_out), recursive = TRUE, showWarnings = FALSE)
  ggsave(png_out, fig3, width = 10, height = 5, dpi = 220, bg = "white")
  check(
    "output png",
    file.exists(png_out) && file.info(png_out)$size > 0,
    png_out
  )
}

if (!is.null(copy_out) && nzchar(copy_out)) {
  dir.create(dirname(copy_out), recursive = TRUE, showWarnings = FALSE)
  invisible(file.copy(svg_out, copy_out, overwrite = TRUE))
  check(
    "copy svg",
    file.exists(copy_out) && file.info(copy_out)$size > 0,
    copy_out
  )
}

cat("wrote", normalizePath(svg_out, mustWork = FALSE), "\n")
if (!is.null(png_out) && nzchar(png_out)) {
  cat("wrote", normalizePath(png_out, mustWork = FALSE), "\n")
}
if (!is.null(copy_out) && nzchar(copy_out)) {
  cat("wrote", normalizePath(copy_out, mustWork = FALSE), "\n")
}
