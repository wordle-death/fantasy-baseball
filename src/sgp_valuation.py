"""
sgp_valuation.py - SGP (Standings Gain Points) player valuation

SGP EXPLAINED:
SGP is the industry standard for fantasy baseball player valuation.
It measures how many points in the standings a player's stats are worth.

For example, if one SGP in HR = 9 home runs (meaning you need 9 HR to move up
one position in the standings), then a player with 36 HR = 4 SGP in HR.

We sum up SGP across all categories, then convert to dollar values based on
a fixed league budget ($260/team).

LEAGUE-SPECIFIC VALUES:
- 14-team league
- 5x5 categories: R, HR, RBI, SB, OBP | W, SV, K, ERA, WHIP
- ~196 draftable hitters, ~126 draftable pitchers
- 65% budget to hitters, 35% to pitchers
"""

import pandas as pd
import numpy as np


# League settings
NUM_TEAMS = 14
BUDGET_PER_TEAM = 260
TOTAL_BUDGET = NUM_TEAMS * BUDGET_PER_TEAM  # $3,640

# Hitter/Pitcher split (70/30 for this league - hitters valued more, pitchers easier to find on waivers)
HITTER_BUDGET_PCT = 0.70
PITCHER_BUDGET_PCT = 0.30
HITTER_BUDGET = TOTAL_BUDGET * HITTER_BUDGET_PCT  # $2,548
PITCHER_BUDGET = TOTAL_BUDGET * PITCHER_BUDGET_PCT  # $1,092

# Roster positions per team (typical mixed league)
HITTERS_PER_TEAM = 14
PITCHERS_PER_TEAM = 9

# Draftable player pool (1.5x roster spots for replacement level)
DRAFTABLE_HITTERS = int(NUM_TEAMS * HITTERS_PER_TEAM * 1.0)  # ~196
DRAFTABLE_PITCHERS = int(NUM_TEAMS * PITCHERS_PER_TEAM * 1.0)  # ~126

# SGP denominators for a 14-team league
# These represent how many stat points = 1 position in standings
# Derived from historical 14-team league standings spreads
SGP_DENOMINATORS = {
    # Hitting (counting stats)
    'R': 22,    # ~22 runs per standings position
    'HR': 9,    # ~9 HR per standings position
    'RBI': 22,  # ~22 RBI per standings position
    'SB': 7,    # ~7 SB per standings position

    # Pitching (counting stats)
    'W': 3,     # ~3 wins per standings position
    'SV': 7,    # ~7 saves per standings position
    'K': 35,    # ~35 K per standings position
}

# Replacement level for rate stats (league average baseline)
# These will be calculated from the draftable player pool
REPLACEMENT_LEVEL = {
    'OBP': 0.320,   # Minimum useful OBP
    'ERA': 4.50,    # Replacement level ERA
    'WHIP': 1.35,   # Replacement level WHIP
}

# Position scarcity multipliers
# These boost the value of players at scarce positions AFTER base SGP calculation
# Rationale: A 40 HR catcher is more valuable than a 40 HR 1B due to position scarcity
POSITION_SCARCITY = {
    # Hitters - relative to generic hitter pool
    'C': 1.15,      # Catchers: moderate scarcity boost (only elite catchers warrant early picks)
    'SS': 1.10,     # Shortstops: power/speed combo rare at position
    '2B': 1.05,     # Second basemen: slightly scarce
    '3B': 1.00,     # Third basemen: standard depth
    '1B': 0.95,     # First basemen: abundant power options
    'OF': 1.00,     # Outfielders: deep position
    'Util': 1.00,   # Utility: no position scarcity
    'DH': 1.00,     # DH: no position scarcity

    # Pitchers - relative to generic pitcher pool
    'RP': 1.25,     # Relievers/Closers (with saves): scarce, ~28 closers league-wide
    'SP': 1.00,     # Starters: deep position
}


def fuzzy_match_name(name1: str, name2: str) -> float:
    """Calculate similarity between two player names."""
    from difflib import SequenceMatcher
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    return SequenceMatcher(None, n1, n2).ratio()


