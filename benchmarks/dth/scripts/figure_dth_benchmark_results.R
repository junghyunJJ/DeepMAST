rm(list = ls())

args <- commandArgs(trailingOnly = TRUE)
bench_root <- if (length(args) >= 1) {
  args[[1]]
} else {
  file.path(getwd(), "benchmarks", "dth")
}

default_result_dir <- file.path(bench_root, "results")
result_dir <- if (length(args) >= 2) {
  args[[2]]
} else {
  Sys.getenv("DTH_BENCHMARK_RESULT_DIR", default_result_dir)
}

suppressPackageStartupMessages({
  library(dplyr)
  library(ggplot2)
  library(jsonlite)
  library(readr)
  library(tidyr)
})

`%||%` <- function(x, y) {
  if (is.null(x)) y else x
}

out_dir <- file.path(bench_root, "figures")
table_dir <- file.path(bench_root, "results", "figure_tables")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(table_dir, recursive = TRUE, showWarnings = FALSE)

summary_json <- file.path(result_dir, "cumulative_valid_only_summary_for_20each_target.json")
judge_dir <- file.path(result_dir, "judge")
judge_files <- tibble::tibble(
  judge_label = c("GPT-5.4", "Sonnet 4.6"),
  file_name = c(
    "dth_yes_no_gpt54_blind_summary.json",
    "dth_yes_no_sonnet46_blind_summary.json"
  ),
  row_file = c(
    "dth_yes_no_gpt54_blind_judge_rows.jsonl",
    "dth_yes_no_sonnet46_blind_judge_rows.jsonl"
  )
)

stopifnot(file.exists(summary_json))
stopifnot(all(file.exists(file.path(judge_dir, judge_files$file_name))))
stopifnot(all(file.exists(file.path(judge_dir, judge_files$row_file))))

condition_levels <- c("DTH_yes", "DTH_no")
condition_labels <- c(
  "DTH_no" = "Baseline",
  "DTH_yes" = "DTH-guided"
)
condition_colors <- c(
  "DTH_no" = "grey60",
  "DTH_yes" = "#430541"
)
outcome_colors <- c(
  "DTH-guided" = "#084594",
  "Tie" = "#c6dbef",
  "Baseline" = "#6baed6"
)
main_condition_order <- c("DTH-guided", "Baseline")

base_theme <- theme_bw() +
  theme(
    axis.text = element_text(color = "black"),
    axis.title = element_text(color = "black"),
    legend.title = element_blank(),
    # legend.position = "top",
    # panel.grid.major.y = element_line(color = "#d9e7f5", linewidth = 0.25),
    plot.title = element_text(face = "bold", hjust = 0),
    plot.subtitle = element_text(color = "#334155"),
    plot.caption = element_text(color = "#475569", hjust = 0),
    # strip.background = element_blank(),
    strip.text = element_text(face = "bold", color = "black")
  )

axis_only_theme <- base_theme
# +
#   theme(
#     legend.position = "none",
#     plot.title = element_blank(),
#     plot.subtitle = element_blank(),
#     plot.caption = element_blank()
#   )

summary_data <- jsonlite::fromJSON(summary_json, simplifyVector = FALSE)
valid_rows <- summary_data$valid_run_table
coverage_df <- dplyr::bind_rows(lapply(seq_along(valid_rows), function(i) {
  row <- valid_rows[[i]]
  data.frame(
    run_index = i,
    condition = as.character(row$condition %||% NA_character_),
    stamp = as.character(row$stamp %||% NA_character_),
    repeat_id = as.integer(row[["repeat"]] %||% NA_integer_),
    run_id = as.character(row$run_id %||% NA_character_),
    valid = isTRUE(row$valid),
    dth_activated = isTRUE(row$dth_activated),
    coverage = as.numeric(row$coverage %||% NA_real_),
    hypothesis_count = as.integer(row$hypothesis_count %||% NA_integer_),
    retry_attempts = as.integer(row$retry_attempts %||% NA_integer_),
    elapsed_s = as.numeric(row$elapsed_s %||% NA_real_),
    stringsAsFactors = FALSE
  )
})) %>%
  filter(valid, condition %in% condition_levels) %>%
  mutate(
    condition = factor(condition, levels = condition_levels),
    condition_label = factor(condition_labels[as.character(condition)],
      levels = condition_labels[condition_levels]
    ),
    within_condition_index = ave(seq_along(condition), condition, FUN = seq_along)
  )

