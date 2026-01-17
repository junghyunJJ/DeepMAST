import pandas as pd
import liana as li
import omnipath as op
import decoupler as dc


def make_unique_by_interaction(df, interaction_col='interaction', source_col='source'):
    """
    Make DataFrame unique by interaction, concatenating sources.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Input dataframe
    interaction_col : str
        Column name for interactions
    source_col : str
        Column name for sources to concatenate
    
    Returns:
    --------
    pd.DataFrame : Unique dataframe
    """
    # Check if columns exist
    if interaction_col not in df.columns:
        raise ValueError(f"Column '{interaction_col}' not found")
    if source_col not in df.columns:
        raise ValueError(f"Column '{source_col}' not found")

    # Group and aggregate
    result = df.groupby(interaction_col).agg({
        source_col: lambda x: ';'.join(x.dropna().astype(str).unique())
    })

    # Add other columns if they exist
    for col in df.columns:
        if col not in [interaction_col, source_col]:
            if col not in result.columns:
                if df[col].dtype == 'object':
                    result[col] = df.groupby(interaction_col)[col].apply(
                        lambda x: ';'.join(x.dropna().astype(str).unique()) if
                        len(x.dropna().unique()) > 1 else x.iloc[0]
                    )
                else:
                    result[col] = df.groupby(interaction_col)[col].first()

    return result.reset_index()


def annotate_lr_interactions(sig_liana_CCI, save_path=None, verbose=True):
    """
    Annotate ligand-receptor interactions with progeny pathways and diseases.
    
    This function takes sig_liana_CCI results and annotates them with:
    - Progeny pathway associations
    - DisGeNet disease associations
    
    Parameters:
    -----------
    sig_liana_CCI : pd.DataFrame
        DataFrame with CCI results containing 'liana_interaction' column
    save_path : str, optional
        Path to save the annotated results
    verbose : bool
        Whether to print progress messages (default: True)
        
    Returns:
    --------
    pd.DataFrame : Final dataframe with all annotations including:
        - Original CCI columns (source, target, ligand, receptor, etc.)
        - progeny: Associated pathways (semicolon-separated)
        - disease: Associated diseases (semicolon-separated)
    """
    
    # 1. Validate input
    if not isinstance(sig_liana_CCI, pd.DataFrame):
        raise TypeError("sig_liana_CCI must be a pandas DataFrame")
    
    if 'liana_interaction' not in sig_liana_CCI.columns:
        raise ValueError("sig_liana_CCI must contain 'liana_interaction' column")
    
    # Work with a copy to avoid modifying the original
    sig_liana_CCI = sig_liana_CCI.copy()
    
    # 2. Generate Progeny pathway annotations
    if verbose:
        print("Generating Progeny pathway annotations...")
    
    progeny = dc.op.progeny()
    lr_progeny = li.rs.generate_lr_geneset(
        sig_liana_CCI, 
        progeny, 
        lr_sep="^"
    )[['source', 'interaction']]
    lr_progeny = lr_progeny.drop_duplicates().sort_values("interaction")
    

    # Make progeny unique by interaction
    lr_progeny_unique = make_unique_by_interaction(lr_progeny)
    lr_progeny_unique = lr_progeny_unique.rename(columns={
        'interaction': 'interaction', 
        'source': 'progeny'
    })
    
    if verbose:
        print(f"  Found {len(lr_progeny_unique)} unique interactions with Progeny annotations")
    
    # 3. Generate DisGeNet disease annotations
    if verbose:
        print("Generating DisGeNet disease annotations...")
    
    diseases = op.requests.Annotations.get(resources=['DisGeNet'])
    diseases = diseases[['genesymbol', 'label', 'value']]
    diseases = diseases.pivot_table(
        index='genesymbol',
        columns='label', 
        values='value',
        aggfunc=lambda x: '; '.join(x)
    ).reset_index()
    
    diseases = diseases[['genesymbol', 'disease']]
    diseases['disease'] = diseases['disease'].str.split('; ')
    diseases = diseases.explode('disease')
    
    # Generate LR disease associations
    lr_diseases = li.rs.generate_lr_geneset(
        sig_liana_CCI, 
        diseases,
        source='disease', 
        target='genesymbol', 
        weight=None
    )
    lr_diseases = lr_diseases.drop_duplicates().sort_values("interaction")
    
    # Make diseases unique by interaction
    lr_diseases_unique = make_unique_by_interaction(
        lr_diseases, 
        interaction_col='interaction', 
        source_col='disease'
    )
    
    if verbose:
        print(f"  Found {len(lr_diseases_unique)} unique interactions with DisGeNet annotations")
    
    # 4. Merge all annotations
    if verbose:
        print("Merging annotations...")
    
    # Merge with progeny
    merged_df = sig_liana_CCI.merge(
        lr_progeny_unique,
        left_on='liana_interaction',
        right_on='interaction',
        how='left',
        suffixes=('', '_progeny')
    )
    
    # Remove duplicate interaction column if exists
    if 'interaction' in merged_df.columns:
        merged_df = merged_df.drop(columns=['interaction'])
    
    # Merge with diseases
    final_df = merged_df.merge(
        lr_diseases_unique,
        left_on='liana_interaction',
        right_on='interaction',
        how='left',
        suffixes=('', '_diseases')
    )
    
    # Remove duplicate interaction column if exists
    if 'interaction' in final_df.columns:
        final_df = final_df.drop(columns=['interaction'])
    
    # 5. Summary statistics
    if verbose:
        print("\nAnnotation Summary:")
        print(f"  Total CCI interactions: {len(final_df)}")
        
        with_progeny = final_df['progeny'].notna().sum()
        print(f"  With Progeny annotations: {with_progeny} ({with_progeny/len(final_df)*100:.1f}%)")
        
        with_diseases = final_df['disease'].notna().sum()
        print(f"  With Disease annotations: {with_diseases} ({with_diseases/len(final_df)*100:.1f}%)")
        
        with_both = (final_df['progeny'].notna() & final_df['disease'].notna()).sum()
        print(f"  With both annotations: {with_both} ({with_both/len(final_df)*100:.1f}%)")
    
    # 6. Save if requested
    if save_path:
        final_df.to_csv(save_path, index=False)
        if verbose:
            print(f"\nSaved annotated results to: {save_path}")
    
    return final_df


