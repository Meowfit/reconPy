import pandas as pd
import numpy as np
from fuzzywuzzy import fuzz

def recon(left_df:pd.DataFrame, right_df:pd.DataFrame, 
            left_exact_match_cols:list, right_exact_match_cols:list, 
            left_compare_cols:list, right_compare_cols:list, 
            show_left_cols:list=[], show_right_cols:list=[], 
            weight=None,
            tolerance_percentage=None,
            suffix:list=['_left', '_right'],  
            show_matching_status=True, 
            show_matching_score=False) -> pd.DataFrame:
            
    """
    reconPy: Data Reconciliation Engine

    A tool for comparing records across two dataframes.

    Usage:
        output = recon(left_df, right_df, left_exact_match_cols, right_exact_match_cols, 
                    left_compare_cols, right_compare_cols, show_left_cols, show_right_cols, 
                    weight, tolerance_percentage, suffix,
                    show_matching_status, show_matching_score)

    Parameters:
        left_df, right_df (DataFrame): Primary and secondary DataFrames for comparison.
        left_exact_match_cols, right_exact_match_cols (list): Columns for exact matching.
        left_compare_cols, right_compare_cols (list): Columns for score-based matching.

    Optional Parameters:
        show_left_cols, show_right_cols (list): Columns to display in output.
        weight (list): Weights for score calculation.
        tolerance_percentage (list): Acceptable percentage differences.
        suffix (list): Suffixes for output columns.
        show_matching_status (bool): Display matching status.
        show_matching_score (bool): Display matching score.

    For detailed documentation, refer to the full project description.
    """

    # If weighting is not provided, use equal weights
    if weight is None:
        weight = [1/len(left_compare_cols)] * len(left_compare_cols)

    if sum(n < 0 for n in weight):
        raise ValueError("weight cannot be negative")
    elif sum(n == 0 for n in weight):
        raise ValueError("weight cannot be 0")
    elif sum(weight) != 1:
        raise ValueError("the sum of weights must equal to 1")
    
    # If tolerance_percentage is not provided, use zeros
    if tolerance_percentage is None:
        tolerance_percentage = [0] * len(left_compare_cols)
    
    if sum(n < 0 for n in tolerance_percentage):
        raise ValueError("tolerance_percentage cannot be negative")
    elif sum(n > 100 for n in tolerance_percentage):
        raise ValueError("tolerance_percentage cannot > 100")

    # Validate input lengths
    if len(left_exact_match_cols) != len(right_exact_match_cols) or \
        len(left_compare_cols) != len(right_compare_cols) or \
        len(weight) != len(left_compare_cols) or \
        len(tolerance_percentage) != len(left_compare_cols):
        raise ValueError("Input lists must have the same length")

    # Validate suffix
    if len(suffix) != 2:
        raise ValueError("length of the suffix must be 2")
    else:
        suffix[0] = str(suffix[0])
        suffix[1] = str(suffix[1])
    
    if left_df.empty:
        raise ValueError("left dataframe cannot be empty")
    elif right_df.empty:
        raise ValueError("right dataframe cannot be empty")
    
    if show_matching_status not in (True, False):
        raise ValueError("show_matching_status must be True or False. Default is True")

    # Check columns
    if len(list(set(left_exact_match_cols + left_compare_cols + show_left_cols) - set(left_df.columns))) > 0:
        raise ValueError(f"Columns {list(set(left_exact_match_cols + left_compare_cols + show_left_cols) - set(left_df.columns))} do not exist in left dataframe")
    
    if len(list(set(right_exact_match_cols + right_compare_cols + show_right_cols) - set(right_df.columns))) > 0:
        raise ValueError(f"Columns {list(set(right_exact_match_cols + right_compare_cols + show_right_cols) - set(right_df.columns))} do not exist in right dataframe")

    # Create unique identifiers for each dataframe
    left_df['_left_id'] = range(len(left_df))
    right_df['_right_id'] = range(len(right_df))

    # Adding suffix for compare cols
    left_df_renamed = left_df.rename(columns={col: f"{col}{suffix[0]}" for col in left_compare_cols})
    right_df_renamed = right_df.rename(columns={col: f"{col}{suffix[1]}" for col in right_compare_cols})

    # Create a cross join of the dataframes based on exact match columns
    merged_df = pd.merge(left_df_renamed, right_df_renamed, 
                         left_on=left_exact_match_cols, 
                         right_on=right_exact_match_cols, 
                         how='outer')

    # Calculate matching scores and check tolerance
    for left_col, right_col, weight, tolerance in zip(left_compare_cols, right_compare_cols, weight, tolerance_percentage):
        left_values = merged_df[f"{left_col}{suffix[0]}"]
        right_values = merged_df[f"{right_col}{suffix[1]}"]

        if pd.api.types.is_datetime64_any_dtype(left_values):
            left_values = pd.to_numeric(left_values) / 60 / 60 / 24 / 1000000000
            right_values = pd.to_numeric(right_values) / 60 / 60 / 24 / 1000000000
            merged_df[f"{left_col}_diff"] = (left_values - right_values) 
            within_tolerance = (np.abs((left_values - right_values) / 365.25) * 100 <= tolerance) # 1% diff = 3.65 days, measuring the diff in term of number of days in a year. 
            score = np.where(within_tolerance, ((left_values - right_values) / 365.25) ** 2, np.inf)
        elif pd.api.types.is_object_dtype(left_values):
            merged_df[f"{left_col}_diff"] = np.nan
            within_tolerance = (merged_df.apply(lambda row: 100 - fuzz.ratio(str(row[f"{left_col}{suffix[0]}"]), str(row[f"{right_col}{suffix[1]}"])), axis=1) <= tolerance)
            score = np.where(within_tolerance, merged_df.apply(lambda row: 100 - fuzz.ratio(str(row[f"{left_col}{suffix[0]}"]), str(row[f"{right_col}{suffix[1]}"])), axis=1) ** 2, np.inf)
        else:
            merged_df[f"{left_col}_diff"] = (left_values - right_values) 
            within_tolerance = (np.abs((left_values - right_values) / (right_values + 0.00000001)) * 100 <= tolerance)
            score = np.where(within_tolerance, ((left_values - right_values) / (right_values + 0.00000001)) ** 2, np.inf)
    
        # Calculate weighted matching score
        merged_df[f"{left_col}_score"] = score * weight

    # Calculate total matching score
    score_columns = [f"{col}_score" for col in left_compare_cols]
    merged_df['matching_score'] = merged_df[score_columns].sum(axis=1)

    # Remove rows where any comparison column is not within tolerance
    merged_df = merged_df[merged_df['matching_score'] < np.inf]

    # Sort by total score lower score on top (best matches first)
    merged_df = merged_df.sort_values(['matching_score', '_left_id', '_right_id'], ascending=True)

    # Find the matches which has lowest total matching score
    matched_left = set()
    matched_right = set()
    matched = []

    for _, row in merged_df.iterrows():
        left_id = row['_left_id']
        right_id = row['_right_id']
        if pd.notna(left_id) and pd.notna(right_id) and (left_id not in matched_left) and (right_id not in matched_right): # Ensure each of the record is used only once
            matched_left.add(left_id)
            matched_right.add(right_id)
            matched.append(row)

    result_df = pd.DataFrame(matched)

    # Add unmatched records
    unmatched_left_result = left_df[~left_df['_left_id'].isin(matched_left)].copy()
    if not unmatched_left_result.empty: 
        for col in left_compare_cols:
            unmatched_left_result[f"{col}{suffix[0]}"] = left_df[col]
            unmatched_left_result[f"{col}{suffix[1]}"] = np.nan
            unmatched_left_result[f"{col}_diff"] = np.nan
        unmatched_left_result['matching_score'] = np.inf

    unmatched_right_result = right_df[~right_df['_right_id'].isin(matched_right)].copy()
    if not unmatched_right_result.empty: 
        for col in right_compare_cols:
            unmatched_right_result[f"{col}{suffix[0]}"] = np.nan
            unmatched_right_result[f"{col}{suffix[1]}"] = right_df[col]
            unmatched_right_result[f"{col}_diff"] = np.nan
        unmatched_right_result['matching_score'] = np.inf

    result_df = pd.concat([result_df, unmatched_left_result, unmatched_right_result], ignore_index=True)
    
    # Select columns for output
    output_columns = show_left_cols + show_right_cols

    for _, col in enumerate(right_compare_cols):
        output_columns.append(left_compare_cols[_] + suffix[0])
        output_columns.append(right_compare_cols[_] + suffix[1])
        output_columns.append(left_compare_cols[_] + "_diff")

    if show_matching_score == True:
        output_columns.append('matching_score')

    if show_matching_status == True:
        result_df['matching_status'] = np.where(result_df['matching_score'] == np.inf, 'Unmatched', np.where(result_df['matching_score'] == 0, 'Matched', 'Matched within tolerance'))
        output_columns.append('matching_status')

    return result_df[output_columns]