coverage_summary <- coverage_df %>%
  group_by(condition, condition_label) %>%
  summarise(
    n = n(),
    mean_coverage = mean(coverage, na.rm = TRUE),
    median_coverage = median(coverage, na.rm = TRUE),
    sd_coverage = sd(coverage, na.rm = TRUE),
    se_coverage = sd_coverage / sqrt(n),
    min_coverage = min(coverage, na.rm = TRUE),
    max_coverage = max(coverage, na.rm = TRUE),
    .groups = "drop"
  )

readr::write_csv(coverage_df, file.path(table_dir, "dth_fig3a_evidence_coverage_runs.csv"))
readr::write_csv(coverage_summary, file.path(table_dir, "dth_fig3a_evidence_coverage_summary.csv"))

coverage_wide <- coverage_df %>%
  select(condition, within_condition_index, coverage) %>%
  tidyr::pivot_wider(names_from = condition, values_from = coverage) %>%
  arrange(within_condition_index) %>%
  mutate(delta_yes_minus_no = DTH_yes - DTH_no)
coverage_wilcox <- suppressWarnings(stats::wilcox.test(
  coverage_wide$DTH_yes,
  coverage_wide$DTH_no,
  paired = TRUE,
  exact = FALSE
))
coverage_test <- data.frame(
  metric = "evidence_coverage",
  test = "paired Wilcoxon signed-rank",
  n_pairs = nrow(coverage_wide),
  mean_delta_yes_minus_no = mean(coverage_wide$delta_yes_minus_no, na.rm = TRUE),
  median_delta_yes_minus_no = median(coverage_wide$delta_yes_minus_no, na.rm = TRUE),
  p_value = as.numeric(coverage_wilcox$p.value),
  sig = ifelse(coverage_wilcox$p.value < 0.001, "***",
    ifelse(coverage_wilcox$p.value < 0.01, "**",
      ifelse(coverage_wilcox$p.value < 0.05, "*", "ns")
    )
  ),
  stringsAsFactors = FALSE
)
readr::write_csv(coverage_test, file.path(table_dir, "dth_fig3a_evidence_coverage_paired_test.csv"))

