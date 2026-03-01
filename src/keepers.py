"""
keepers.py - Keeper value calculation and recommendations

KEEPER VALUE EXPLAINED:
Keeper value = how much better a player is than what you'd "pay" to keep them.

If a player is worth $30 and costs you a Round 5 pick (roughly $20 value),
your "surplus" or "keeper value" is $10. That's what you gain by keeping them
vs. drafting someone else at that spot.

Formula: Keeper Value = Projected Dollar Value - Draft Cost Value

The higher the keeper value, the better the keeper.
"""

import pandas as pd
import numpy as np


# Draft pick value curve - how much each round is "worth"
# These values roughly match typical auction values for each draft slot
# In a 25-round snake draft with 15 teams, there are 375 total picks
# Round 1 picks are worth the most, declining each round
DRAFT_ROUND_VALUES = {
    1: 40,   # Elite players
    2: 32,
    3: 26,
    4: 22,
    5: 19,
    6: 16,
    7: 14,
    8: 12,
    9: 10,
    10: 9,
    11: 8,
    12: 7,
    13: 6,
    14: 5,
    15: 4,
    16: 4,
    17: 3,
    18: 3,   # Undrafted player value
    19: 2,
    20: 2,
    21: 2,
    22: 1,
    23: 1,
    24: 1,
    25: 1,
}


def get_draft_round_value(round_num: int) -> float:
    """
    Get the dollar value of a draft pick in a given round.

    Args:
        round_num: Draft round (1-25, capped at 25)

    Returns:
        Dollar value of that pick
    """
    # Cap at round 1 (can't have negative rounds)
    round_num = max(1, round_num)
    # Cap at round 25
    round_num = min(25, round_num)

    return DRAFT_ROUND_VALUES.get(round_num, 1)


def calculate_keeper_cost(last_year_round: int) -> int:
    """
    Calculate the keeper cost for a player.

    Rule: Keeper cost = last year's draft round - 3
    Minimum: Round 1 (can't go lower)

    Args:
        last_year_round: Round the player was drafted in last year
                        (18 for undrafted/waiver players)

    Returns:
        Round cost to keep the player this year
    """
    # Keeper cost is previous round minus 3
    keeper_round = last_year_round - 3

    # Can't go below round 1
    return max(1, keeper_round)


