# Publication-style Fig. 3 variant for selective8 governor-vs-middleware.
# Panel A: repeat-level activation metrics with bootstrap CIs.
# Panel B: seven-skill correctness heatmap split by lung/IPF and breast cancer.

rm(list = ls())

suppressPackageStartupMessages({
  library(cowplot)
  library(dplyr)
  library(ggplot2)
  library(grid)
  library(jsonlite)
  library(pheatmap)
  library(purrr)
  library(scales)
  library(tibble)
  library(tidyr)
})

get_arg <- function(flag, default = NULL) {
  args <- commandArgs(trailingOnly = TRUE)
  idx <- match(flag, args)
  if (is.na(idx) || idx == length(args)) {
    return(default)
  }
  args[[idx + 1]]
}

default_stamp <- "selective8_lung_breast_120run_20260614_072904"
results_root <- get_arg(
  "--results-root",
  file.path("docs", "benchmarks", "hypothesis_generation_consistency", "results")
)
output_dir <- get_arg(
  "--output-dir",
  file.path(
    "docs", "benchmarks", "hypothesis_generation_consistency", "figures"
  )
)
output_prefix <- get_arg("--output-prefix", "selective8_governor_vs_middleware_skill_fig3")
bootstrap_n <- as.integer(get_arg(
  "--bootstrap-n",
  Sys.getenv("SELECTIVE8_FIG_BOOTSTRAP_N", "2000")
))

datasets <- tibble::tribble(
  ~dataset, ~dataset_short, ~result_dir,
  "Lung/IPF", "lung", paste0(default_stamp, "_lung"),
  "Breast cancer", "breast", paste0(default_stamp, "_breast")
)

models <- tibble::tribble(
  ~model, ~model_label, ~model_short,
  "qwen3.5:35b", "35B", "35b",
  "qwen3.5:122b", "122B", "122b"
)

modes <- tibble::tribble(
  ~mode,                         ~condition,
  "middleware_plus_governor",    "Governor",
  "middleware_plus_activator",   "Activator",
  "middleware_only",             "Middleware only"
)

selective8_skills <- tibble::tribble(
  ~skill, ~skill_label, ~control,
  "opentargets-database", "Open Targets", "Expected active",
  "chembl-database", "ChEMBL", "Expected active",
  "compare-census-gene-pair-by-cell-type", "Census\ngene-pair", "Expected active",
  "string-database", "STRING", "Expected active",
  "gwas-database", "GWAS", "Negative control",
  "biomedical-literature-search", "Literature\nsearch", "Negative control",
  "html-report-generator", "HTML report", "Negative control"
)

expected_active_skills <- selective8_skills %>%
  filter(control == "Expected active") %>%
  pull(skill)
expected_inactive_skills <- selective8_skills %>%
  filter(control == "Negative control") %>%
  pull(skill)
metric_names <- c("F1", "Precision", "Recall", "Specificity")

as_character_vector <- function(value) {
  if (is.null(value)) {
    return(character())
  }
  as.character(unlist(value, use.names = FALSE))
}

score_skill_correctness <- function(activated_skills, validation_passed) {
  if (!isTRUE(validation_passed)) {
    return(0L)
  }
  activated <- as_character_vector(activated_skills)
  length(intersect(activated, expected_active_skills)) +
    length(setdiff(expected_inactive_skills, activated))
}

score_repeat_metrics <- function(activated_skills, validation_passed) {
  if (!isTRUE(validation_passed)) {
    return(c(F1 = 0, Precision = 0, Recall = 0, Specificity = 0))
  }

  activated <- as_character_vector(activated_skills)
  tp <- length(intersect(activated, expected_active_skills))
  fp <- length(intersect(activated, expected_inactive_skills))
  fn <- length(setdiff(expected_active_skills, activated))
  tn <- length(setdiff(expected_inactive_skills, activated))

  precision <- if ((tp + fp) > 0) tp / (tp + fp) else 0
  recall <- if ((tp + fn) > 0) tp / (tp + fn) else 0
  specificity <- if ((tn + fp) > 0) tn / (tn + fp) else 0
  f1 <- if ((precision + recall) > 0) 2 * precision * recall / (precision + recall) else 0
  c(F1 = f1, Precision = precision, Recall = recall, Specificity = specificity) * 100
}

