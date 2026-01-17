# CELINA annotation for LIANA results
# Annotates ligand-receptor pairs with cell type-specific spatially variable genes (ctSVG)
#
# Supports two data types:
# 1. Single-cell resolution (MERFISH/Xenium): Uses binary celltype matrix from adata.obs[celltype_key]
# 2. Spot-based (Visium) with deconvolution: Uses proportions from adata.obsm['compositions']

library(dplyr)
library(data.table)
library(CELINA)
library(hdf5r)
library(Matrix)

# Helper function: Convert dataframe with first column as rownames
convert_dataframe <- function(dat, preview = FALSE) {
    dat <- as.data.frame(dat)
    rownames(dat) <- dat[, 1]
    dat <- dat[, -1, drop = FALSE]
    if (preview) {
        if (ncol(dat) >= 5) {
            print(dat[1:5, 1:5])
        } else {
            print(head(dat))
        }
    }
    return(dat)
}

# Helper function: Read h5ad file using hdf5r (no Python dependency)
read_h5ad_hdf5r <- function(h5ad_path) {
    if (!requireNamespace("hdf5r", quietly = TRUE)) {
        stop("Package 'hdf5r' is required. Install with: install.packages('hdf5r')")
    }
    h5 <- hdf5r::H5File$new(h5ad_path, mode = "r")
    on.exit(h5$close_all())

    # 1. X matrix 읽기
    x_obj <- h5[["/X"]]
    if (inherits(x_obj, "H5Group")) {
        # sparse matrix (CSR format from Python anndata)
        # CSR: indptr defines row pointers, indices are column indices
        data <- h5[["/X/data"]][]
        indices <- h5[["/X/indices"]][]
        indptr <- h5[["/X/indptr"]][]
        shape <- x_obj$attr_open("shape")$read()

        # Convert CSR to triplet format (i, j, x) for proper R sparse matrix construction
        # Each row r contains elements from indptr[r] to indptr[r+1]-1
        rows <- rep(seq_len(shape[1]), diff(indptr))

        X <- Matrix::sparseMatrix(
            i = rows,
            j = indices + 1,  # 1-indexed column indices
            x = data,
            dims = shape,     # [n_obs, n_vars] = [cells, genes]
            repr = "C"        # Convert to CSC (dgCMatrix)
        )
    } else {
        # dense matrix
        X <- x_obj$read()
    }

    # 2. obs (cell metadata) 읽기
    obs_group <- h5[["/obs"]]
    obs_items <- names(obs_group)
    # _index와 실제 컬럼 분리
    obs_list <- list()
    for (n in obs_items) {
        item <- obs_group[[n]]
        if (inherits(item, "H5Group")) {
            # categorical: categories/codes 구조
            cats <- item[["categories"]][]
            codes <- item[["codes"]][]
            obs_list[[n]] <- cats[codes + 1]
        } else {
            obs_list[[n]] <- item[]
        }
    }
    obs <- as.data.frame(obs_list, stringsAsFactors = FALSE)

    # 3. var (gene metadata) 읽기
    var_group <- h5[["/var"]]
    var_items <- names(var_group)
    var_list <- list()
    for (n in var_items) {
        item <- var_group[[n]]
        if (inherits(item, "H5Group")) {
            cats <- item[["categories"]][]
            codes <- item[["codes"]][]
            var_list[[n]] <- cats[codes + 1]
        } else {
            var_list[[n]] <- item[]
        }
    }
    var <- as.data.frame(var_list, stringsAsFactors = FALSE)

    # 4. obsm reading (spatial and compositions)
    spatial <- NULL
    compositions <- NULL

    # Check if obsm group exists first before accessing children
    if (h5$exists("obsm")) {
        obsm_group <- h5[["obsm"]]
        obsm_items <- names(obsm_group)

        # Read spatial if exists
        if ("spatial" %in% obsm_items) {
            spatial <- t(obsm_group[["spatial"]]$read())
            message("Loaded spatial coordinates from obsm/spatial")
        }

        # Read compositions if exists
        if ("compositions" %in% obsm_items) {
            comp_group <- obsm_group[["compositions"]]
            comp_items <- names(comp_group)
            comp_list <- list()

            for (n in comp_items) {
                if (n == "_index") next  # skip index column, handle separately
                item <- comp_group[[n]]
                if (inherits(item, "H5Group")) {
                    # categorical data
                    cats <- item[["categories"]][]
                    codes <- item[["codes"]][]
                    comp_list[[n]] <- cats[codes + 1]
                } else {
                    comp_list[[n]] <- item[]
                }
            }

            # Only create data frame if we have actual columns
            if (length(comp_list) > 0) {
                # Use check.names = FALSE to preserve original column names with spaces/special chars
                compositions <- as.data.frame(comp_list, stringsAsFactors = FALSE, check.names = FALSE)

                # Restore original column order from 'column-order' attribute
                # HDF5 group keys are returned in alphabetical order, but anndata stores
                # the original column order in this attribute
                if (comp_group$attr_exists("column-order")) {
                    col_order <- comp_group$attr_open("column-order")$read()
                    # Handle byte strings if needed
                    if (length(col_order) > 0 && is.raw(col_order[1])) {
                        col_order <- sapply(col_order, rawToChar)
                    }
                    # Reorder columns to match original order
                    valid_cols <- col_order[col_order %in% names(compositions)]
                    if (length(valid_cols) > 0) {
                        compositions <- compositions[, valid_cols, drop = FALSE]
                        message("Restored original column order from 'column-order' attribute")
                    }
                }

                # Set rownames from _index if available
                if ("_index" %in% comp_items) {
                    idx <- comp_group[["_index"]][]
                    # Handle potential byte strings
                    if (length(idx) > 0 && is.raw(idx[1])) {
                        idx <- sapply(idx, rawToChar)
                    }
                    rownames(compositions) <- as.character(idx)
                }
                message("Loaded cell type compositions from obsm/compositions")
            }
        }
    }

    # Informational messages for missing data
    if (is.null(spatial)) {
        message("Note: No spatial coordinates found in obsm/spatial")
    }
    if (is.null(compositions)) {
        message("Note: No cell type compositions found in obsm/compositions")
    }

    # 5. Dimension validation and auto-correction (BEFORE rownames assignment)
    n_obs <- nrow(obs)
    n_vars <- nrow(var)
    x_dims <- dim(X)

    # Debug output
    message(sprintf("Dimension check: X=[%d, %d], obs=%d rows, var=%d rows",
                    x_dims[1], x_dims[2], n_obs, n_vars))

    # Check if X needs to be transposed
    # X should be [n_obs, n_vars] = [cells, genes]
    if (x_dims[1] == n_vars && x_dims[2] == n_obs) {
        message("Auto-transposing X matrix from [genes x cells] to [cells x genes]")
        X <- t(X)
        x_dims <- dim(X)
    } else if (x_dims[1] != n_obs || x_dims[2] != n_vars) {
        warning(sprintf("Dimension mismatch: X=[%d, %d] but expected [%d, %d]",
                        x_dims[1], x_dims[2], n_obs, n_vars))
    }

    # 6. Safe rownames/colnames assignment with length checks
    obs_idx_col <- intersect(c("_index", "X_index"), names(obs))[1]
    var_idx_col <- intersect(c("_index", "X_index"), names(var))[1]

    if (!is.na(obs_idx_col) && length(obs[[obs_idx_col]]) == nrow(X)) {
        rownames(X) <- obs[[obs_idx_col]]  # cell names to rows
    } else if (!is.na(obs_idx_col)) {
        warning(sprintf("Cannot set rownames: obs index has %d entries but X has %d rows",
                        length(obs[[obs_idx_col]]), nrow(X)))
    }

    if (!is.na(var_idx_col) && length(var[[var_idx_col]]) == ncol(X)) {
        colnames(X) <- var[[var_idx_col]]  # gene names to columns
    } else if (!is.na(var_idx_col)) {
        warning(sprintf("Cannot set colnames: var index has %d entries but X has %d cols",
                        length(var[[var_idx_col]]), ncol(X)))
    }

    message(sprintf("Loaded h5ad: %d cells x %d genes", nrow(X), ncol(X)))

    # Return cells x genes matrix (no transpose needed now)
    list(
        X = X,
        obs = obs,
        var = var,
        obsm = list(
            spatial = spatial,
            compositions = compositions
        )
    )
}