read_judge_summary <- function(judge_label, file_name) {
  payload <- jsonlite::fromJSON(file.path(judge_dir, file_name), simplifyVector = FALSE)
  aggregate <- payload$aggregate
  metadata <- payload$metadata

  metric_rows <- dplyr::bind_rows(lapply(c("DTH_no", "DTH_yes"), function(condition) {
    metrics <- aggregate$metric_means_by_condition[[condition]]
    dplyr::bind_rows(lapply(names(metrics), function(metric) {
      data.frame(
        judge_label = judge_label,
        judge_model = as.character(metadata$judge_model %||% judge_label),
        condition = condition,
        metric = metric,
        mean_score = as.numeric(metrics[[metric]]),
        stringsAsFactors = FALSE
      )
    }))
  }))

  score_rows <- dplyr::bind_rows(lapply(c("DTH_no", "DTH_yes"), function(condition) {
    data.frame(
      judge_label = judge_label,
      judge_model = as.character(metadata$judge_model %||% judge_label),
      condition = condition,
      metric = "total_score",
      mean_score = as.numeric(aggregate$mean_score_by_condition[[condition]]),
      stringsAsFactors = FALSE
    )
  }))

  win_rows <- data.frame(
    judge_label = judge_label,
    judge_model = as.character(metadata$judge_model %||% judge_label),
    outcome = c("DTH-guided", "Tie", "Baseline"),
    win_count = c(
      as.integer(aggregate$wins$DTH_yes %||% 0),
      as.integer(aggregate$wins$tie %||% 0),
      as.integer(aggregate$wins$DTH_no %||% 0)
    ),
    win_rate = c(
      as.numeric(aggregate$win_rates$DTH_yes %||% 0),
      as.numeric(aggregate$win_rates$tie %||% 0),
      as.numeric(aggregate$win_rates$DTH_no %||% 0)
    ),
    total_pairs = as.integer(aggregate$total_rows %||% metadata$pair_count %||% NA_integer_),
    stringsAsFactors = FALSE
  )

  summary_row <- data.frame(
    judge_label = judge_label,
    judge_model = as.character(metadata$judge_model %||% judge_label),
    total_rows = as.integer(aggregate$total_rows %||% NA_integer_),
    valid_judge_rows = as.integer(aggregate$valid_judge_rows %||% NA_integer_),
    dth_yes_wins = as.integer(aggregate$wins$DTH_yes %||% 0),
    dth_no_wins = as.integer(aggregate$wins$DTH_no %||% 0),
    ties = as.integer(aggregate$wins$tie %||% 0),
    dth_yes_win_rate = as.numeric(aggregate$win_rates$DTH_yes %||% 0),
    dth_no_win_rate = as.numeric(aggregate$win_rates$DTH_no %||% 0),
    tie_rate = as.numeric(aggregate$win_rates$tie %||% 0),
    mean_score_delta_yes_minus_no = as.numeric(aggregate$mean_score_delta_yes_minus_no %||% NA_real_),
    sign_test_pvalue_yes_vs_no = as.numeric(aggregate$sign_test_pvalue_yes_vs_no %||% NA_real_),
    stringsAsFactors = FALSE
  )

  list(metrics = metric_rows, scores = score_rows, wins = win_rows, summary = summary_row)
}

judge_records <- lapply(seq_len(nrow(judge_files)), function(i) {
  read_judge_summary(judge_files$judge_label[[i]], judge_files$file_name[[i]])
})

judge_metric_means <- bind_rows(lapply(judge_records, function(x) x$metrics)) %>%
  mutate(
    condition = factor(condition, levels = condition_levels),
    condition_label = factor(condition_labels[as.character(condition)],
      levels = condition_labels[condition_levels]
    ),
    judge_label = factor(judge_label, levels = judge_files$judge_label)
  )
judge_total_scores <- bind_rows(lapply(judge_records, function(x) x$scores))
judge_win_rates <- bind_rows(lapply(judge_records, function(x) x$wins)) %>%
  mutate(
    judge_label = factor(judge_label, levels = judge_files$judge_label),
    outcome = factor(outcome, levels = c("DTH-guided", "Tie", "Baseline")),
    win_percent = 100 * win_rate,
    label = paste0(win_count, "/", total_pairs)
  )
judge_summary <- bind_rows(lapply(judge_records, function(x) x$summary))

read_judge_rows <- function(judge_label, row_file) {
  path <- file.path(judge_dir, row_file)
  lines <- readLines(path, warn = FALSE)
  lines <- lines[nzchar(trimws(lines))]
  rows <- lapply(lines, jsonlite::fromJSON, simplifyVector = FALSE)
  dplyr::bind_rows(lapply(rows, function(row) {
    yes_payload <- row$condition_payloads$DTH_yes
    no_payload <- row$condition_payloads$DTH_no
    data.frame(
      judge_label = judge_label,
      pair_id = as.character(row$pair_id %||% NA_character_),
      dth_yes_claim_boundary = as.numeric(yes_payload$claim_boundary_restraint %||% NA_real_),
      dth_no_claim_boundary = as.numeric(no_payload$claim_boundary_restraint %||% NA_real_),
      stringsAsFactors = FALSE
    )
  }))
}

claim_boundary_pairs <- bind_rows(lapply(seq_len(nrow(judge_files)), function(i) {
  read_judge_rows(judge_files$judge_label[[i]], judge_files$row_file[[i]])
})) %>%
  mutate(
    judge_label = factor(judge_label, levels = judge_files$judge_label),
    delta_yes_minus_no = dth_yes_claim_boundary - dth_no_claim_boundary
  )

