suppressPackageStartupMessages({
  required <- c("jsonlite", "lme4", "emmeans", "dplyr")
  missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing) > 0) {
    stop(sprintf("Missing required R packages: %s", paste(missing, collapse = ", ")))
  }
})

library(jsonlite)
library(lme4)
library(emmeans)
library(dplyr)

# -----------------------------------------------------------------------------
# Trial JSONL reader — REV5 fix: read ALL lines per file, keep the latest
# non-error row per trial_index, coerce NULL columns to NA.
# -----------------------------------------------------------------------------
read_trial_dir <- function(path) {
  files <- sort(list.files(path, pattern = "^trial_.*\\.jsonl$", full.names = TRUE))
  if (length(files) == 0) {
    stop(sprintf("No trial files found under %s", path))
  }

  all_rows <- list()
  for (file in files) {
    payload <- readLines(file, warn = FALSE)
    payload <- payload[nzchar(payload)]
    if (length(payload) == 0) next
    parsed <- lapply(payload, function(line) fromJSON(line, simplifyDataFrame = FALSE))

    # Prefer the latest non-error row per file; fall back to the last row
    # (even if it carries an error) so downstream logic can exclude it.
    keep <- NULL
    for (row in parsed) {
      err <- row$error
      has_err <- !is.null(err) && !identical(err, "") && !is.na(err)
      if (!has_err) keep <- row
    }
    if (is.null(keep)) keep <- parsed[[length(parsed)]]
    all_rows[[length(all_rows) + 1]] <- keep
  }

  if (length(all_rows) == 0) {
    stop(sprintf("No parseable rows in %s", path))
  }

  # Normalize NULL → NA and drop list-type fields that break column binding.
  normalized <- lapply(all_rows, function(r) {
    null_to_na <- function(x, default = NA) if (is.null(x)) default else x
    data.frame(
      case_id = as.character(null_to_na(r$case_id, "")),
      category = as.character(null_to_na(r$category, "")),
      lr_pair = as.character(null_to_na(r$lr_pair, "")),
      condition = as.character(null_to_na(r$condition, "")),
      model = as.character(null_to_na(r$model, "")),
      model_strength = as.character(null_to_na(r$model_strength, "weak")),
      skill_on = as.logical(null_to_na(r$skill_on, FALSE)),
      repeat_id = as.integer(null_to_na(r[["repeat"]], 1L)),
      trial_index = as.integer(null_to_na(r$trial_index, NA_integer_)),
      total_papers = as.integer(null_to_na(r$total_papers, 0L)),
      genes_coverage_pct = as.numeric(null_to_na(r$genes_coverage_pct, NA_real_)),
      pathways_coverage_pct = as.numeric(null_to_na(r$pathways_coverage_pct, NA_real_)),
      coverage_pass = as.integer(as.logical(null_to_na(r$coverage_pass, FALSE))),
      genes_coverage_pct_tagoff = as.numeric(null_to_na(r$genes_coverage_pct_tagoff, NA_real_)),
      pathways_coverage_pct_tagoff = as.numeric(null_to_na(r$pathways_coverage_pct_tagoff, NA_real_)),
      coverage_pass_tagoff = as.integer(as.logical(null_to_na(r$coverage_pass_tagoff, FALSE))),
      biomcp_latency_ms = as.numeric(null_to_na(r$biomcp_latency_ms, NA_real_)),
      biomcp_error = as.character(null_to_na(r$biomcp_error, NA_character_)),
      biomcp_paper_count_raw = as.integer(null_to_na(r$biomcp_paper_count_raw, 0L)),
      latency_s = as.numeric(null_to_na(r$latency_s, NA_real_)),
      error = as.character(null_to_na(r$error, NA_character_)),
      stringsAsFactors = FALSE
    )
  })

  df <- dplyr::bind_rows(normalized)

  # Drop error rows from statistical analysis (diagnostics only).
  n_with_errors <- sum(!is.na(df$error))
  df <- df[is.na(df$error), , drop = FALSE]
  if (nrow(df) == 0) {
    stop(sprintf("All %d rows carry an error field; nothing to analyze", n_with_errors))
  }
  attr(df, "n_error_rows_dropped") <- n_with_errors

  # Pin factor reference levels for reproducible coefficient signs.
  df$skill_on <- factor(as.character(df$skill_on), levels = c("FALSE", "TRUE"))
  df$model_strength <- factor(df$model_strength, levels = c("weak", "strong"))
  df$case_id <- as.factor(df$case_id)
  df
}