p_to_star <- function(p_value) {
  if (is.na(p_value)) {
    return(NA_character_)
  }
  if (p_value <= 0.001) {
    return("***")
  }
  if (p_value <= 0.01) {
    return("**")
  }
  if (p_value <= 0.05) {
    return("*")
  }
  "ns"
}

format_p <- function(p_value) {
  if (is.na(p_value)) {
    return("NA")
  }
  formatC(p_value, format = "e", digits = 3)
}

read_groups <- function(dataset, dataset_short, result_dir) {
  summary_path <- file.path(results_root, result_dir, "selective_activation_summary.json")
  benchmark_path <- file.path(results_root, result_dir, "benchmark_results.json")
  if (!file.exists(summary_path)) {
    stop("missing selective activation summary: ", summary_path, call. = FALSE)
  }
  if (!file.exists(benchmark_path)) {
    stop("missing benchmark results: ", benchmark_path, call. = FALSE)
  }
  payload <- fromJSON(summary_path, simplifyVector = FALSE)
  groups <- payload$aggregate$groups
  benchmark_payload <- fromJSON(benchmark_path, simplifyVector = FALSE)
  skill_groups <- benchmark_payload$aggregate$groups

  tidyr::crossing(models, modes) %>%
    mutate(
      dataset = dataset,
      dataset_short = dataset_short,
      group_key = paste(model, mode, sep = "::"),
      group = lapply(group_key, function(key) groups[[key]]),
      skill_group = lapply(group_key, function(key) skill_groups[[key]])
    )
}

group_rows <- pmap_dfr(datasets, read_groups) %>%
  mutate(
    runs = vapply(group, function(g) as.integer(g$runs), integer(1)),
    valid_trace_runs = vapply(group, function(g) as.integer(g$valid_trace_runs), integer(1)),
    exact_matches = vapply(group, function(g) as.integer(g$selective_exact_matches), integer(1)),
    f1 = vapply(group, function(g) as.numeric(g$mean_f1) * 100, numeric(1)),
    precision = vapply(group, function(g) as.numeric(g$mean_precision) * 100, numeric(1)),
    recall = vapply(group, function(g) as.numeric(g$mean_recall) * 100, numeric(1)),
    specificity = vapply(group, function(g) as.numeric(g$mean_specificity) * 100, numeric(1))
  )

read_metric_rows <- function(dataset, dataset_short, result_dir) {
  summary_path <- file.path(results_root, result_dir, "selective_activation_summary.json")
  benchmark_path <- file.path(results_root, result_dir, "benchmark_results.json")
  payload <- fromJSON(summary_path, simplifyVector = FALSE)
  benchmark_payload <- fromJSON(benchmark_path, simplifyVector = FALSE)
  run_ids <- vapply(benchmark_payload$trials, function(trial) {
    as.character(trial$run_id)
  }, character(1))
  validation_by_run_id <- setNames(
    vapply(benchmark_payload$trials, function(trial) {
      isTRUE(trial$returncode == 0) &&
        !is.null(trial$validation) &&
        isTRUE(trial$validation$validation_passed)
    }, logical(1)),
    run_ids
  )
  repeat_by_run_id <- setNames(
    vapply(benchmark_payload$trials, function(trial) {
      if (is.null(trial[["repeat"]])) {
        return(NA_integer_)
      }
      as.integer(trial[["repeat"]])
    }, integer(1)),
    run_ids
  )

  map_dfr(payload$rows, function(row) {
    activated <- intersect(
      as_character_vector(row$activated_skill_names),
      selective8_skills$skill
    )
    run_id <- as.character(row$run_id)
    validation_passed <- run_id %in% names(validation_by_run_id) &&
      isTRUE(validation_by_run_id[[run_id]])
    repeat_id <- if (run_id %in% names(repeat_by_run_id)) {
      repeat_by_run_id[[run_id]]
    } else {
      NA_integer_
    }
    repeat_metrics <- score_repeat_metrics(activated, validation_passed)
    tibble(
      dataset = dataset,
      dataset_short = dataset_short,
      model = as.character(row$model),
      mode = as.character(row$mode),
      run_id = run_id,
      repeat_id = repeat_id,
      valid_trace = isTRUE(row$valid_trace),
      validation_passed = validation_passed,
      skill_correct_score = score_skill_correctness(
        activated,
        validation_passed
      ),
      repeat_f1 = unname(repeat_metrics[["F1"]]),
      repeat_precision = unname(repeat_metrics[["Precision"]]),
      repeat_recall = unname(repeat_metrics[["Recall"]]),
      repeat_specificity = unname(repeat_metrics[["Specificity"]]),
      activated_skills = list(activated)
    )
  })
}