def get_primary_position(position_str: str, saves: float = 0) -> str:
    """
    Determine primary position for scarcity calculation.

    For multi-position players, returns the most valuable (scarcest) position.
    For pitchers, uses saves projection to distinguish closers from setup men.
    """
    if pd.isna(position_str) or position_str == '':
        return 'Util'

    positions = [p.strip() for p in str(position_str).split(',')]

    # Catcher eligibility is most valuable - always use C if available
    if 'C' in positions:
        return 'C'

    # For pitchers, check saves to distinguish closers
    if 'SP' in positions or 'RP' in positions:
        if saves >= 10:
            return 'RP'  # Closer/saves guy
        return 'SP'

    # For hitters, use position priority (scarcest first)
    priority = ['SS', '2B', '3B', 'OF', '1B', 'Util', 'DH']
    for pos in priority:
        if pos in positions:
            return pos

    # Default to first listed position
    return positions[0] if positions else 'Util'


def add_positions_from_yahoo(projections_df: pd.DataFrame,
                              yahoo_roster_path: str,
                              is_pitcher: bool = False) -> pd.DataFrame:
    """
    Add position data to projections by matching with Yahoo roster.

    Uses fuzzy matching to handle name variations between data sources.
    """
    df = projections_df.copy()

    # Load Yahoo roster
    yahoo = pd.read_csv(yahoo_roster_path)

    # Build a lookup of player positions
    position_map = {}
    for _, row in yahoo.iterrows():
        player = row['Player']
        position = row['Position']
        position_map[player.lower().strip()] = position

    # Match each projection to Yahoo position
    positions = []
    for _, row in df.iterrows():
        player_name = row['Name']
        saves = row.get('SV', 0) if is_pitcher else 0

        # Try exact match first
        exact_key = player_name.lower().strip()
        if exact_key in position_map:
            positions.append(position_map[exact_key])
            continue

        # Try fuzzy matching
        best_match = None
        best_score = 0
        for yahoo_name, pos in position_map.items():
            score = fuzzy_match_name(player_name, yahoo_name)
            if score > best_score and score > 0.8:
                best_score = score
                best_match = pos

        if best_match:
            positions.append(best_match)
        else:
            # Default position if not found
            positions.append('SP' if is_pitcher else 'Util')

    df['Position'] = positions

    # Calculate primary position for scarcity
    if is_pitcher:
        df['primary_position'] = df.apply(
            lambda r: get_primary_position(r['Position'], r.get('SV', 0)),
            axis=1
        )
    else:
        df['primary_position'] = df['Position'].apply(
            lambda p: get_primary_position(p)
        )

    return df


def apply_position_scarcity(df: pd.DataFrame, is_pitcher: bool = False) -> pd.DataFrame:
    """
    Apply position scarcity multipliers to SGP values.

    Multiplies total_sgp by position-specific factors, then renormalizes
    to maintain the same total SGP (just redistributed).
    """
    df = df.copy()

    # Get multiplier for each player's primary position
    df['position_multiplier'] = df['primary_position'].apply(
        lambda p: POSITION_SCARCITY.get(p, 1.0)
    )

    # Apply multiplier to total SGP
    raw_adjusted = df['total_sgp'] * df['position_multiplier']

    # Renormalize to maintain total SGP (redistributes value without inflating)
    # This ensures position adjustments just shift value between players
    original_total = df['total_sgp'].sum()
    adjusted_total = raw_adjusted.sum()

    if adjusted_total > 0:
        scale_factor = original_total / adjusted_total
        df['adjusted_sgp'] = raw_adjusted * scale_factor
    else:
        df['adjusted_sgp'] = df['total_sgp']

    return df