# -----------------------------------------------------------------------------
# Primary + sensitivity GLMMs, LMM secondary, LRT, simple effects.
# -----------------------------------------------------------------------------
fit_models <- function(df) {
  fit_glmer <- function(formula) {
    tryCatch(
      lme4::glmer(formula, family = binomial(), data = df),
      error = function(e) list(error = conditionMessage(e))
    )
  }

  primary <- fit_glmer(coverage_pass ~ skill_on * model_strength + (1 | case_id))
  primary_reduced <- fit_glmer(coverage_pass ~ skill_on + model_strength + (1 | case_id))
  sensitivity <- fit_glmer(coverage_pass_tagoff ~ skill_on * model_strength + (1 | case_id))

  secondary <- tryCatch(
    lme4::lmer(genes_coverage_pct ~ skill_on * model_strength + (1 | case_id), data = df),
    error = function(e) list(error = conditionMessage(e))
  )

  interaction_lrt <- tryCatch(
    anova(primary_reduced, primary),
    error = function(e) list(error = conditionMessage(e))
  )

  simple_effects <- tryCatch(
    emmeans::emmeans(primary, pairwise ~ skill_on | model_strength, type = "response"),
    error = function(e) list(error = conditionMessage(e))
  )

  list(
    primary = primary,
    primary_reduced = primary_reduced,
    sensitivity = sensitivity,
    secondary = secondary,
    interaction_lrt = interaction_lrt,
    simple_effects = simple_effects
  )
}

# -----------------------------------------------------------------------------
# Case-level bootstrap CI for the primary GLMM fixed effects.
# Uses a percentile bootstrap with n_iter resamples of case_ids.
# -----------------------------------------------------------------------------
bootstrap_ci_case_level <- function(df, n_iter = 1000, seed = 42) {
  if (!is.data.frame(df) || nrow(df) == 0) {
    return(list(skipped = "empty data frame"))
  }
  set.seed(seed)
  cases <- unique(as.character(df$case_id))
  n_cases <- length(cases)
  coef_names <- c(
    "(Intercept)",
    "skill_onTRUE",
    "model_strengthstrong",
    "skill_onTRUE:model_strengthstrong"
  )
  estimates <- matrix(NA_real_, nrow = n_iter, ncol = length(coef_names))
  colnames(estimates) <- coef_names

  for (i in seq_len(n_iter)) {
    sampled <- sample(cases, n_cases, replace = TRUE)
    boot_df <- do.call(
      rbind,
      lapply(seq_along(sampled), function(k) {
        slice <- df[as.character(df$case_id) == sampled[[k]], , drop = FALSE]
        if (nrow(slice) == 0) return(NULL)
        slice$case_id <- paste0(sampled[[k]], "_boot", k)
        slice
      })
    )
    if (is.null(boot_df) || nrow(boot_df) == 0) next
    boot_df$case_id <- as.factor(boot_df$case_id)
    fit <- tryCatch(
      suppressWarnings(
        lme4::glmer(
          coverage_pass ~ skill_on * model_strength + (1 | case_id),
          family = binomial(),
          data = boot_df,
          control = lme4::glmerControl(
            optimizer = "bobyqa", optCtrl = list(maxfun = 5000)
          )
        )
      ),
      error = function(e) NULL
    )
    if (!is.null(fit)) {
      coefs <- lme4::fixef(fit)
      for (name in names(coefs)) {
        if (name %in% colnames(estimates)) estimates[i, name] <- coefs[[name]]
      }
    }
  }

  n_success <- sum(!is.na(estimates[, 1]))
  ci <- apply(estimates, 2, function(x) {
    v <- x[!is.na(x)]
    if (length(v) == 0) return(c(lower = NA_real_, median = NA_real_, upper = NA_real_))
    setNames(
      stats::quantile(v, probs = c(0.025, 0.5, 0.975), names = FALSE),
      c("lower", "median", "upper")
    )
  })

  list(
    n_iter = n_iter,
    n_successful = n_success,
    coef_names = coef_names,
    ci_95 = ci
  )
}