metric_rows <- pmap_dfr(datasets, read_metric_rows) %>%
  left_join(models, by = "model") %>%
  left_join(modes, by = "mode") %>%
  mutate(
    dataset = factor(dataset, levels = datasets$dataset),
    condition = factor(condition, levels = modes$condition),
    model_label = factor(model_label, levels = models$model_label)
  )

compute_significance_for_group <- function(
    rows,
    dataset_name,
    dataset_short,
    model_label_value,
    metric_name,
    score_col) {
  condition_order <- as.character(modes$condition)
  empty_omnibus <- tibble(
    dataset = dataset_name,
    dataset_short = dataset_short,
    model_label = model_label_value,
    metric = metric_name,
    n_blocks = 0L,
    statistic = NA_real_,
    df = NA_real_,
    p_value = NA_real_
  )
  empty_pairs <- tibble(
    dataset = character(),
    dataset_short = character(),
    model_label = character(),
    metric = character(),
    group1 = character(),
    group2 = character(),
    raw_p = numeric(),
    p_adj = numeric(),
    p_label = character(),
    n_blocks = integer()
  )

  wide <- rows %>%
    filter(valid_trace, !is.na(condition), !is.na(repeat_id)) %>%
    mutate(block_id = paste(model_label, repeat_id, sep = "::")) %>%
    mutate(score = .data[[score_col]]) %>%
    select(block_id, condition, score) %>%
    distinct(block_id, condition, .keep_all = TRUE) %>%
    pivot_wider(names_from = condition, values_from = score) %>%
    drop_na(all_of(condition_order))

  if (nrow(wide) < 2) {
    return(list(omnibus = empty_omnibus, pairs = empty_pairs))
  }

  score_matrix <- as.matrix(wide[, condition_order, drop = FALSE])
  omnibus <- tryCatch(
    friedman.test(score_matrix),
    error = function(err) NULL
  )
  omnibus_row <- tibble(
    dataset = dataset_name,
    dataset_short = dataset_short,
    model_label = model_label_value,
    metric = metric_name,
    n_blocks = nrow(wide),
    statistic = if (is.null(omnibus)) NA_real_ else unname(omnibus$statistic),
    df = if (is.null(omnibus)) NA_real_ else unname(omnibus$parameter),
    p_value = if (is.null(omnibus)) NA_real_ else omnibus$p.value
  )

  comparisons <- combn(condition_order, 2, simplify = FALSE)
  raw_p <- vapply(comparisons, function(comparison) {
    x <- wide[[comparison[[1]]]]
    y <- wide[[comparison[[2]]]]
    if (all(x == y)) {
      return(1)
    }
    wilcox.test(x, y, paired = TRUE, exact = FALSE)$p.value
  }, numeric(1))

  pair_rows <- tibble(
    dataset = dataset_name,
    dataset_short = dataset_short,
    model_label = model_label_value,
    metric = metric_name,
    group1 = vapply(comparisons, `[[`, character(1), 1),
    group2 = vapply(comparisons, `[[`, character(1), 2),
    raw_p = raw_p,
    p_adj = p.adjust(raw_p, method = "holm"),
    n_blocks = nrow(wide)
  ) %>%
    mutate(p_label = vapply(p_adj, p_to_star, character(1)))

  list(omnibus = omnibus_row, pairs = pair_rows)
}

metric_score_columns <- tibble::tribble(
  ~metric,        ~score_col,
  "F1",           "repeat_f1",
  "Precision",    "repeat_precision",
  "Recall",       "repeat_recall",
  "Specificity",  "repeat_specificity"
)

significance_results <- pmap(
  tidyr::crossing(datasets, models, metric_score_columns),
  function(
      dataset,
      dataset_short,
      result_dir,
      model,
      model_label,
      model_short,
      metric,
      score_col) {
    compute_significance_for_group(
      metric_rows %>%
        filter(.data$dataset == .env$dataset, .data$model == .env$model),
      dataset,
      dataset_short,
      model_label,
      metric,
      score_col
    )
  }
)
significance_omnibus <- map_dfr(significance_results, "omnibus")
significance_pairs <- map_dfr(significance_results, "pairs")