def calculate_hitter_sgp(hitters_df: pd.DataFrame,
                         min_pa: int = 200) -> pd.DataFrame:
    """
    Calculate SGP values for hitters.

    Args:
        hitters_df: DataFrame with Name, Team, PA, R, HR, RBI, SB, OBP
        min_pa: Minimum PA to include

    Returns:
        DataFrame with SGP calculations and dollar values
    """
    df = hitters_df.copy()

    # Filter to players with meaningful PA
    df = df[df['PA'] >= min_pa]

    # Calculate SGP for counting stats
    for stat in ['R', 'HR', 'RBI', 'SB']:
        denom = SGP_DENOMINATORS[stat]
        df[f'{stat}_sgp'] = df[stat] / denom

    # Calculate SGP for OBP (rate stat)
    # Use marginal OBP: how many points above replacement × PA
    # Weighted by plate appearances
    replacement_obp = REPLACEMENT_LEVEL['OBP']

    # Calculate the average PA for draftable hitters
    top_hitters = df.nlargest(DRAFTABLE_HITTERS, 'PA')
    avg_pa = top_hitters['PA'].mean()

    # OBP SGP = (OBP - replacement) × (PA/avg_PA) × scaling factor
    # The scaling factor converts marginal OBP to SGP
    # In a 14-team league, ~0.015 OBP per standings position, weighted by PA
    obp_sgp_factor = avg_pa / 0.015  # Approx SGP per marginal OBP point
    df['OBP_sgp'] = ((df['OBP'] - replacement_obp) * (df['PA'] / avg_pa)) * (1 / 0.015)

    # Total SGP
    sgp_cols = [col for col in df.columns if col.endswith('_sgp')]
    df['total_sgp'] = df[sgp_cols].sum(axis=1)

    # Assign rankings
    df['hitter_rank'] = df['total_sgp'].rank(ascending=False, method='min').astype(int)

    return df


def calculate_pitcher_sgp(pitchers_df: pd.DataFrame,
                          min_ip: int = 30) -> pd.DataFrame:
    """
    Calculate SGP values for pitchers.

    Args:
        pitchers_df: DataFrame with Name, Team, IP, W, SV, K, ERA, WHIP
        min_ip: Minimum IP to include

    Returns:
        DataFrame with SGP calculations and dollar values
    """
    df = pitchers_df.copy()

    # Filter to pitchers with meaningful IP
    df = df[df['IP'] >= min_ip]

    # Calculate SGP for counting stats
    for stat in ['W', 'SV', 'K']:
        denom = SGP_DENOMINATORS[stat]
        df[f'{stat}_sgp'] = df[stat] / denom

    # Calculate SGP for rate stats (ERA, WHIP)
    # For ERA/WHIP, LOWER is better, so we flip the sign
    # Weighted by IP
    top_pitchers = df.nlargest(DRAFTABLE_PITCHERS, 'IP')
    avg_ip = top_pitchers['IP'].mean()

    # ERA SGP = (replacement_ERA - actual_ERA) × (IP/avg_IP) × scaling factor
    # ~0.25 ERA per standings position in 14-team league
    era_replacement = REPLACEMENT_LEVEL['ERA']
    df['ERA_sgp'] = ((era_replacement - df['ERA']) * (df['IP'] / avg_ip)) * (1 / 0.25)

    # WHIP SGP = (replacement_WHIP - actual_WHIP) × (IP/avg_IP) × scaling factor
    # ~0.04 WHIP per standings position
    whip_replacement = REPLACEMENT_LEVEL['WHIP']
    df['WHIP_sgp'] = ((whip_replacement - df['WHIP']) * (df['IP'] / avg_ip)) * (1 / 0.04)

    # Total SGP
    sgp_cols = [col for col in df.columns if col.endswith('_sgp')]
    df['total_sgp'] = df[sgp_cols].sum(axis=1)

    # Assign rankings
    df['pitcher_rank'] = df['total_sgp'].rank(ascending=False, method='min').astype(int)

    return df