# -----------------------------------------------------------------------------
# Optional power analysis via simr::powerSim. Gracefully skipped if simr is
# unavailable or if the fit is degenerate.
# -----------------------------------------------------------------------------
run_power_analysis <- function(fit, nsim = 200) {
  if (!requireNamespace("simr", quietly = TRUE)) {
    return(list(skipped = "simr package not installed"))
  }
  if (!inherits(fit, "merMod")) {
    return(list(skipped = "primary fit is not a merMod (probably failed to converge)"))
  }
  tryCatch(
    {
      sim <- simr::powerSim(
        fit,
        test = simr::fixed("skill_on:model_strength", "lr"),
        nsim = nsim,
        progress = FALSE
      )
      summ <- summary(sim)
      list(
        power = as.numeric(summ$mean),
        ci_lower = as.numeric(summ$lower),
        ci_upper = as.numeric(summ$upper),
        nsim = nsim
      )
    },
    error = function(e) list(error = conditionMessage(e))
  )
}

# -----------------------------------------------------------------------------
# Safe capture helper — produces a single-string summary even when the fit
# itself errored (so downstream JSON always has the key).
# -----------------------------------------------------------------------------
safe_capture <- function(obj) {
  if (is.list(obj) && !is.null(obj$error)) {
    return(paste("ERROR:", obj$error))
  }
  tryCatch(
    paste(capture.output(summary(obj)), collapse = "\n"),
    error = function(e) paste("ERROR:", conditionMessage(e))
  )
}

safe_print <- function(obj) {
  if (is.list(obj) && !is.null(obj$error)) {
    return(paste("ERROR:", obj$error))
  }
  tryCatch(
    paste(capture.output(print(obj)), collapse = "\n"),
    error = function(e) paste("ERROR:", conditionMessage(e))
  )
}

# -----------------------------------------------------------------------------
# P0.3 — Multi-dataset pooled GLMM + TOST equivalence (Rev 4 3-dimensional primary)
# -----------------------------------------------------------------------------
read_multi_dir <- function(dirs, labels) {
  stopifnot(length(dirs) == length(labels))
  frames <- list()
  for (i in seq_along(dirs)) {
    d <- read_trial_dir(dirs[[i]])
    d$dataset <- as.character(labels[[i]])
    d$case_id <- as.character(d$case_id)
    d$skill_on <- as.character(d$skill_on)
    d$model_strength <- as.character(d$model_strength)
    frames[[i]] <- d
  }
  combined <- dplyr::bind_rows(frames)
  combined$skill_on <- factor(combined$skill_on, levels = c("FALSE", "TRUE"))
  combined$model_strength <- factor(combined$model_strength, levels = c("weak", "strong"))
  combined$dataset <- factor(combined$dataset, levels = unique(unlist(labels)))
  combined$case_id <- as.factor(combined$case_id)
  combined
}

fit_pooled_model <- function(df) {
  safe_fit <- function(fn, formula, family = NULL) {
    tryCatch(
      if (is.null(family)) fn(formula, data = df) else fn(formula, family = family, data = df),
      error = function(e) list(error = conditionMessage(e))
    )
  }
  celltype_primary <- safe_fit(
    lme4::lmer,
    celltypes_coverage_pct ~ skill_on * model_strength + dataset + (1 | case_id)
  )
  coverage_primary <- safe_fit(
    lme4::glmer,
    coverage_pass ~ skill_on * model_strength + dataset + (1 | case_id),
    family = binomial()
  )
  df_path <- df[!is.na(df$pathways_coverage_pct), , drop = FALSE]
  pathway_secondary <- tryCatch(
    if (nrow(df_path) >= 10) {
      stats::lm(pathways_coverage_pct ~ skill_on * model_strength + dataset, data = df_path)
    } else {
      list(error = sprintf("Insufficient pathway data: n=%d", nrow(df_path)))
    },
    error = function(e) list(error = conditionMessage(e))
  )
  list(
    celltype_primary = celltype_primary,
    coverage_primary = coverage_primary,
    pathway_secondary = pathway_secondary
  )
}