skill_rows <- pmap_dfr(
  metric_rows %>%
    filter(valid_trace, !is.na(condition)) %>%
    select(dataset, model_label, condition, validation_passed, activated_skills),
  function(dataset, model_label, condition, validation_passed, activated_skills) {
    activated <- as_character_vector(activated_skills)
    selective8_skills %>%
      mutate(
        dataset = dataset,
        model_label = model_label,
        condition = condition,
        correct = validation_passed & if_else(
          control == "Expected active",
          skill %in% activated,
          !(skill %in% activated)
        )
      )
  }
) %>%
  group_by(dataset, model_label, condition, skill, skill_label, control) %>%
  summarise(
    n_correct = sum(correct),
    n_total = n(),
    accuracy_pct = n_correct / n_total * 100,
    .groups = "drop"
  ) %>%
  mutate(
    dataset = factor(dataset, levels = datasets$dataset),
    x_label = paste(model_label, condition, sep = "\n"),
    x_label = factor(
      x_label,
      levels = c(
        "35B\nGovernor", "35B\nActivator", "35B\nMiddleware only",
        "122B\nGovernor", "122B\nActivator", "122B\nMiddleware only"
      )
    ),
    skill_label = factor(skill_label, levels = rev(selective8_skills$skill_label)),
    control = factor(control, levels = c("Expected active", "Negative control")),
    group_label = recode(
      as.character(control),
      "Expected active" = "Skill Reading Expected",
      "Negative control" = "No Skill Reading Expected"
    ),
    group_label = factor(
      group_label,
      levels = c("Skill Reading Expected", "No Skill Reading Expected")
    ),
    cell_label = sprintf("%d/%d", n_correct, n_total)
  )

calc_metrics <- function(df) {
  tp <- fp <- tn <- fn <- 0

  for (row_idx in seq_len(nrow(df))) {
    if (!isTRUE(df$validation_passed[[row_idx]])) {
      fn <- fn + length(expected_active_skills)
      fp <- fp + length(expected_inactive_skills)
      next
    }

    activated <- df$activated_skills[[row_idx]]
    tp <- tp + length(intersect(activated, expected_active_skills))
    fp <- fp + length(intersect(activated, expected_inactive_skills))
    fn <- fn + length(setdiff(expected_active_skills, activated))
    tn <- tn + length(setdiff(expected_inactive_skills, activated))
  }

  precision <- if ((tp + fp) > 0) tp / (tp + fp) else 0
  recall <- if ((tp + fn) > 0) tp / (tp + fn) else 0
  specificity <- if ((tn + fp) > 0) tn / (tn + fp) else 0
  f1 <- if ((precision + recall) > 0) 2 * precision * recall / (precision + recall) else 0

  tibble(
    metric = metric_names,
    value = c(f1, precision, recall, specificity) * 100
  )
}

