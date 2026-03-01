"""
valuation.py - Calculate player fantasy value using z-scores

Z-SCORES EXPLAINED:
A z-score tells you how many standard deviations a value is from the average.
- A z-score of 0 means average
- A z-score of +1 means one standard deviation above average (better than ~84% of players)
- A z-score of +2 means two standard deviations above average (better than ~97% of players)
- A z-score of -1 means one standard deviation below average

For fantasy baseball, we calculate z-scores for each stat category, then sum them up.
A player who is +1.5 in HR and +1.0 in RBI has a total z-score of +2.5 for those categories.

IMPORTANT: For ERA and WHIP, LOWER is better, so we flip the sign.
"""

import pandas as pd
import numpy as np


def calculate_hitter_zscores(hitters_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate z-scores for hitter stats.

    Our hitting categories: R, HR, RBI, SB, OBP

    Args:
        hitters_df: DataFrame with columns Name, PA, R, HR, RBI, SB, OBP

    Returns:
        DataFrame with z-scores for each category plus total value
    """
    df = hitters_df.copy()

    # The stat categories we care about
    counting_stats = ['R', 'HR', 'RBI', 'SB']  # More is better
    rate_stats = ['OBP']  # Also more is better

    # Calculate z-scores for each category
    # Z-score formula: (value - mean) / standard_deviation
    for stat in counting_stats + rate_stats:
        if stat not in df.columns:
            print(f"Warning: Missing stat column {stat}")
            continue

        mean = df[stat].mean()
        std = df[stat].std()

        # Avoid division by zero if all values are the same
        if std == 0:
            df[f'{stat}_z'] = 0
        else:
            df[f'{stat}_z'] = (df[stat] - mean) / std

    # Sum up all z-scores for total value
    z_columns = [col for col in df.columns if col.endswith('_z')]
    df['total_z'] = df[z_columns].sum(axis=1)

    # Convert z-score to dollar value for easier interpretation
    # We'll use a simple scale: league total budget of $260 per team
    # With 15 teams, that's $3900 total. About 65% goes to hitters = $2535 for hitters
    # With ~180 draftable hitters, average is about $14 per hitter
    # We'll scale z-scores so average player = ~$1 and stars = ~$40
    df['dollar_value'] = (df['total_z'] * 5) + 10  # Adjust multiplier as needed

    return df


def calculate_pitcher_zscores(pitchers_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate z-scores for pitcher stats.

    Our pitching categories: W, SV, K, ERA, WHIP

    Note: ERA and WHIP are "negative" stats - lower is better.
    We flip the sign so that good (low) ERA/WHIP = positive z-score.
    """
    df = pitchers_df.copy()

    # Positive stats (more is better)
    positive_stats = ['W', 'SV', 'K']

    # Negative stats (lower is better) - we'll flip these
    negative_stats = ['ERA', 'WHIP']

    # Calculate z-scores for positive stats
    for stat in positive_stats:
        if stat not in df.columns:
            print(f"Warning: Missing stat column {stat}")
            continue

        mean = df[stat].mean()
        std = df[stat].std()

        if std == 0:
            df[f'{stat}_z'] = 0
        else:
            df[f'{stat}_z'] = (df[stat] - mean) / std

    # Calculate z-scores for negative stats (flip the sign)
    for stat in negative_stats:
        if stat not in df.columns:
            print(f"Warning: Missing stat column {stat}")
            continue

        mean = df[stat].mean()
        std = df[stat].std()

        if std == 0:
            df[f'{stat}_z'] = 0
        else:
            # FLIP THE SIGN: lower than average = positive z-score
            df[f'{stat}_z'] = (mean - df[stat]) / std

    # Sum up all z-scores
    z_columns = [col for col in df.columns if col.endswith('_z')]
    df['total_z'] = df[z_columns].sum(axis=1)

    # Convert to dollar value
    df['dollar_value'] = (df['total_z'] * 5) + 8

    return df


def combine_player_values(hitters_df: pd.DataFrame, pitchers_df: pd.DataFrame) -> pd.DataFrame:
    """
    Combine hitter and pitcher valuations into a single player pool.

    Args:
        hitters_df: DataFrame with hitter z-scores and dollar values
        pitchers_df: DataFrame with pitcher z-scores and dollar values

    Returns:
        Combined DataFrame with all players and their values
    """
    # Add player type column
    hitters = hitters_df.copy()
    pitchers = pitchers_df.copy()

    hitters['player_type'] = 'Hitter'
    pitchers['player_type'] = 'Pitcher'

    # Standardize column names for combining
    # Keep: Name, Team, total_z, dollar_value, player_type
    hitter_cols = ['Name', 'Team', 'total_z', 'dollar_value', 'player_type']
    if 'PA' in hitters.columns:
        hitter_cols.insert(2, 'PA')

    pitcher_cols = ['Name', 'Team', 'total_z', 'dollar_value', 'player_type']
    if 'IP' in pitchers.columns:
        pitcher_cols.insert(2, 'IP')

    # Only keep columns that exist
    hitter_cols = [c for c in hitter_cols if c in hitters.columns]
    pitcher_cols = [c for c in pitcher_cols if c in pitchers.columns]

    hitters_slim = hitters[hitter_cols]
    pitchers_slim = pitchers[pitcher_cols]

    # Rename PA/IP to 'playing_time' for consistency
    if 'PA' in hitters_slim.columns:
        hitters_slim = hitters_slim.rename(columns={'PA': 'playing_time'})
    if 'IP' in pitchers_slim.columns:
        pitchers_slim = pitchers_slim.rename(columns={'IP': 'playing_time'})

    # Combine
    combined = pd.concat([hitters_slim, pitchers_slim], ignore_index=True)

    # Sort by dollar value descending
    combined = combined.sort_values('dollar_value', ascending=False)

    return combined


def display_top_players(players_df: pd.DataFrame, n: int = 25) -> None:
    """
    Display the top N players by value in a nice format.
    """
    print(f"\n{'='*60}")
    print(f"  TOP {n} PLAYERS BY PROJECTED VALUE")
    print(f"{'='*60}")
    print(f"{'Rank':<5} {'Player':<25} {'Type':<8} {'Value':>8} {'Z-Score':>8}")
    print(f"{'-'*60}")

    for i, (_, row) in enumerate(players_df.head(n).iterrows(), 1):
        player_type = row['player_type'][:3]  # 'Hit' or 'Pit'
        print(f"{i:<5} {row['Name']:<25} {player_type:<8} ${row['dollar_value']:>6.1f} {row['total_z']:>8.2f}")

    print(f"{'='*60}\n")


if __name__ == '__main__':
    # Test the valuation with sample data
    from data_loader import load_hitter_projections, load_pitcher_projections
    from pathlib import Path

    data_dir = Path(__file__).parent.parent / 'data' / 'projections'

    print("Testing valuation engine with sample data...")

    # Load sample projections
    hitters = load_hitter_projections(data_dir / 'sample_hitters.csv')
    pitchers = load_pitcher_projections(data_dir / 'sample_pitchers.csv')

    # Calculate z-scores
    hitters_valued = calculate_hitter_zscores(hitters)
    pitchers_valued = calculate_pitcher_zscores(pitchers)

    # Combine and display
    all_players = combine_player_values(hitters_valued, pitchers_valued)
    display_top_players(all_players, n=30)