def get_lr_annotations(sig_liana_cci, annotation_type='both', verbose=True):
    """
    Get specific type of LR annotations.
    
    Parameters:
    -----------
    sig_liana_cci : pd.DataFrame
        CCI dataframe with liana_interaction column
    annotation_type : str
        Type of annotation: 'progeny', 'disease', or 'both'
    verbose : bool
        Whether to print progress messages
        
    Returns:
    --------
    pd.DataFrame : Dataframe with requested annotations
    """
    
    if annotation_type == 'progeny':
        if verbose:
            print("Generating Progeny pathway annotations only...")
        
        progeny = dc.op.progeny()
        lr_progeny = li.rs.generate_lr_geneset(
            sig_liana_cci, 
            progeny, 
            lr_sep="^"
        )[['source', 'interaction']]
        lr_progeny = lr_progeny.drop_duplicates().sort_values("interaction")
        
        lr_progeny_unique = make_unique_by_interaction(lr_progeny)
        lr_progeny_unique = lr_progeny_unique.rename(columns={'source': 'progeny'})
        
        return lr_progeny_unique
        
    elif annotation_type == 'disease':
        if verbose:
            print("Generating DisGeNet disease annotations only...")
        
        diseases = op.requests.Annotations.get(resources=['DisGeNet'])
        diseases = diseases[['genesymbol', 'label', 'value']]
        diseases = diseases.pivot_table(
            index='genesymbol',
            columns='label', 
            values='value',
            aggfunc=lambda x: '; '.join(x)
        ).reset_index()
        
        diseases = diseases[['genesymbol', 'disease']]
        diseases['disease'] = diseases['disease'].str.split('; ')
        diseases = diseases.explode('disease')
        
        lr_diseases = li.rs.generate_lr_geneset(
            sig_liana_cci, 
            diseases,
            source='disease', 
            target='genesymbol', 
            weight=None
        )
        lr_diseases = lr_diseases.drop_duplicates().sort_values("interaction")
        
        lr_diseases_unique = make_unique_by_interaction(
            lr_diseases, 
            interaction_col='interaction', 
            source_col='disease'
        )
        
        return lr_diseases_unique
        
    else:  # both
        return annotate_lr_interactions(sig_liana_cci, verbose=verbose)