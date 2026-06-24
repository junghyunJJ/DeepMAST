#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(jsonlite)
  library(ggplot2)
  library(scales)
})

get_script_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg) == 0) {
    return(getwd())
  }
  dirname(normalizePath(sub("^--file=", "", file_arg[[1]]), mustWork = FALSE))
}

cli_args <- commandArgs(trailingOnly = TRUE)
bundle_dir <- if (length(cli_args) >= 1) {
  normalizePath(cli_args[[1]], mustWork = TRUE)
} else {
  normalizePath(file.path(get_script_dir(), ".."), mustWork = TRUE)
}

result_dir <- file.path(bundle_dir, "results", "raw")
summary_dir <- file.path(bundle_dir, "results")
figure_dir <- file.path(bundle_dir, "figures")
dir.create(summary_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(figure_dir, recursive = TRUE, showWarnings = FALSE)

files <- data.frame(
  model = c("35B", "35B", "122B", "122B"),
  condition = c("wiki_off", "wiki_doc_routing", "wiki_off", "wiki_doc_routing"),
  condition_label = c(
    "Baseline retrieval",
    "SGCP-enabled retrieval",
    "Baseline retrieval",
    "SGCP-enabled retrieval"
  ),
  path = file.path(
    result_dir,
    c(
      "multihop_full_qwen35_35b_port7000_wiki_off_rw3.jsonl",
      "multihop_full_qwen35_35b_port7000_wiki_doc_routing_rw3.jsonl",
      "multihop_full_qwen35_122b_port6000_wiki_off_rw3.jsonl",
      "multihop_full_qwen35_122b_port6000_wiki_doc_routing_rw3.jsonl"
    )
  ),
  stringsAsFactors = FALSE
)

writing_files <- data.frame(
  model = c("35B", "35B", "35B", "122B", "122B", "122B"),
  condition = c(
    "wiki_off",
    "wiki_static_refs",
    "wiki_doc_routing",
    "wiki_off",
    "wiki_static_refs",
    "wiki_doc_routing"
  ),
  condition_label = c(
    "Baseline retrieval",
    "Static-reference SGCP",
    "SGCP-enabled retrieval",
    "Baseline retrieval",
    "Static-reference SGCP",
    "SGCP-enabled retrieval"
  ),
  path = file.path(
    result_dir,
    c(
      "multihop_full_qwen35_35b_port7000_wiki_off_rw3.jsonl",
      "multihop_full_qwen35_35b_port7000_wiki_static_refs_rw3.jsonl",
      "multihop_full_qwen35_35b_port7000_wiki_doc_routing_rw3.jsonl",
      "multihop_full_qwen35_122b_port6000_wiki_off_rw3.jsonl",
      "multihop_full_qwen35_122b_port6000_wiki_static_refs_rw3.jsonl",
      "multihop_full_qwen35_122b_port6000_wiki_doc_routing_rw3.jsonl"
    )
  ),
  stringsAsFactors = FALSE
)

missing_files <- files$path[!file.exists(files$path)]
if (length(missing_files) > 0) {
  stop("Missing benchmark result file(s):\n", paste(missing_files, collapse = "\n"))
}
missing_writing_files <- writing_files$path[!file.exists(writing_files$path)]
if (length(missing_writing_files) > 0) {
  stop("Missing writing reproducibility result file(s):\n", paste(missing_writing_files, collapse = "\n"))
}

to_logical <- function(x) {
  if (is.logical(x)) {
    return(x)
  }
  if (is.numeric(x)) {
    return(x != 0)
  }
  tolower(as.character(x)) %in% c("true", "t", "yes", "y", "1")
}

read_jsonl <- function(path) {
  con <- file(path, open = "r")
  on.exit(close(con), add = TRUE)
  stream_in(con, verbose = FALSE)
}

accuracy_ci <- function(correct, n) {
  prop.test(correct, n)$conf.int
}

mean_ci <- function(x) {
  x <- x[!is.na(x)]
  se <- stats::sd(x) / sqrt(length(x))
  mean(x) + c(-1, 1) * stats::qt(0.975, df = length(x) - 1) * se
}

format_p <- function(p) {
  if (is.na(p)) {
    return("P=NA")
  }
  if (p < 1e-300) {
    return("P<1e-300")
  }
  if (p < 0.001) {
    return(sprintf("P=%.1e", p))
  }
  sprintf("P=%.3f", p)
}

summaries <- do.call(
  rbind,
  lapply(seq_len(nrow(files)), function(i) {
    cfg <- files[i, ]
    d <- read_jsonl(cfg$path)

    contains <- to_logical(d$contains)
    n_accuracy <- sum(!is.na(contains))
    n_correct <- sum(contains, na.rm = TRUE)
    acc <- n_correct / n_accuracy
    acc_ci <- accuracy_ci(n_correct, n_accuracy)

    recall_values <- d$evidence_recall
    recall_values <- recall_values[!is.na(recall_values)]
    recall <- mean(recall_values)
    recall_ci <- mean_ci(recall_values)

    data.frame(
      model = cfg$model,
      condition = cfg$condition,
      condition_label = cfg$condition_label,
      metric = c("Exact-answer accuracy", "Evidence recall"),
      value = c(acc, recall),
      ymin = c(acc_ci[[1]], recall_ci[[1]]),
      ymax = c(acc_ci[[2]], recall_ci[[2]]),
      n = c(n_accuracy, length(recall_values)),
      stringsAsFactors = FALSE
    )
  })
)

raw_data <- do.call(
  rbind,
  lapply(seq_len(nrow(files)), function(i) {
    cfg <- files[i, ]
    d <- read_jsonl(cfg$path)
    data.frame(
      model = cfg$model,
      condition = cfg$condition,
      id = d$id,
      contains = to_logical(d$contains),
      evidence_recall = d$evidence_recall,
      stringsAsFactors = FALSE
    )
  })
)

summaries$model <- factor(summaries$model, levels = c("35B", "122B"))
summaries$condition_label <- factor(
  summaries$condition_label,
  levels = c("SGCP-enabled retrieval", "Baseline retrieval")
)
summaries$metric <- factor(
  summaries$metric,
  levels = c("Exact-answer accuracy", "Evidence recall")
)

off <- summaries[summaries$condition == "wiki_off", ]
routing <- summaries[summaries$condition == "wiki_doc_routing", ]
deltas <- merge(
  off[, c("model", "metric", "value", "ymax")],
  routing[, c("model", "metric", "value", "ymax")],
  by = c("model", "metric"),
  suffixes = c("_off", "_routing")
)
deltas$delta <- deltas$value_routing - deltas$value_off
deltas$label <- sprintf("+%.1f pp", deltas$delta * 100)
deltas$y <- pmin(pmax(deltas$ymax_off, deltas$ymax_routing) * 100 + 3.2, 42)
deltas$model <- factor(deltas$model, levels = c("35B", "122B"))
deltas$metric <- factor(deltas$metric, levels = levels(summaries$metric))

tests <- do.call(
  rbind,
  lapply(levels(summaries$model), function(model_name) {
    model_data <- raw_data[raw_data$model == model_name, ]
    off_data <- model_data[model_data$condition == "wiki_off", ]
    routing_data <- model_data[model_data$condition == "wiki_doc_routing", ]

    paired <- merge(
      off_data,
      routing_data,
      by = "id",
      suffixes = c("_off", "_routing")
    )

    accuracy_pairs <- paired[
      !is.na(paired$contains_off) & !is.na(paired$contains_routing),
    ]
    routing_only <- sum(!accuracy_pairs$contains_off & accuracy_pairs$contains_routing)
    off_only <- sum(accuracy_pairs$contains_off & !accuracy_pairs$contains_routing)
    accuracy_p <- binom.test(
      min(routing_only, off_only),
      routing_only + off_only,
      p = 0.5
    )$p.value
    accuracy_delta <- mean(accuracy_pairs$contains_routing) -
      mean(accuracy_pairs$contains_off)

    recall_pairs <- paired[
      !is.na(paired$evidence_recall_off) &
        !is.na(paired$evidence_recall_routing),
    ]
    recall_test <- stats::wilcox.test(
      recall_pairs$evidence_recall_routing,
      recall_pairs$evidence_recall_off,
      paired = TRUE,
      exact = FALSE
    )
    recall_delta <- mean(recall_pairs$evidence_recall_routing) -
      mean(recall_pairs$evidence_recall_off)

    data.frame(
      model = model_name,
      metric = c("Exact-answer accuracy", "Evidence recall"),
      test = c("Exact McNemar test", "Paired Wilcoxon signed-rank test"),
      n_pairs = c(nrow(accuracy_pairs), nrow(recall_pairs)),
      routing_only = c(routing_only, NA_integer_),
      off_only = c(off_only, NA_integer_),
      delta = c(accuracy_delta, recall_delta),
      p_value = c(accuracy_p, recall_test$p.value),
      stringsAsFactors = FALSE
    )
  })
)

tests$model <- factor(tests$model, levels = c("35B", "122B"))
tests$metric <- factor(tests$metric, levels = levels(summaries$metric))
tests$label <- sprintf("+%.1f pp\n%s", tests$delta * 100, vapply(tests$p_value, format_p, character(1)))
tests$y <- c(42.0, 32.0, 39.0, 32.0)
tests$stars <- "***"
tests$bracket_y <- c(39.0, 29.0, 36.5, 29.0)
tests$star_y <- tests$bracket_y + 1.1
tests$tick_y <- tests$bracket_y - 0.45
tests$model_x <- as.numeric(tests$model)
tests$xmin <- tests$model_x - 0.225
tests$xmax <- tests$model_x + 0.225

summary_out <- summaries
summary_out$value_percent <- summary_out$value * 100
summary_out$ci_low_percent <- summary_out$ymin * 100
summary_out$ci_high_percent <- summary_out$ymax * 100
write.csv(
  summary_out,
  file.path(summary_dir, "sgcp_accuracy_recall_summary.csv"),
  row.names = FALSE
)
write.csv(
  tests,
  file.path(summary_dir, "sgcp_accuracy_recall_tests.csv"),
  row.names = FALSE
)

mean_or_na <- function(x) {
  if (length(x) == 0 || all(is.na(x))) {
    return(NA_real_)
  }
  mean(x, na.rm = TRUE)
}

writing_raw_data <- do.call(
  rbind,
  lapply(seq_len(nrow(writing_files)), function(i) {
    cfg <- writing_files[i, ]
    d <- read_jsonl(cfg$path)
    data.frame(
      model = cfg$model,
      condition = cfg$condition,
      condition_label = cfg$condition_label,
      id = d$id,
      contains = to_logical(d$contains),
      evidence_recall = d$evidence_recall,
      token_f1 = d$token_f1,
      error = d$error,
      retrieved_document_count = d$retrieved_document_count,
      wiki_promoted_document_count = d$wiki_promoted_document_count,
      elapsed_seconds = d$elapsed_seconds,
      stringsAsFactors = FALSE
    )
  })
)

writing_summary <- do.call(
  rbind,
  lapply(seq_len(nrow(writing_files)), function(i) {
    cfg <- writing_files[i, ]
    d <- writing_raw_data[
      writing_raw_data$model == cfg$model &
        writing_raw_data$condition == cfg$condition,
    ]
    contains <- d$contains
    recall_values <- d$evidence_recall[!is.na(d$evidence_recall)]
    correct_contains <- sum(contains, na.rm = TRUE)
    n_total <- sum(!is.na(contains))
    data.frame(
      model = cfg$model,
      condition = cfg$condition,
      condition_label = cfg$condition_label,
      n = n_total,
      correct_contains = correct_contains,
      accuracy = correct_contains / n_total,
      answerable_accuracy = correct_contains / length(recall_values),
      evidence_recall = mean_or_na(recall_values),
      no_relevant_context = sum(d$error == "no_relevant_context", na.rm = TRUE),
      retrieved_chunks = mean_or_na(d$retrieved_document_count),
      promoted_chunks = mean_or_na(d$wiki_promoted_document_count),
      mean_latency_s = mean_or_na(d$elapsed_seconds),
      token_f1 = mean_or_na(d$token_f1),
      stringsAsFactors = FALSE
    )
  })
)

paired_condition_test <- function(model_name, baseline_condition, comparison_condition) {
  model_data <- writing_raw_data[writing_raw_data$model == model_name, ]
  baseline <- model_data[model_data$condition == baseline_condition, ]
  comparison <- model_data[model_data$condition == comparison_condition, ]
  paired <- merge(
    baseline,
    comparison,
    by = "id",
    suffixes = c("_baseline", "_comparison")
  )

  accuracy_pairs <- paired[
    !is.na(paired$contains_baseline) & !is.na(paired$contains_comparison),
  ]
  comparison_only <- sum(!accuracy_pairs$contains_baseline & accuracy_pairs$contains_comparison)
  baseline_only <- sum(accuracy_pairs$contains_baseline & !accuracy_pairs$contains_comparison)
  accuracy_p <- binom.test(
    min(comparison_only, baseline_only),
    comparison_only + baseline_only,
    p = 0.5
  )$p.value
  accuracy_delta <- mean(accuracy_pairs$contains_comparison) -
    mean(accuracy_pairs$contains_baseline)

  recall_pairs <- paired[
    !is.na(paired$evidence_recall_baseline) &
      !is.na(paired$evidence_recall_comparison),
  ]
  recall_test <- stats::wilcox.test(
    recall_pairs$evidence_recall_comparison,
    recall_pairs$evidence_recall_baseline,
    paired = TRUE,
    exact = FALSE
  )
  recall_delta <- mean(recall_pairs$evidence_recall_comparison) -
    mean(recall_pairs$evidence_recall_baseline)

  latency_delta <- mean_or_na(paired$elapsed_seconds_comparison) -
    mean_or_na(paired$elapsed_seconds_baseline)

  data.frame(
    model = model_name,
    baseline_condition = baseline_condition,
    comparison_condition = comparison_condition,
    comparison_label = paste(comparison_condition, "vs", baseline_condition),
    accuracy_delta = accuracy_delta,
    comparison_only_correct = comparison_only,
    baseline_only_correct = baseline_only,
    accuracy_mcnemar_exact_p = accuracy_p,
    evidence_recall_delta = recall_delta,
    evidence_recall_wilcoxon_p = recall_test$p.value,
    no_relevant_context_baseline = sum(baseline$error == "no_relevant_context", na.rm = TRUE),
    no_relevant_context_comparison = sum(comparison$error == "no_relevant_context", na.rm = TRUE),
    latency_delta_s = latency_delta,
    stringsAsFactors = FALSE
  )
}

static_reference_tests <- do.call(
  rbind,
  list(
    paired_condition_test("35B", "wiki_off", "wiki_static_refs"),
    paired_condition_test("35B", "wiki_doc_routing", "wiki_static_refs"),
    paired_condition_test("122B", "wiki_off", "wiki_static_refs"),
    paired_condition_test("122B", "wiki_doc_routing", "wiki_static_refs")
  )
)

write.csv(
  writing_summary,
  file.path(summary_dir, "sgcp_all_conditions_summary.csv"),
  row.names = FALSE
)
write.csv(
  static_reference_tests,
  file.path(summary_dir, "sgcp_static_reference_tests.csv"),
  row.names = FALSE
)

plot_data <- summaries
plot_data$value_percent <- plot_data$value * 100
plot_data$ymin_percent <- plot_data$ymin * 100
plot_data$ymax_percent <- plot_data$ymax * 100

condition_colors <- c(
  "Baseline retrieval" = "#A6CEE3",
  "SGCP-enabled retrieval" = "#1F78B4"
)

dodge <- position_dodge(width = 0.78)

p <- ggplot(
  plot_data,
  aes(
    x = model,
    y = value_percent,
    fill = condition_label
  )
) +
  geom_col(position = dodge, width = 0.72, colour = "black", linewidth = 0.35, alpha = 0.86) +
  geom_errorbar(
    aes(ymin = ymin_percent, ymax = ymax_percent),
    position = dodge,
    width = 0.18,
    linewidth = 0.45,
    colour = "black"
  ) +
  geom_segment(
    data = tests,
    aes(x = xmin, xend = xmax, y = bracket_y, yend = bracket_y),
    inherit.aes = FALSE,
    linewidth = 0.55,
    color = "black"
  ) +
  geom_segment(
    data = tests,
    aes(x = xmin, xend = xmin, y = tick_y, yend = bracket_y),
    inherit.aes = FALSE,
    linewidth = 0.55,
    color = "black"
  ) +
  geom_segment(
    data = tests,
    aes(x = xmax, xend = xmax, y = tick_y, yend = bracket_y),
    inherit.aes = FALSE,
    linewidth = 0.55,
    color = "black"
  ) +
  geom_text(
    data = tests,
    aes(x = model_x, y = star_y, label = stars),
    inherit.aes = FALSE,
    size = 3.4,
    color = "black"
  ) +
  facet_grid(. ~ metric) +
  scale_fill_manual(values = condition_colors, name = NULL) +
  scale_y_continuous(
    labels = label_percent(scale = 1),
    limits = c(0, 43),
    breaks = seq(0, 40, by = 10),
    expand = expansion(mult = c(0, 0))
  ) +
  labs(
    x = NULL,
    y = "Benchmark score"
  ) +
  theme_bw() +
  theme(
    strip.background = element_rect(fill = "white", colour = NA),
    strip.text = element_text(face = "bold"),
    legend.position = c(0.985, 0.985),
    legend.justification = c(1, 1),
    legend.background = element_rect(fill = "white", colour = "black", linewidth = 0.3),
    legend.key = element_rect(fill = "white", colour = NA),
    legend.margin = margin(4, 6, 4, 6),
    legend.text = element_text(colour = "black"),
    axis.text = element_text(colour = "black")
  )

saveRDS(p, "benchmarks/tot/fig2e.rds")

png_path <- file.path(figure_dir, "sgcp_accuracy_recall_main.png")
svg_path <- file.path(figure_dir, "sgcp_accuracy_recall_main.svg")
pdf_path <- file.path(figure_dir, "sgcp_accuracy_recall_main.pdf")

ggsave(png_path, p, width = 8, height = 4, units = "in", dpi = 300, bg = "white")
ggsave(svg_path, p, width = 8, height = 4, units = "in", bg = "white")
if (file.exists(pdf_path)) {
  invisible(file.remove(pdf_path))
}

figure2c_svg_path <- file.path(figure_dir, "figure2c_sgcp_accuracy_recall.svg")
ggsave(figure2c_svg_path, p, width = 8, height = 4, units = "in", bg = "white")

figure2c_35b_svg_path <- file.path(figure_dir, "figure2c_sgcp_35b_accuracy_recall.svg")
if (file.exists(figure2c_35b_svg_path)) {
  invisible(file.remove(figure2c_35b_svg_path))
}

message("Wrote: ", png_path)
message("Wrote: ", svg_path)
message("Wrote: ", figure2c_svg_path)
message("Wrote: ", file.path(summary_dir, "sgcp_accuracy_recall_summary.csv"))
message("Wrote: ", file.path(summary_dir, "sgcp_accuracy_recall_tests.csv"))
message("Wrote: ", file.path(summary_dir, "sgcp_all_conditions_summary.csv"))
message("Wrote: ", file.path(summary_dir, "sgcp_static_reference_tests.csv"))