# Helper function: Create cell type binary matrix (for single-cell data)
make_celltype_mat <- function(celltype_annotation) {
    celltype_mat <- matrix(0, length(celltype_annotation), length(unique(celltype_annotation)))
    celltype_names <- names(table(celltype_annotation))

    for (i in seq_along(celltype_names)) {
        celltypename <- celltype_names[i]
        celltype_mat[which(celltype_annotation == celltypename), i] <- 1
    }
    colnames(celltype_mat) <- celltype_names
    return(celltype_mat)
}

# Helper function: Prepare celltype matrix for Visium data using compositions
# Returns transposed matrix (celltypes x spots) for CELINA
prepare_visium_celltype_mat <- function(compositions) {
    # compositions is a data.frame with spots as rows and cell types as columns
    # CELINA expects (celltypes x spots) format
    celltype_mat <- t(as.matrix(compositions))
    return(celltype_mat)
}

#' Run ct-SVG annotation for LIANA results
#'
#' Supports two data types:
#' 1. Single-cell resolution (MERFISH/Xenium): Uses binary celltype matrix from adata.obs[celltype_key]
#' 2. Spot-based (Visium) with deconvolution: Uses proportions from adata.obsm['compositions']
#'
#' For Visium data, cell type proportions (0-1 values) are used directly instead of binary matrix.
#' Cell type filtering for Visium uses total proportion across spots rather than cell counts.
#'
#' @param h5ad_path Path to AnnData h5ad file
#' @param res_dir Result directory containing sig_liana.csv
#' @param celltype_key Column name for cell type annotation in adata$obs.
#'                     Required for single-cell data (MERFISH, Xenium).
#'                     Set to NULL for Visium data to use compositions.
#' @param data_type Data type: "auto" (auto-detect), "single_cell", or "visium".
#'                  Default "auto" detects based on presence of compositions in obsm.
#' @param adj_pval Whether to apply FDR correction (default: FALSE)
#' @param p_th P-value threshold (default: 0.05)
#' @param nthreads Number of threads for parallel processing (default: 10)
#' @param kernel_approximation Whether to use kernel approximation (default: TRUE for large data)
#' @param min_celltype_prop Minimum cell type proportion filter (default: 0.01).
#'                          For single-cell: filters cell types with < (n_cells * min_celltype_prop) cells.
#'                          For Visium: filters cell types with total proportion < (n_spots * min_celltype_prop).
#'
#' @return data.frame with ligand_ctSVG and receptor_ctSVG annotations
#' @export
#'
#' @examples
#' # Single-cell data (MERFISH/Xenium)
#' run_celina_annotation(
#'     h5ad_path = "data.h5ad",
#'     res_dir = "results",
#'     celltype_key = "cell_type",
#'     data_type = "single_cell"
#' )
#'
#' # Visium data with deconvolution
#' run_celina_annotation(
#'     h5ad_path = "visium_data.h5ad",
#'     res_dir = "results",
#'     celltype_key = NULL,
#'     data_type = "visium"
#' )
#'
#' # Auto-detect data type
#' run_celina_annotation(
#'     h5ad_path = "data.h5ad",
#'     res_dir = "results",
#'     data_type = "auto"
#' )
run_celina_annotation <- function(
    h5ad_path,
    res_dir,
    celltype_key = NULL,
    data_type = "auto",
    adj_pval = FALSE,
    p_th = 0.05,
    nthreads = 10,
    kernel_approximation = TRUE,
    min_celltype_prop = 0.01
) {
    # 1. Load h5ad data (using hdf5r, no Python dependency)
    message("Loading h5ad file: ", h5ad_path)
    adata <- read_h5ad_hdf5r(h5ad_path)

    # 2. Determine data type
    has_compositions <- !is.null(adata$obsm$compositions)
    has_celltype_key <- !is.null(celltype_key) && celltype_key %in% names(adata$obs)

    if (data_type == "auto") {
        if (has_compositions) {
            detected_type <- "visium"
            message("Auto-detected data type: Visium (found compositions in obsm)")
        } else if (has_celltype_key) {
            detected_type <- "single_cell"
            message("Auto-detected data type: Single-cell (using celltype_key: ", celltype_key, ")")
        } else {
            stop("Cannot auto-detect data type. Either:\n",
                 "  - Provide celltype_key parameter for single-cell data\n",
                 "  - Ensure adata.obsm['compositions'] exists for Visium data")
        }
    } else {
        detected_type <- data_type
        message("Using specified data type: ", detected_type)
    }

    # Validate data type requirements
    if (detected_type == "visium" && !has_compositions) {
        stop("Visium mode requires compositions in adata.obsm['compositions']")
    }
    if (detected_type == "single_cell" && !has_celltype_key) {
        stop("Single-cell mode requires celltype_key. Provide celltype_key parameter or check column name in adata.obs")
    }
    

    
    # 3. Prepare data based on data type
    data_use <- list()
    data_use$count_use <- t(adata$X)  # genes x spots/cells
    data_use$location_coord <- adata$obsm$spatial
    rownames(data_use$location_coord) <- colnames(data_use$count_use)

    if (detected_type == "visium") {
        # VISIUM MODE: Use cell type proportions directly
        message("Preparing Visium data with cell type proportions...")

        # Get compositions from obsm (spots x celltypes) and transpose to (celltypes x spots)
        data_use$celltype_proportion <- prepare_visium_celltype_mat(adata$obsm$compositions)

        # Ensure column names match between count matrix and celltype proportion matrix
        if (!is.null(rownames(adata$obsm$compositions))) {
            colnames(data_use$celltype_proportion) <- rownames(adata$obsm$compositions)
        } else {
            colnames(data_use$celltype_proportion) <- colnames(data_use$count_use)
        }

        n_spots <- ncol(data_use$count_use)
        n_celltypes <- nrow(data_use$celltype_proportion)

        # Verify dimensions
        if (ncol(data_use$celltype_proportion) != n_spots) {
            stop("Spot count mismatch: celltype proportion matrix has ", ncol(data_use$celltype_proportion),
                 " columns but count matrix has ", n_spots, " spots")
        }
        message("Visium data dimensions: ", n_spots, " spots, ", nrow(data_use$count_use), " genes, ", n_celltypes, " cell types")

        # Create CELINA object with proportion matrix
        message("Creating CELINA object for Visium...")
        Obj <- Create_Celina_Object(
            celltype_mat = data_use$celltype_proportion,  # Already in (celltypes x spots) format
            gene_expression_mat = as.matrix(data_use$count_use),
            location = as.matrix(data_use$location_coord),
            covariates = NULL,
            project = "celina_visium_analysis"
        )

        # Filter cell types by total proportion across spots
        # For Visium: use rowSums (sum of proportions across all spots)
        celltype_total_prop <- rowSums(data_use$celltype_proportion)
        threshold <- n_spots * min_celltype_prop
        filtered_cell_types <- rownames(data_use$celltype_proportion)[celltype_total_prop > threshold]
        message("Cell type filtering (Visium): threshold = ", round(threshold, 2),
                " (n_spots * ", min_celltype_prop, ")")

    } else {
        # SINGLE-CELL MODE: Create binary celltype matrix
        message("Preparing single-cell data with binary celltype matrix...")

        data_use$celltype_annotation <- adata$obs[, celltype_key]
        data_use$celltype <- make_celltype_mat(data_use$celltype_annotation)
        rownames(data_use$celltype) <- colnames(data_use$count_use)

        n_cells <- ncol(data_use$count_use)

        # Verify dimensions
        if (nrow(data_use$celltype) != n_cells) {
            stop("Cell count mismatch: celltype matrix has ", nrow(data_use$celltype),
                 " rows but count matrix has ", n_cells, " columns")
        }
        if (nrow(data_use$location_coord) != n_cells) {
            stop("Cell count mismatch: location matrix has ", nrow(data_use$location_coord),
                 " rows but count matrix has ", n_cells, " columns")
        }
        message("Single-cell data dimensions: ", n_cells, " cells, ", nrow(data_use$count_use), " genes")

        # Create CELINA object with binary matrix (transposed to celltypes x cells)
        message("Creating CELINA object for single-cell...")
        Obj <- Create_Celina_Object(
            celltype_mat = t(data_use$celltype),  # Transpose to (celltypes x cells)
            gene_expression_mat = as.matrix(data_use$count_use),
            location = as.matrix(data_use$location_coord),
            covariates = NULL,
            project = "celina_singlecell_analysis"
        )

        # Filter cell types by cell count
        filtered_cell_types <- colnames(data_use$celltype)[
            which(colSums(data_use$celltype) > (nrow(data_use$celltype) * min_celltype_prop))
        ]
        message("Cell type filtering (single-cell): threshold = ", round(n_cells * min_celltype_prop, 0),
                " cells (n_cells * ", min_celltype_prop, ")")
    }

    message("Filtered cell types (", length(filtered_cell_types), "): ", paste(filtered_cell_types, collapse = ", "))

    # 4. Load sig_liana.csv
    liana_path <- file.path(res_dir, "sig_liana.csv")
    message("Loading LIANA results: ", liana_path)
    res_liana <- fread(liana_path) %>% convert_dataframe()
    tot_lr_genes <- unique(c(res_liana$ligand, res_liana$receptor))
    message("Total L-R genes: ", length(tot_lr_genes))

    # 5. Set genes list and optionally preprocess
    if (detected_type == "visium") {
        # VISIUM MODE: Skip preprocess_input, set genes_list directly
        # This follows the CELINA tutorial for Lung (Visium) data
        message("Setting genes list directly for Visium data (skipping scRNA preprocessing)...")

        # For Visium, we set genes_list directly with all L-R genes for each cell type
        genes_list <- lapply(seq_along(filtered_cell_types), function(x) tot_lr_genes)
        names(genes_list) <- filtered_cell_types
        Obj@genes_list <- genes_list

        message("Genes list set for ", length(filtered_cell_types), " cell types with ",
                length(tot_lr_genes), " L-R genes each")

    } else {
        # SINGLE-CELL MODE: Use preprocess_input with scRNA reference
        message("Preprocessing single-cell data with scRNA reference...")

        Obj <- preprocess_input(
            Obj,
            cell_types_to_test = filtered_cell_types,
            scRNA_count = as.matrix(data_use$count_use),
            sc_cell_type_labels = data_use$celltype_annotation,
            threshold = 5e-5
        )

        # Filter genes_list to only include L-R genes present in the preprocessed list
        genes_list <- lapply(Obj@genes_list, function(sel) {
            sel[sel %in% tot_lr_genes]
        })
        names(genes_list) <- filtered_cell_types
        Obj@genes_list <- genes_list

        message("Genes list filtered to L-R genes for ", length(filtered_cell_types), " cell types")
    }

    # 6. Run CELINA analysis
    message("Calculating kernel (approximation = ", kernel_approximation, ")...")
    Obj <- Calculate_Kernel(Obj, approximation = kernel_approximation)

    message("Testing interactions with ", nthreads, " threads...")
    Obj <- Testing_interaction_all(Obj, celltype_to_test = filtered_cell_types, num_cores = nthreads)

    # 7. Extract significant genes per cell type
    res_celina <- lapply(Obj@result, function(sel) {
        if (adj_pval) {
            sel$fdr <- p.adjust(sel[, ncol(sel)], method = "fdr")
            rownames(sel[sel$fdr < p_th, ])
        } else {
            rownames(sel[sel[, 1] < p_th, , drop = FALSE])
        }
    })

    # 8. Annotate ligand/receptor with ctSVG
    res_liana$ligand_ctSVG <- ""
    res_liana$receptor_ctSVG <- ""

    for (i in seq_along(res_celina)) {
        sel <- res_celina[[i]]
        sel_ctname <- names(res_celina)[i]

        # Annotate ligand
        idx_ligand <- which(res_liana$ligand %in% sel)
        res_liana$ligand_ctSVG[idx_ligand] <- ifelse(
            res_liana$ligand_ctSVG[idx_ligand] == "",
            sel_ctname,
            paste0(res_liana$ligand_ctSVG[idx_ligand], ";", sel_ctname)
        )

        # Annotate receptor
        idx_receptor <- which(res_liana$receptor %in% sel)
        res_liana$receptor_ctSVG[idx_receptor] <- ifelse(
            res_liana$receptor_ctSVG[idx_receptor] == "",
            sel_ctname,
            paste0(res_liana$receptor_ctSVG[idx_receptor], ";", sel_ctname)
        )
    }

    # 9. Save results
    output_path <- file.path(res_dir, "anno_sig_liana.csv")
    message("Saving results to: ", output_path)
    fwrite(res_liana, output_path)

    message("CELINA annotation complete!")
    message("Data type: ", detected_type)
    message("Cell types tested: ", length(filtered_cell_types))
    message("Output: ", output_path)

    return(res_liana)
}