claim_boundary_tests <- claim_boundary_pairs %>%
  group_by(judge_label) %>%
  group_modify(function(.x, .y) {
    test <- suppressWarnings(stats::wilcox.test(
      .x$dth_yes_claim_boundary,
      .x$dth_no_claim_boundary,
      paired = TRUE,
      exact = FALSE
    ))
    data.frame(
      n_pairs = nrow(.x),
      mean_dth_yes = mean(.x$dth_yes_claim_boundary, na.rm = TRUE),
      mean_dth_no = mean(.x$dth_no_claim_boundary, na.rm = TRUE),
      mean_delta_yes_minus_no = mean(.x$delta_yes_minus_no, na.rm = TRUE),
      positive_pairs = sum(.x$delta_yes_minus_no > 0, na.rm = TRUE),
      tied_pairs = sum(.x$delta_yes_minus_no == 0, na.rm = TRUE),
      negative_pairs = sum(.x$delta_yes_minus_no < 0, na.rm = TRUE),
      wilcoxon_p = as.numeric(test$p.value),
      stringsAsFactors = FALSE
    )
  }) %>%
  ungroup() %>%
  mutate(
    wilcoxon_p_bonferroni = pmin(wilcoxon_p * n(), 1),
    sig = ifelse(wilcoxon_p_bonferroni < 0.001, "***",
      ifelse(wilcoxon_p_bonferroni < 0.01, "**",
        ifelse(wilcoxon_p_bonferroni < 0.05, "*", "ns")
      )
    ),
    x = as.numeric(judge_label)
  )

claim_boundary_summary <- claim_boundary_pairs %>%
  select(judge_label, dth_no_claim_boundary, dth_yes_claim_boundary) %>%
  pivot_longer(
    cols = c(dth_no_claim_boundary, dth_yes_claim_boundary),
    names_to = "condition",
    values_to = "score"
  ) %>%
  mutate(
    condition = recode(
      condition,
      dth_no_claim_boundary = "DTH_no",
      dth_yes_claim_boundary = "DTH_yes"
    ),
    condition = factor(condition, levels = condition_levels),
    condition_label = factor(condition_labels[as.character(condition)],
      levels = condition_labels[condition_levels]
    ),
    judge_label = factor(judge_label, levels = judge_files$judge_label)
  ) %>%
  group_by(judge_label, condition, condition_label) %>%
  summarise(
    n = n(),
    mean_score = mean(score, na.rm = TRUE),
    sd_score = sd(score, na.rm = TRUE),
    se_score = sd_score / sqrt(n),
    .groups = "drop"
  )

claim_boundary_pair_means <- claim_boundary_pairs %>%
  group_by(pair_id) %>%
  summarise(
    dth_no_claim_boundary = mean(dth_no_claim_boundary, na.rm = TRUE),
    dth_yes_claim_boundary = mean(dth_yes_claim_boundary, na.rm = TRUE),
    delta_yes_minus_no = dth_yes_claim_boundary - dth_no_claim_boundary,
    .groups = "drop"
  )

claim_boundary_aggregate_long <- claim_boundary_pair_means %>%
  select(pair_id, dth_no_claim_boundary, dth_yes_claim_boundary) %>%
  pivot_longer(
    cols = c(dth_no_claim_boundary, dth_yes_claim_boundary),
    names_to = "condition",
    values_to = "score"
  ) %>%
  mutate(
    condition = recode(
      condition,
      dth_no_claim_boundary = "DTH_no",
      dth_yes_claim_boundary = "DTH_yes"
    ),
    condition = factor(condition, levels = condition_levels),
    condition_label = factor(condition_labels[as.character(condition)],
      levels = condition_labels[condition_levels]
    )
  )

claim_boundary_aggregate_summary <- claim_boundary_aggregate_long %>%
  group_by(condition, condition_label) %>%
  summarise(
    n = n(),
    mean_score = mean(score, na.rm = TRUE),
    sd_score = sd(score, na.rm = TRUE),
    se_score = sd_score / sqrt(n),
    .groups = "drop"
  )