fit_tost_equivalence <- function(df, margin_pp = 5) {
  ds_levels <- levels(df$dataset)
  if (!("C" %in% ds_levels) || !("B_prime" %in% ds_levels)) {
    return(list(skipped = "Both C and B_prime datasets required for TOST."))
  }
  tryCatch({
    df_sub <- df[df$dataset %in% c("C", "B_prime") & df$skill_on == "TRUE", , drop = FALSE]
    if (nrow(df_sub) < 10) {
      return(list(error = sprintf("Insufficient C+B_prime ON-arm rows: %d", nrow(df_sub))))
    }
    df_sub$dataset <- droplevels(df_sub$dataset)
    fit <- lme4::lmer(
      celltypes_coverage_pct ~ dataset + model_strength + (1 | case_id),
      data = df_sub
    )
    emm <- emmeans::emmeans(fit, ~ dataset)
    contr <- as.data.frame(pairs(emm, adjust = "none"))
    row <- contr[1, ]
    est <- as.numeric(row$estimate)
    se  <- as.numeric(row$SE)
    df_denom <- as.numeric(row$df)
    t_lower <- (est - (-margin_pp)) / se
    t_upper <- (est -  margin_pp)  / se
    p_lower <- pt(t_lower, df = df_denom, lower.tail = FALSE)
    p_upper <- pt(t_upper, df = df_denom, lower.tail = TRUE)
    p_tost  <- max(p_lower, p_upper)
    list(
      contrast = as.character(row$contrast),
      estimate_pp = est, se_pp = se, margin_pp = margin_pp,
      p_lower = p_lower, p_upper = p_upper, p_tost = p_tost,
      equivalent_at_alpha_0_05 = p_tost < 0.05
    )
  }, error = function(e) list(error = conditionMessage(e)))
}