def convert_sgp_to_dollars(hitters_df: pd.DataFrame,
                           pitchers_df: pd.DataFrame,
                           use_adjusted: bool = False) -> tuple:
    """
    Convert SGP to dollar values using fixed budget split.

    Uses 70/30 hitter/pitcher budget split and allocates based on
    marginal SGP above replacement level.

    Args:
        use_adjusted: If True, uses adjusted_sgp (with position scarcity)
                     instead of total_sgp for valuation

    Returns:
        Tuple of (hitters_with_dollars, pitchers_with_dollars)
    """
    hitters = hitters_df.copy()
    pitchers = pitchers_df.copy()

    # Use adjusted_sgp if available and requested, otherwise use total_sgp
    sgp_col = 'adjusted_sgp' if (use_adjusted and 'adjusted_sgp' in hitters.columns) else 'total_sgp'

    # Get top draftable players only (based on chosen SGP column)
    hitters = hitters.nlargest(DRAFTABLE_HITTERS, sgp_col)
    pitchers = pitchers.nlargest(DRAFTABLE_PITCHERS, sgp_col)

    # Calculate replacement level (last draftable player)
    hitter_replacement_sgp = hitters[sgp_col].min()
    pitcher_replacement_sgp = pitchers[sgp_col].min()

    # Calculate marginal SGP (above replacement)
    hitters['marginal_sgp'] = hitters[sgp_col] - hitter_replacement_sgp
    pitchers['marginal_sgp'] = pitchers[sgp_col] - pitcher_replacement_sgp

    # Total marginal SGP for each group
    total_hitter_marginal = hitters['marginal_sgp'].sum()
    total_pitcher_marginal = pitchers['marginal_sgp'].sum()

    # Dollar value = (marginal_SGP / total_marginal_SGP) × budget + $1 baseline
    if total_hitter_marginal > 0:
        hitters['dollar_value'] = (
            (hitters['marginal_sgp'] / total_hitter_marginal) * HITTER_BUDGET
        ) + 1
    else:
        hitters['dollar_value'] = 1

    if total_pitcher_marginal > 0:
        pitchers['dollar_value'] = (
            (pitchers['marginal_sgp'] / total_pitcher_marginal) * PITCHER_BUDGET
        ) + 1
    else:
        pitchers['dollar_value'] = 1

    # Cap minimum at $1
    hitters['dollar_value'] = hitters['dollar_value'].clip(lower=1)
    pitchers['dollar_value'] = pitchers['dollar_value'].clip(lower=1)

    return hitters, pitchers


def combine_and_rank_players(hitters_df: pd.DataFrame,
                             pitchers_df: pd.DataFrame) -> pd.DataFrame:
    """
    Combine hitters and pitchers into a single ranked list.

    Adds overall rank and preserves position-specific ranks.
    """
    hitters = hitters_df.copy()
    pitchers = pitchers_df.copy()

    # Add player type
    hitters['player_type'] = 'Hitter'
    pitchers['player_type'] = 'Pitcher'

    # Standardize columns for combining
    hitters = hitters.rename(columns={'hitter_rank': 'position_rank'})
    pitchers = pitchers.rename(columns={'pitcher_rank': 'position_rank'})

    # Select columns to keep
    keep_cols = ['Name', 'Team', 'total_sgp', 'marginal_sgp', 'dollar_value',
                 'player_type', 'position_rank']

    # Add position columns if available
    if 'primary_position' in hitters.columns:
        keep_cols.append('primary_position')
    if 'position_multiplier' in hitters.columns:
        keep_cols.append('position_multiplier')
    if 'adjusted_sgp' in hitters.columns:
        keep_cols.append('adjusted_sgp')

    # Add playing time column
    if 'PA' in hitters.columns:
        hitters['playing_time'] = hitters['PA']
    if 'IP' in pitchers.columns:
        pitchers['playing_time'] = pitchers['IP']
    keep_cols.append('playing_time')

    # Add per-category stat columns for draft recommendation engine
    # These are needed to calculate category needs (R, HR, RBI, SB, OBP for hitters;
    # W, SV, K, ERA, WHIP for pitchers). NaN where stat doesn't apply.
    stat_cols = ['R', 'HR', 'RBI', 'SB', 'OBP', 'PA',
                 'W', 'SV', 'K', 'ERA', 'WHIP', 'IP',
                 'ADP']  # Fangraphs ADP for draft position reality check
    for col in stat_cols:
        if col not in keep_cols:
            keep_cols.append(col)

    # Filter to available columns
    hitter_cols = [c for c in keep_cols if c in hitters.columns]
    pitcher_cols = [c for c in keep_cols if c in pitchers.columns]

    hitters_slim = hitters[hitter_cols]
    pitchers_slim = pitchers[pitcher_cols]

    # Combine
    combined = pd.concat([hitters_slim, pitchers_slim], ignore_index=True)

    # Add overall rank
    combined['overall_rank'] = combined['dollar_value'].rank(ascending=False, method='min').astype(int)

    # Sort by dollar value
    combined = combined.sort_values('dollar_value', ascending=False)

    return combined