claim_boundary_aggregate_wilcox <- suppressWarnings(stats::wilcox.test(
  claim_boundary_pair_means$dth_yes_claim_boundary,
  claim_boundary_pair_means$dth_no_claim_boundary,
  paired = TRUE,
  exact = FALSE
))
claim_boundary_aggregate_test <- data.frame(
  metric = "claim_boundary_restraint",
  test = "paired Wilcoxon signed-rank on pair-level judge means",
  n_pairs = nrow(claim_boundary_pair_means),
  mean_delta_yes_minus_no = mean(claim_boundary_pair_means$delta_yes_minus_no, na.rm = TRUE),
  median_delta_yes_minus_no = median(claim_boundary_pair_means$delta_yes_minus_no, na.rm = TRUE),
  p_value = as.numeric(claim_boundary_aggregate_wilcox$p.value),
  sig = ifelse(claim_boundary_aggregate_wilcox$p.value < 0.001, "***",
    ifelse(claim_boundary_aggregate_wilcox$p.value < 0.01, "**",
      ifelse(claim_boundary_aggregate_wilcox$p.value < 0.05, "*", "ns")
    )
  ),
  stringsAsFactors = FALSE
)

readr::write_csv(judge_metric_means, file.path(table_dir, "dth_fig3b_judge_metric_means.csv"))
readr::write_csv(claim_boundary_pairs, file.path(table_dir, "dth_fig3b_claim_boundary_pairs.csv"))
readr::write_csv(claim_boundary_summary, file.path(table_dir, "dth_fig3b_claim_boundary_summary.csv"))
readr::write_csv(claim_boundary_tests, file.path(table_dir, "dth_fig3b_claim_boundary_paired_tests.csv"))
readr::write_csv(claim_boundary_pair_means, file.path(table_dir, "dth_fig3b_claim_boundary_pair_means.csv"))
readr::write_csv(claim_boundary_aggregate_summary, file.path(table_dir, "dth_fig3b_claim_boundary_aggregate_summary.csv"))
readr::write_csv(claim_boundary_aggregate_test, file.path(table_dir, "dth_fig3b_claim_boundary_aggregate_paired_test.csv"))
readr::write_csv(judge_total_scores, file.path(table_dir, "dth_judge_total_score_means.csv"))
readr::write_csv(judge_win_rates, file.path(table_dir, "dth_figs3d_judge_win_rates.csv"))
readr::write_csv(judge_summary, file.path(table_dir, "dth_blind_judge_summary.csv"))

fig3a <- ggplot() +
  geom_col(
    data = coverage_summary,
    aes(x = condition_label, y = mean_coverage, fill = condition),
    # width = 0.78,
    color = "black",
    linewidth = 0.45,
    alpha = 0.8
  ) +
  geom_errorbar(
    data = coverage_summary,
    aes(
      x = condition_label,
      ymin = mean_coverage - se_coverage,
      ymax = mean_coverage + se_coverage
    ),
    width = 0.18,
    linewidth = 0.45
  ) +
  scale_fill_manual(values = condition_colors, guide = "none") +
  scale_x_discrete(limits = main_condition_order) +
  scale_y_continuous(limits = c(0, 100), breaks = seq(0, 100, 25), expand = expansion(mult = c(0, 0.03))) +
  labs(
    x = NULL,
    y = "Evidence coverage (%)"
  ) +
  base_theme
fig3a

fig3b <- ggplot(claim_boundary_aggregate_summary, aes(x = condition_label, y = mean_score, fill = condition)) +
  geom_col(
    # width = 0.78,
    color = "black",
    linewidth = 0.45,
    alpha = 0.8
  ) +
  geom_errorbar(
    aes(ymin = mean_score - se_score, ymax = mean_score + se_score),
    width = 0.18,
    linewidth = 0.42
  ) +
  annotate("segment", x = 1, xend = 2, y = 5.12, yend = 5.12, linewidth = 0.4) +
  annotate("segment", x = 1, xend = 1, y = 5.02, yend = 5.12, linewidth = 0.4) +
  annotate("segment", x = 2, xend = 2, y = 5.02, yend = 5.12, linewidth = 0.4) +
  annotate("text", x = 1.5, y = 5.25, label = claim_boundary_aggregate_test$sig[[1]], size = 3.3) +
  scale_fill_manual(values = condition_colors, guide = "none") +
  scale_x_discrete(limits = main_condition_order) +
  scale_y_continuous(limits = c(0, 5.45), breaks = 0:5, expand = expansion(mult = c(0, 0.02))) +
  labs(
    x = NULL,
    y = "Claim-boundary restraint score (0-5)"
  ) +
  base_theme