parse_multi_dir_args <- function(args) {
  dirs <- c(); labels <- c()
  pooled <- FALSE
  n_boot <- 1000L; n_power <- 200L
  output <- NULL
  i <- 1
  while (i <= length(args)) {
    tok <- args[[i]]
    if (tok == "--results-dir") {
      dirs <- c(dirs, args[[i + 1]]); i <- i + 2
    } else if (tok == "--dataset-label") {
      labels <- c(labels, args[[i + 1]]); i <- i + 2
    } else if (tok == "--pooled") {
      pooled <- TRUE; i <- i + 1
    } else if (tok == "--n-boot") {
      n_boot <- as.integer(args[[i + 1]]); i <- i + 2
    } else if (tok == "--n-powersim") {
      n_power <- as.integer(args[[i + 1]]); i <- i + 2
    } else if (tok == "--output") {
      output <- args[[i + 1]]; i <- i + 2
    } else {
      i <- i + 1
    }
  }
  list(dirs = dirs, labels = labels, pooled = pooled,
       n_boot = n_boot, n_power = n_power, output = output)
}

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  has_flags <- any(grepl("^--", args))

  if (!has_flags) {
    # Legacy single-dir mode (backward-compat)
    if (length(args) < 2) {
      stop(
        "Usage:\n",
        "  Legacy:  Rscript harness_x_model_glmm.R <results_dir> <output_json> [n_boot] [n_powersim]\n",
        "  Pooled:  Rscript harness_x_model_glmm.R \\\n",
        "           --results-dir A --dataset-label B [--results-dir C --dataset-label D ...] \\\n",
        "           --pooled --output out.json [--n-boot N] [--n-powersim M]"
      )
    }
    results_dir <- args[[1]]
    output_json <- args[[2]]
    n_boot <- if (length(args) >= 3) as.integer(args[[3]]) else 1000L
    n_power <- if (length(args) >= 4) as.integer(args[[4]]) else 200L

    df <- read_trial_dir(results_dir)
    fits <- fit_models(df)
    boot_ci <- bootstrap_ci_case_level(df, n_iter = n_boot)
    power_sim <- run_power_analysis(fits$primary, nsim = n_power)

    payload <- list(
      mode = "single_dir_legacy",
      n = nrow(df),
      n_cases = length(unique(df$case_id)),
      n_error_rows_dropped = attr(df, "n_error_rows_dropped"),
      primary_summary = safe_capture(fits$primary),
      primary_reduced_summary = safe_capture(fits$primary_reduced),
      sensitivity_summary = safe_capture(fits$sensitivity),
      secondary_summary = safe_capture(fits$secondary),
      interaction_lrt = safe_print(fits$interaction_lrt),
      simple_effects = safe_print(fits$simple_effects),
      boot_ci = boot_ci,
      power_sim = power_sim,
      analysis_notes = c(
        "Primary endpoint: coverage_pass (tag-on, production semantics).",
        "Sensitivity endpoint: coverage_pass_tagoff (tag-off, addresses REV5 §1 critique).",
        "Factor levels pinned: skill_on = FALSE -> TRUE, model_strength = weak -> strong.",
        paste0(
          "Bootstrap: case-level resampling, n_iter = ", n_boot,
          "; power simulation nsim = ", n_power, "."
        )
      )
    )
    writeLines(
      toJSON(payload, auto_unbox = TRUE, pretty = TRUE, na = "null"),
      con = output_json
    )
    return(invisible(NULL))
  }

  # Multi-dir pooled mode (Rev 4)
  parsed <- parse_multi_dir_args(args)
  if (length(parsed$dirs) == 0) {
    stop("At least one --results-dir/--dataset-label pair is required.")
  }
  if (length(parsed$dirs) != length(parsed$labels)) {
    stop(sprintf(
      "Mismatched --results-dir (%d) / --dataset-label (%d).",
      length(parsed$dirs), length(parsed$labels)
    ))
  }
  if (is.null(parsed$output)) {
    stop("--output <out.json> is required in multi-dir mode.")
  }
  df_pooled <- read_multi_dir(parsed$dirs, parsed$labels)
  pooled_fits <- fit_pooled_model(df_pooled)

  per_dataset <- list()
  for (lbl in levels(df_pooled$dataset)) {
    df_i <- df_pooled[df_pooled$dataset == lbl, , drop = FALSE]
    if (nrow(df_i) == 0) next
    per_dataset[[lbl]] <- list(
      n = nrow(df_i),
      n_cases = length(unique(df_i$case_id)),
      celltype_mean = mean(df_i$celltypes_coverage_pct, na.rm = TRUE),
      coverage_pass_rate = mean(df_i$coverage_pass, na.rm = TRUE),
      pathway_n = sum(!is.na(df_i$pathways_coverage_pct))
    )
  }

  tost <- fit_tost_equivalence(df_pooled, margin_pp = 5)
  boot_ci <- if (parsed$pooled) {
    bootstrap_ci_case_level(df_pooled, n_iter = parsed$n_boot)
  } else {
    list(skipped = "Bootstrap only runs with --pooled")
  }

  payload <- list(
    mode = "pooled_multi_dir",
    datasets = parsed$labels,
    n_total = nrow(df_pooled),
    n_cases = length(unique(df_pooled$case_id)),
    per_dataset = per_dataset,
    celltype_primary_summary = safe_capture(pooled_fits$celltype_primary),
    coverage_glmm_summary = safe_capture(pooled_fits$coverage_primary),
    pathway_secondary_summary = safe_capture(pooled_fits$pathway_secondary),
    tost_equivalence = tost,
    boot_ci = boot_ci,
    analysis_notes = c(
      "Rev 4 primary endpoint: celltypes_coverage_pct (continuous, LMM).",
      "Coverage_pass GLMM retained as binary-endpoint robustness check.",
      "Dataset FE controls for B / B_prime / C baseline differences.",
      "TOST on C - B_prime celltype contrast with 5 pp margin (Rev 4 equivalence test)."
    )
  )
  writeLines(
    toJSON(payload, auto_unbox = TRUE, pretty = TRUE, na = "null"),
    con = parsed$output
  )
}

main()