def display_top_players_with_ranks(players_df: pd.DataFrame, n: int = 30) -> None:
    """
    Display top N players with rankings.
    """
    print(f"\n{'='*75}")
    print(f"  TOP {n} PLAYERS BY SGP VALUE (with Position Ranks)")
    print(f"{'='*75}")
    print(f"{'Rank':<5} {'Player':<25} {'Type':<6} {'Value':>7} {'Pos Rk':>7} {'SGP':>8}")
    print(f"{'-'*75}")

    for _, row in players_df.head(n).iterrows():
        ptype = row['player_type'][:3]
        print(f"{int(row['overall_rank']):<5} {row['Name']:<25} {ptype:<6} "
              f"${row['dollar_value']:>5.1f} {int(row['position_rank']):>7} "
              f"{row['total_sgp']:>8.1f}")

    print(f"{'='*75}")

    # Show summary stats
    hitters = players_df[players_df['player_type'] == 'Hitter']
    pitchers = players_df[players_df['player_type'] == 'Pitcher']

    print(f"\nSummary:")
    print(f"  Total hitters valued: {len(hitters)}")
    print(f"  Total pitchers valued: {len(pitchers)}")
    print(f"  Hitter budget used: ${hitters['dollar_value'].sum():,.0f} (target: ${HITTER_BUDGET:,.0f})")
    print(f"  Pitcher budget used: ${pitchers['dollar_value'].sum():,.0f} (target: ${PITCHER_BUDGET:,.0f})")
    print(f"  Total: ${players_df['dollar_value'].sum():,.0f} (target: ${TOTAL_BUDGET:,.0f})")