bootstrap_condition_metrics <- function(df) {
  valid_df <- df %>% filter(valid_trace)
  if (nrow(valid_df) == 0) {
    return(tibble(
      metric = metric_names,
      value = 0,
      ci_low = 0,
      ci_high = 0
    ))
  }

  observed <- calc_metrics(valid_df)
  set.seed(42)
  boot <- map_dfr(seq_len(bootstrap_n), function(iter) {
    sampled <- valid_df[
      sample.int(nrow(valid_df), size = nrow(valid_df), replace = TRUE), ,
      drop = FALSE
    ]
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

metric_significance_annotations <- function(dataset_name, model_filter, metrics_to_show) {
  if (is.null(model_filter)) {
    return(tibble())
  }

  condition_offset <- c(
    "Governor" = -0.78 / 3,
    "Activator" = 0,
    "Middleware only" = 0.78 / 3
  )

  significance_pairs %>%
    filter(
      dataset == dataset_name,
      model_label == model_filter,
      metric %in% metrics_to_show,
      p_adj <= 0.05,
      p_label != "ns"
    ) %>%
    mutate(
      metric_x = match(metric, metrics_to_show),
      x = metric_x + unname(condition_offset[group1]),
      xend = metric_x + unname(condition_offset[group2]),
      xmin = pmin(x, xend),
      xmax = pmax(x, xend),
      bracket_width = xmax - xmin
    ) %>%
    group_by(metric) %>%
    arrange(bracket_width, p_adj, .by_group = TRUE) %>%
    mutate(
      y = 104 + (row_number() - 1) * 7,
      yend = y,
      tick_y = y - 2.8,
      label_x = (xmin + xmax) / 2,
      label_y = y + 2.1
    ) %>%
    ungroup()
}

write_significance_summary <- function() {
  output_json <- file.path(
    output_dir,
    paste0(output_prefix, "_selective7_significance_summary.json")
  )
  output_md <- file.path(
    output_dir,
    paste0(output_prefix, "_selective7_significance_summary.md")
  )

  write_json(
    list(
      scoring = list(
        endpoint = "repeat-level metric scores: F1, Precision, Recall, Specificity",
        denominator = length(selective8_skills$skill),
        validation_failed_runs = "zero correctness credit",
        omnibus = "Friedman test",
        posthoc = "paired Wilcoxon signed-rank tests",
        multiple_testing = "Holm correction"
      ),
      omnibus = significance_omnibus,
      pairwise = significance_pairs
    ),
    output_json,
    pretty = TRUE,
    auto_unbox = TRUE
  )

  lines <- c(
    "# Selective7 Significance Summary",
    "",
    "Endpoint: repeat-level F1, Precision, Recall, and Specificity. Validation-failed runs receive zero metric credit.",
    "",
    "## Friedman Omnibus",
    "",
    "| dataset | model | metric | n blocks | statistic | df | p |",
    "| --- | --- | --- | ---: | ---: | ---: | ---: |"
  )
  for (idx in seq_len(nrow(significance_omnibus))) {
    row <- significance_omnibus[idx, ]
    lines <- c(
      lines,
      sprintf(
        "| %s | %s | %s | %d | %.3f | %.0f | %s |",
        row$dataset,
        row$model_label,
        row$metric,
        row$n_blocks,
        row$statistic,
        row$df,
        format_p(row$p_value)
      )
    )
  }

  lines <- c(
    lines,
    "",
    "## Holm-Adjusted Paired Wilcoxon Post-Hoc",
    "",
    "| dataset | model | metric | comparison | raw p | Holm p | label |",
    "| --- | --- | --- | --- | ---: | ---: | --- |"
  )
  for (idx in seq_len(nrow(significance_pairs))) {
    row <- significance_pairs[idx, ]
    lines <- c(
      lines,
      sprintf(
        "| %s | %s | %s | %s vs %s | %s | %s | %s |",
        row$dataset,
        row$model_label,
        row$metric,
        row$group1,
        row$group2,
        format_p(row$raw_p),
        format_p(row$p_adj),
        row$p_label
      )
    )
  }
  writeLines(lines, output_md)
}

build_panel_b <- function(dataset_skill_rows, facet_label) {
  row_order <- selective8_skills$skill_label
  col_order <- intersect(
    levels(dataset_skill_rows$x_label),
    unique(as.character(dataset_skill_rows$x_label))
  )

  acc_mat <- dataset_skill_rows %>%
    mutate(
      skill_label = as.character(skill_label),
      x_label = as.character(x_label)
    ) %>%
    select(x_label, skill_label, accuracy_pct) %>%
    pivot_wider(names_from = x_label, values_from = accuracy_pct) %>%
    column_to_rownames("skill_label") %>%
    as.matrix()
  acc_mat <- acc_mat[row_order, col_order, drop = FALSE]

  lab_mat <- dataset_skill_rows %>%
    mutate(
      skill_label = as.character(skill_label),
      x_label = as.character(x_label)
    ) %>%
    select(x_label, skill_label, cell_label) %>%
    pivot_wider(names_from = x_label, values_from = cell_label) %>%
    column_to_rownames("skill_label") %>%
    as.matrix()
  lab_mat <- lab_mat[row_order, col_order, drop = FALSE]

  row_ann <- selective8_skills %>%
    mutate(
      Group = if_else(
        control == "Expected active",
        "Skill Reading Expected",
        "No Skill Reading Expected"
      ),
      Group = factor(
        Group,
        levels = c("Skill Reading Expected", "No Skill Reading Expected")
      )
    ) %>%
    select(skill_label, Group) %>%
    column_to_rownames("skill_label")
  row_ann <- row_ann[row_order, , drop = FALSE]

  col_ann <- dataset_skill_rows %>%
    mutate(x_label = as.character(x_label)) %>%
    distinct(x_label, condition) %>%
    arrange(match(x_label, col_order)) %>%
    mutate(
      Condition = factor(
        as.character(condition),
        levels = c("Governor", "Activator", "Middleware only")
      )
    ) %>%
    select(x_label, Condition) %>%
    column_to_rownames("x_label")
  col_ann <- col_ann[col_order, , drop = FALSE]

  ann_colors <- list(
    Group = c(
      "Skill Reading Expected" = "purple",
      "No Skill Reading Expected" = "royalblue1"
    ),
    Condition = c(
      "Governor" = "firebrick3",
      "Activator" = "#CC79A7",
      "Middleware only" = "grey60"
    )
  )

  pheatmap(
    acc_mat,
    display_numbers = lab_mat,
    number_color = "black",
    cluster_rows = FALSE,
    cluster_cols = FALSE,
    annotation_row = row_ann,
    annotation_col = col_ann,
    annotation_colors = ann_colors,
    annotation_names_row = FALSE,
    annotation_names_col = FALSE,
    color = colorRampPalette(c("#009E73", "#FFF9C4", "#D55E00"))(100),
    breaks = seq(0, 100, length.out = 101),
    gaps_row = length(expected_active_skills),
    border_color = "black",
    angle_col = "45",
    legend_breaks = seq(0, 100, 20),
    legend_labels = paste0(seq(0, 100, 20), "%"),
    main = facet_label,
    fontsize = 8.5,
    fontsize_number = 8,
    silent = TRUE
  )$gtable
}

add_significance_layers <- function(plot, sig_df) {
  if (nrow(sig_df) == 0) {
    return(plot)
  }

  plot +
    geom_segment(
      data = sig_df,
      aes(x = xmin, xend = xmax, y = y, yend = yend),
      inherit.aes = FALSE,
      linewidth = 0.45
    ) +
    geom_segment(
      data = sig_df,
      aes(x = xmin, xend = xmin, y = tick_y, yend = y),
      inherit.aes = FALSE,
      linewidth = 0.45
    ) +
    geom_segment(
      data = sig_df,
      aes(x = xmax, xend = xmax, y = tick_y, yend = y),
      inherit.aes = FALSE,
      linewidth = 0.45
    ) +
    geom_text(
      data = sig_df,
      aes(x = label_x, y = label_y, label = p_label),
      inherit.aes = FALSE,
      family = "Arial",
      size = 3.6
    )
}

build_metric_bar_panel <- function(
    dataset_metric_rows,
    dataset_name,
    model_filter,
    metrics_to_show,
    y_label = "Score (%)",
    show_legend = FALSE) {
  metrics_df <- map_dfr(as.character(modes$condition), function(condition_name) {
    bootstrap_condition_metrics(
      dataset_metric_rows %>% filter(condition == condition_name)
    ) %>%
      mutate(condition = condition_name)
  }) %>%
    filter(metric %in% metrics_to_show) %>%
    mutate(
      metric = factor(metric, levels = metrics_to_show),
      condition = factor(condition, levels = modes$condition)
    )

  sig_df <- metric_significance_annotations(dataset_name, model_filter, metrics_to_show)
  x_text_angle <- if (length(metrics_to_show) == 1) 0 else 45
  x_text_hjust <- if (length(metrics_to_show) == 1) 0.5 else 1

  panel <- ggplot(metrics_df, aes(metric, value, fill = condition)) +
    geom_col(
      position = position_dodge(width = 0.78),
      alpha = 0.8,
      color = "black",
      width = 0.72
    ) +
    geom_errorbar(
      aes(ymin = ci_low, ymax = ci_high),
      position = position_dodge(width = 0.78),
      width = 0.18,
      linewidth = 0.45
    ) +
    scale_fill_manual(
      values = c(
        "Governor" = "firebrick3",
        "Activator" = "#CC79A7",
        "Middleware only" = "grey60"
      ),
      name = "Mode"
    ) +
    scale_y_continuous(limits = c(0, 122), breaks = seq(0, 100, 20)) +
    theme_bw() +
    labs(x = NULL, y = y_label) +
    theme(
      legend.position = if (show_legend) "top" else "none",
      legend.direction = "horizontal",
      legend.title = element_text(size = 8),
      legend.text = element_text(size = 8),
      legend.key.width = unit(0.45, "cm"),
      legend.key.height = unit(0.25, "cm"),
      legend.margin = margin(0, 0, 0, 0),
      axis.text = element_text(color = "black"),
      axis.text.x = element_text(angle = x_text_angle, hjust = x_text_hjust),
      plot.margin = margin(5, 30, 5, 5)
    )

  add_significance_layers(panel, sig_df)
}

build_dataset_figure <- function(dataset_name, model_filter = NULL) {
  dataset_group_rows <- group_rows %>% filter(dataset == dataset_name)
  dataset_metric_rows <- metric_rows %>% filter(dataset == dataset_name)
  dataset_skill_rows <- skill_rows %>% filter(dataset == dataset_name)
  facet_label <- dataset_name

  if (!is.null(model_filter)) {
    dataset_group_rows <- dataset_group_rows %>% filter(model_label == model_filter)
    dataset_metric_rows <- dataset_metric_rows %>% filter(model_label == model_filter)
    dataset_skill_rows <- dataset_skill_rows %>% filter(model_label == model_filter)
    facet_label <- paste(dataset_name, model_filter)
  }

  if (nrow(dataset_group_rows) == 0 || nrow(dataset_metric_rows) == 0 || nrow(dataset_skill_rows) == 0) {
    stop(
      "no rows available for dataset=", dataset_name,
      if (!is.null(model_filter)) paste0(", model=", model_filter) else "",
      call. = FALSE
    )
  }

  panel_a <- build_metric_bar_panel(
    dataset_metric_rows,
    dataset_name,
    model_filter,
    metrics_to_show = "F1",
    y_label = "F1 score (%)",
    show_legend = TRUE
  )

  panel_b <- build_panel_b(dataset_skill_rows, facet_label)

  cowplot::plot_grid(
    panel_a,
    panel_b,
    align = "h",
    axis = "tb",
    labels = c("A", ""),
    rel_widths = c(0.40, 0.60)
  )
}

build_supplement_figure <- function(dataset_name, model_filter) {
  dataset_metric_rows <- metric_rows %>%
    filter(dataset == dataset_name, model_label == model_filter)

  if (nrow(dataset_metric_rows) == 0) {
    stop("no rows available for supplement dataset=", dataset_name, ", model=", model_filter, call. = FALSE)
  }

  build_metric_bar_panel(
    dataset_metric_rows,
    dataset_name,
    model_filter,
    metrics_to_show = c("Precision", "Recall", "Specificity"),
    y_label = "Score (%)",
    show_legend = TRUE
  )
}

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
write_significance_summary()

for (dataset_row in seq_len(nrow(datasets))) {
  dataset_name <- datasets$dataset[[dataset_row]]
  dataset_short <- datasets$dataset_short[[dataset_row]]
  output_path <- file.path(output_dir, paste0(output_prefix, "_", dataset_short, ".svg"))
  ggsave(output_path, build_dataset_figure(dataset_name), width = 10, height = 5, bg = "white")
  cat("wrote", normalizePath(output_path, mustWork = FALSE), "\n")

  for (model_row in seq_len(nrow(models))) {
    model_label <- models$model_label[[model_row]]
    model_short <- models$model_short[[model_row]]
    split_output_path <- file.path(
      output_dir,
      paste0(output_prefix, "_", dataset_short, "_", model_short, ".svg")
    )
    ggsave(
      split_output_path,
      build_dataset_figure(dataset_name, model_label),
      width = 10,
      height = 5,
      bg = "white"
    )
    cat("wrote", normalizePath(split_output_path, mustWork = FALSE), "\n")

    supplement_output_path <- file.path(
      output_dir,
      paste0("suppl_", output_prefix, "_", dataset_short, "_", model_short, ".svg")
    )
    ggsave(
      supplement_output_path,
      build_supplement_figure(dataset_name, model_label),
      width = 6,
      height = 4,
      bg = "white"
    )
    cat("wrote", normalizePath(supplement_output_path, mustWork = FALSE), "\n")
  }
}