def calculate_keeper_values(roster_df: pd.DataFrame,
                           player_values: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate keeper value for each player on a roster.

    Args:
        roster_df: DataFrame with Player, Position, DraftRound, YearsKept
        player_values: DataFrame with Name, dollar_value from valuation.py

    Returns:
        DataFrame with keeper analysis for each player
    """
    df = roster_df.copy()

    # Merge with player values (projections)
    # Use left join to keep all roster players even if projections missing
    df = df.merge(
        player_values[['Name', 'dollar_value', 'total_z', 'player_type']],
        left_on='Player',
        right_on='Name',
        how='left'
    )

    # Handle players not found in projections
    missing_proj = df[df['dollar_value'].isna()]['Player'].tolist()
    if missing_proj:
        print(f"\nWarning: No projections found for: {missing_proj}")
        print("These players will be excluded from analysis.\n")

    # Drop players without projections
    df = df.dropna(subset=['dollar_value'])

    # Calculate keeper cost (draft round for keeping them)
    df['keeper_round'] = df['DraftRound'].apply(calculate_keeper_cost)

    # Get the dollar value of the draft pick you'd spend
    df['keeper_cost_value'] = df['keeper_round'].apply(get_draft_round_value)

    # Calculate surplus value (keeper value)
    df['keeper_value'] = df['dollar_value'] - df['keeper_cost_value']

    # Calculate years remaining (max 3 years)
    df['years_remaining'] = 3 - df['YearsKept']

    # Adjust value for players with fewer years remaining
    # Year 1 keeper: full value
    # Year 2 keeper: ~85% value (2 years left)
    # Year 3 keeper: ~70% value (final year)
    year_multiplier = {3: 1.0, 2: 0.85, 1: 0.70}
    df['adjusted_keeper_value'] = df.apply(
        lambda row: row['keeper_value'] * year_multiplier.get(row['years_remaining'], 0.5),
        axis=1
    )

    # Sort by adjusted keeper value
    df = df.sort_values('adjusted_keeper_value', ascending=False)

    return df


def recommend_keepers(keeper_df: pd.DataFrame, num_keepers: int = 8) -> tuple:
    """
    Recommend which players to keep.

    Args:
        keeper_df: DataFrame from calculate_keeper_values
        num_keepers: Number of keeper slots available

    Returns:
        Tuple of (recommended_keepers_df, bubble_players_df)
    """
    # Get top N by adjusted keeper value
    recommended = keeper_df.head(num_keepers).copy()

    # Get bubble players (next 3-5 after the cut)
    bubble = keeper_df.iloc[num_keepers:num_keepers+5].copy()

    return recommended, bubble


def display_keeper_recommendations(keeper_df: pd.DataFrame,
                                   num_keepers: int = 8) -> None:
    """
    Display keeper recommendations in a nice format.
    """
    recommended, bubble = recommend_keepers(keeper_df, num_keepers)

    print(f"\n{'═'*70}")
    print(f"  YOUR TOP {num_keepers} KEEPERS (ranked by surplus value)")
    print(f"{'═'*70}")
    print(f"{'#':<3} {'Player':<22} {'Surplus':>9} │ {'Value':>7} │ {'Cost':>12} │ {'Yrs':>3}")
    print(f"{'-'*70}")

    for i, (_, row) in enumerate(recommended.iterrows(), 1):
        keeper_cost_str = f"Rd {int(row['keeper_round']):>2} (${row['keeper_cost_value']:.0f})"
        print(f"{i:<3} {row['Player']:<22} ${row['keeper_value']:>7.1f} │ ${row['dollar_value']:>5.1f} │ {keeper_cost_str:>12} │ {int(row['years_remaining']):>3}")

    if len(bubble) > 0:
        print(f"\n{'═'*70}")
        print(f"  BUBBLE PLAYERS (consider these)")
        print(f"{'═'*70}")
        print(f"{'#':<3} {'Player':<22} {'Surplus':>9} │ {'Value':>7} │ {'Cost':>12} │ {'Yrs':>3}")
        print(f"{'-'*70}")

        for i, (_, row) in enumerate(bubble.iterrows(), num_keepers + 1):
            keeper_cost_str = f"Rd {int(row['keeper_round']):>2} (${row['keeper_cost_value']:.0f})"
            print(f"{i:<3} {row['Player']:<22} ${row['keeper_value']:>7.1f} │ ${row['dollar_value']:>5.1f} │ {keeper_cost_str:>12} │ {int(row['years_remaining']):>3}")

    print(f"{'═'*70}")
    print("\nLegend:")
    print("  Surplus = Keeper Value (how much you 'gain' by keeping)")
    print("  Value = Projected dollar value for 2025")
    print("  Cost = Draft round cost to keep (and dollar equivalent)")
    print("  Yrs = Years remaining you can keep this player (max 3)")
    print()


def calculate_all_team_keepers(league_rosters: dict,
                               player_values: pd.DataFrame,
                               standings_slots: dict) -> dict:
    """
    Calculate keeper predictions for all teams in the league.

    Args:
        league_rosters: Dict of {team_name: roster_df}
        player_values: Combined player values from valuation
        standings_slots: Dict of {team_name: num_keeper_slots}

    Returns:
        Dict of {team_name: predicted_keepers_df}
    """
    all_team_keepers = {}

    for team_name, roster in league_rosters.items():
        num_slots = standings_slots.get(team_name, 6)  # Default 6 keepers

        # Calculate keeper values for this team
        keeper_analysis = calculate_keeper_values(roster, player_values)

        # Predict they'll keep their best players
        recommended, _ = recommend_keepers(keeper_analysis, num_slots)

        all_team_keepers[team_name] = recommended

    return all_team_keepers


def get_available_players(all_keepers: dict,
                          player_values: pd.DataFrame) -> pd.DataFrame:
    """
    Get list of players predicted to NOT be kept (available in draft).

    Args:
        all_keepers: Dict from calculate_all_team_keepers
        player_values: Combined player values

    Returns:
        DataFrame of available players sorted by value
    """
    # Collect all kept player names
    kept_players = set()
    for team_name, keepers_df in all_keepers.items():
        kept_players.update(keepers_df['Player'].tolist())

    # Filter player values to only non-kept players
    available = player_values[~player_values['Name'].isin(kept_players)].copy()

    # Sort by value
    available = available.sort_values('dollar_value', ascending=False)

    return available


def display_available_players(available_df: pd.DataFrame, n: int = 30) -> None:
    """
    Display top available players (predicted to be in the draft).
    """
    print(f"\n{'═'*55}")
    print(f"  TOP {n} AVAILABLE PLAYERS (predicted not kept)")
    print(f"{'═'*55}")
    print(f"{'Rank':<5} {'Player':<25} {'Type':<8} {'Value':>8}")
    print(f"{'-'*55}")

    for i, (_, row) in enumerate(available_df.head(n).iterrows(), 1):
        ptype = row['player_type'][:3]
        print(f"{i:<5} {row['Name']:<25} {ptype:<8} ${row['dollar_value']:>6.1f}")

    print(f"{'═'*55}\n")


if __name__ == '__main__':
    # Test with sample data
    from data_loader import (load_hitter_projections, load_pitcher_projections,
                             load_roster, create_sample_projections, create_sample_roster)
    from valuation import (calculate_hitter_zscores, calculate_pitcher_zscores,
                          combine_player_values)
    from pathlib import Path

    # Create sample data if it doesn't exist
    proj_dir = Path(__file__).parent.parent / 'data' / 'projections'
    roster_dir = Path(__file__).parent.parent / 'data' / 'rosters'

    if not (proj_dir / 'sample_hitters.csv').exists():
        create_sample_projections()
    if not (roster_dir / 'sample_my_team.csv').exists():
        create_sample_roster()

    print("Testing keeper analysis with sample data...")
    print("=" * 60)

    # Load and value projections
    hitters = load_hitter_projections(proj_dir / 'sample_hitters.csv')
    pitchers = load_pitcher_projections(proj_dir / 'sample_pitchers.csv')

    hitters_valued = calculate_hitter_zscores(hitters)
    pitchers_valued = calculate_pitcher_zscores(pitchers)

    all_players = combine_player_values(hitters_valued, pitchers_valued)

    # Load roster
    my_roster = load_roster(roster_dir / 'sample_my_team.csv')

    # Calculate keeper values
    keeper_analysis = calculate_keeper_values(my_roster, all_players)

    # Display recommendations (8 keepers since you're in 5th-8th tier)
    display_keeper_recommendations(keeper_analysis, num_keepers=8)