def run_sgp_valuation(hitter_file: str, pitcher_file: str,
                      output_file: str = None,
                      yahoo_roster_path: str = None) -> pd.DataFrame:
    """
    Run full SGP valuation pipeline.

    Args:
        hitter_file: Path to Fangraphs hitter projections
        pitcher_file: Path to Fangraphs pitcher projections
        output_file: Optional path to save results
        yahoo_roster_path: Path to Yahoo roster CSV for position data
                          (enables position scarcity adjustments)

    Returns:
        Combined player values DataFrame
    """
    print("\n" + "="*60)
    print("  SGP VALUATION ENGINE")
    if yahoo_roster_path:
        print("  (with Position Scarcity Adjustments)")
    print("="*60)

    # Load projections
    print(f"\nLoading projections...")
    hitters = pd.read_csv(hitter_file)
    pitchers = pd.read_csv(pitcher_file)

    # Handle strikeout column naming (Fangraphs uses 'SO')
    if 'SO' in pitchers.columns and 'K' not in pitchers.columns:
        pitchers = pitchers.rename(columns={'SO': 'K'})

    print(f"  Loaded {len(hitters)} hitters and {len(pitchers)} pitchers")

    # Filter to minimum playing time
    hitters = hitters[hitters['PA'] >= 200]
    pitchers = pitchers[pitchers['IP'] >= 30]
    print(f"  After filters: {len(hitters)} hitters (200+ PA), {len(pitchers)} pitchers (30+ IP)")

    # Add position data if Yahoo roster provided
    use_position_scarcity = False
    if yahoo_roster_path:
        print("\nAdding position data from Yahoo roster...")
        hitters = add_positions_from_yahoo(hitters, yahoo_roster_path, is_pitcher=False)
        pitchers = add_positions_from_yahoo(pitchers, yahoo_roster_path, is_pitcher=True)

        # Show position distribution
        hitter_positions = hitters['primary_position'].value_counts()
        print(f"  Hitter positions: {dict(hitter_positions)}")

        pitcher_positions = pitchers['primary_position'].value_counts()
        print(f"  Pitcher positions: {dict(pitcher_positions)}")
        use_position_scarcity = True

    # Calculate SGP
    print("\nCalculating SGP values...")
    hitters_sgp = calculate_hitter_sgp(hitters)
    pitchers_sgp = calculate_pitcher_sgp(pitchers)

    # Apply position scarcity if positions are available
    if use_position_scarcity:
        print("Applying position scarcity multipliers...")
        hitters_sgp = apply_position_scarcity(hitters_sgp, is_pitcher=False)
        pitchers_sgp = apply_position_scarcity(pitchers_sgp, is_pitcher=True)

        # Show example adjustments
        catchers = hitters_sgp[hitters_sgp['primary_position'] == 'C'].nlargest(3, 'adjusted_sgp')
        if len(catchers) > 0:
            print(f"  Top catchers after adjustment:")
            for _, c in catchers.iterrows():
                print(f"    {c['Name']}: {c['total_sgp']:.1f} → {c['adjusted_sgp']:.1f} (×{c['position_multiplier']:.2f})")

    # Convert to dollars
    print("\nConverting to dollar values...")
    hitters_valued, pitchers_valued = convert_sgp_to_dollars(
        hitters_sgp, pitchers_sgp, use_adjusted=use_position_scarcity
    )

    # Combine and rank
    all_players = combine_and_rank_players(hitters_valued, pitchers_valued)

    # Display results
    display_top_players_with_ranks(all_players, n=30)

    # Show top pitchers specifically
    print(f"\n{'='*60}")
    print(f"  TOP 15 PITCHERS")
    print(f"{'='*60}")
    top_pitchers = all_players[all_players['player_type'] == 'Pitcher'].head(15)
    print(f"{'Rank':<5} {'Player':<25} {'Value':>7} {'Overall':>8}")
    print(f"{'-'*60}")
    for _, row in top_pitchers.iterrows():
        print(f"{int(row['position_rank']):<5} {row['Name']:<25} "
              f"${row['dollar_value']:>5.1f} {int(row['overall_rank']):>8}")

    # Save if output file specified
    if output_file:
        all_players.to_csv(output_file, index=False)
        print(f"\nSaved valuations to: {output_file}")

    return all_players


if __name__ == '__main__':
    from pathlib import Path

    proj_dir = Path(__file__).parent.parent / 'data' / 'projections'
    roster_dir = Path(__file__).parent.parent / 'data' / 'rosters'

    # Use real Fangraphs projections (Feb 22, 2026)
    hitter_file = proj_dir / 'fangraphs-projections-hitters-depthcharts-02.22.26.csv'
    pitcher_file = proj_dir / 'fangraphs-projections-pitchers-depthcharts-02.22.26.csv'
    yahoo_roster = roster_dir / 'yahoo_league.csv'
    output_file = proj_dir / 'sgp_player_values_v3.csv'  # v3 = with position scarcity

    if hitter_file.exists() and pitcher_file.exists():
        # Include Yahoo roster for position scarcity adjustments
        yahoo_path = str(yahoo_roster) if yahoo_roster.exists() else None
        run_sgp_valuation(str(hitter_file), str(pitcher_file), str(output_file), yahoo_path)
    else:
        print("Fangraphs projection files not found. Using sample data...")
        hitter_file = proj_dir / 'sample_hitters.csv'
        pitcher_file = proj_dir / 'sample_pitchers.csv'
        if hitter_file.exists():
            run_sgp_valuation(str(hitter_file), str(pitcher_file))