fig3b

figs3e <- ggplot(claim_boundary_summary, aes(x = judge_label, y = mean_score, fill = condition)) +
  geom_col(
    position = position_dodge(width = 0.72),
    width = 0.72,
    color = "black",
    linewidth = 0.45,
    alpha = 0.8
  ) +
  geom_errorbar(
    aes(ymin = mean_score - se_score, ymax = mean_score + se_score),
    position = position_dodge(width = 0.72),
    width = 0.16,
    linewidth = 0.42
  ) +
  geom_segment(
    data = claim_boundary_tests,
    aes(x = x - 0.24, xend = x + 0.24, y = 5.22, yend = 5.22),
    inherit.aes = FALSE,
    linewidth = 0.4
  ) +
  geom_segment(
    data = claim_boundary_tests,
    aes(x = x - 0.24, xend = x - 0.24, y = 5.12, yend = 5.22),
    inherit.aes = FALSE,
    linewidth = 0.4
  ) +
  geom_segment(
    data = claim_boundary_tests,
    aes(x = x + 0.24, xend = x + 0.24, y = 5.12, yend = 5.22),
    inherit.aes = FALSE,
    linewidth = 0.4
  ) +
  geom_text(
    data = claim_boundary_tests,
    aes(x = x, y = 5.25, label = sig),
    inherit.aes = FALSE,
    size = 3.3,
    color = "black"
  ) +
  scale_fill_manual(
    values = condition_colors,
    labels = condition_labels[condition_levels]
  ) +
  scale_y_continuous(limits = c(0, 5.45), breaks = 0:5, expand = expansion(mult = c(0, 0.02))) +
  labs(
    x = NULL,
    y = "Claim-boundary restraint score (0-5)"
  ) +
  base_theme
figs3e

figs3d <- ggplot(judge_win_rates, aes(x = judge_label, y = win_percent, fill = outcome)) +
  geom_col(width = 0.68, color = "black", linewidth = 0.35, alpha = 0.95) +
  geom_text(
    aes(label = ifelse(win_count > 0, label, "")),
    position = position_stack(vjust = 0.5),
    size = 2.8,
    color = "black"
  ) +
  scale_fill_manual(values = outcome_colors) +
  scale_y_continuous(limits = c(0, 100), breaks = seq(0, 100, 25), expand = expansion(mult = c(0, 0.02))) +
  labs(
    x = NULL,
    y = "Preference share (%)"
  ) +
  base_theme
# +
#   theme(legend.title = element_blank(), axis.text = ele)
figs3d

saveRDS(fig3a, "benchmarks/tot/fig3a.rds")
saveRDS(fig3b, "benchmarks/tot/fig3b.rds")
saveRDS(figs3e, "benchmarks/tot/figs3d.rds")
saveRDS(figs3d, "benchmarks/tot/figs3e.rds")

ggsave(file.path(out_dir, "Fig3A_DTH_EvidenceCoverage.svg"), fig3a, width = 3.7, height = 4.4, bg = "white")
ggsave(file.path(out_dir, "Fig3B_DTH_BlindJudgeRigor.svg"), fig3b, width = 3.7, height = 4.4, bg = "white")
ggsave(file.path(out_dir, "FigS3D_DTH_BlindJudgeRigorByJudge.svg"), figs3e, width = 5.6, height = 4.3, bg = "white")
ggsave(file.path(out_dir, "FigS3E_DTH_BlindJudgeWinRate.svg"), figs3d, width = 5.0, height = 4.1, bg = "white")

message("Wrote figures to: ", out_dir)
message("Wrote figure tables to: ", table_dir)
