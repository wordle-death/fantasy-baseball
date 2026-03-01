#!/usr/bin/env python3
"""
run_keeper_analysis.py - Run keeper analysis for The Nudes using SGP valuations

This script:
1. Loads the SGP player valuations
2. Loads The Nudes roster with draft history
3. Calculates keeper surplus values
4. Identifies ineligible players (rounds 1-3, or YearsKept = 3)
5. Recommends the top 8 keepers
"""

import pandas as pd
from pathlib import Path
from difflib import SequenceMatcher
import argparse

# Optional Statcast integration
try:
    from src.statcast_news import analyze_keeper_list, summarize_alerts
    STATCAST_AVAILABLE = True
except ImportError:
    STATCAST_AVAILABLE = False


# League rules
MAX_YEARS_KEPT = 3
INELIGIBLE_ROUNDS = [1, 2, 3]  # Players drafted in rounds 1-3 cannot be kept
UNDRAFTED_ROUND = 18  # Keeper value for undrafted players
NUM_KEEPERS = 8  # The Nudes finished 5th, gets 8 keepers

# Draft round value curve (what each round is "worth" in dollars)
DRAFT_ROUND_VALUES = {
    1: 50, 2: 42, 3: 35, 4: 30, 5: 26, 6: 23, 7: 20, 8: 18,
    9: 16, 10: 14, 11: 12, 12: 10, 13: 9, 14: 8, 15: 7,
    16: 6, 17: 5, 18: 4, 19: 3, 20: 2, 21: 2, 22: 1, 23: 1, 24: 1, 25: 1
}

# League size for ADP calculation
NUM_TEAMS = 14


def estimate_adp_round(overall_rank: int) -> int:
    """
    Estimate what round a player would be drafted based on overall rank.

    In a 14-team league:
    - Picks 1-14 = Round 1
    - Picks 15-28 = Round 2
    - etc.

    Args:
        overall_rank: Player's overall ranking (1 = best)

    Returns:
        Estimated draft round (1-25)
    """
    if overall_rank <= 0:
        return 25  # Undraftable
    # Calculate round (1-indexed)
    adp_round = ((overall_rank - 1) // NUM_TEAMS) + 1
    # Cap at round 25
    return min(25, max(1, adp_round))


def calculate_adp_savings(adp_round: int, keeper_round: int) -> int:
    """
    Calculate how many draft rounds you save by keeping a player.

    Positive = good value (player goes earlier than keeper cost)
    Zero = break even
    Negative = bad value (paying more than market price)

    Args:
        adp_round: Round where player would be drafted
        keeper_round: Round where you keep them

    Returns:
        Rounds saved (positive = value, negative = overpay)
    """
    return adp_round - keeper_round


def fuzzy_match(name1: str, name2: str) -> float:
    """Calculate similarity between two player names."""
    # Normalize names
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    return SequenceMatcher(None, n1, n2).ratio()


def find_player_value(player_name: str, valuations_df: pd.DataFrame) -> dict:
    """
    Find a player's value in the valuations dataframe.
    Uses fuzzy matching to handle name variations.
    """
    # Try exact match first
    exact = valuations_df[valuations_df['Name'] == player_name]
    if len(exact) == 1:
        row = exact.iloc[0]
        return {
            'found': True,
            'name': row['Name'],
            'dollar_value': row['dollar_value'],
            'overall_rank': row['overall_rank'],
            'position_rank': row['position_rank'],
            'player_type': row['player_type']
        }

    # Try fuzzy matching
    best_match = None
    best_score = 0

    for _, row in valuations_df.iterrows():
        score = fuzzy_match(player_name, row['Name'])
        if score > best_score and score > 0.8:  # 80% threshold
            best_score = score
            best_match = row

    if best_match is not None:
        return {
            'found': True,
            'name': best_match['Name'],
            'dollar_value': best_match['dollar_value'],
            'overall_rank': best_match['overall_rank'],
            'position_rank': best_match['position_rank'],
            'player_type': best_match['player_type']
        }

    return {'found': False}


def calculate_keeper_cost(draft_round: int) -> int:
    """Calculate the round cost to keep a player.

    - Drafted players: previous round - 3
    - Undrafted players: Round 18 directly (NO -3 discount)
    """
    if draft_round == 0:
        return 18  # Undrafted: Round 18, NO discount
    return max(1, draft_round - 3)  # Drafted: round - 3


def get_round_value(round_num: int) -> float:
    """Get the dollar value of a draft round."""
    round_num = max(1, min(25, round_num))
    return DRAFT_ROUND_VALUES.get(round_num, 1)


def assign_keeper_rounds(keepers_df: pd.DataFrame, num_keepers: int) -> pd.DataFrame:
    """
    Assign actual keeper rounds, handling conflicts.

    If multiple keepers have the same base keeper round, bump one to an earlier round.
    Players are assigned in order of surplus value (best surplus gets their preferred round).
    """
    df = keepers_df.head(num_keepers).copy()

    # Track which rounds are taken
    taken_rounds = set()

    # New columns for actual assignment
    df['Actual_Round'] = 0
    df['Actual_Cost'] = 0.0

    for idx in df.index:
        base_round = df.loc[idx, 'Keeper_Round']

        # Find the earliest available round starting from base_round
        actual_round = base_round
        while actual_round in taken_rounds:
            actual_round -= 1  # Bump to earlier round
            if actual_round < 1:
                # Shouldn't happen with 8 keepers, but handle edge case
                actual_round = 1
                break

        taken_rounds.add(actual_round)
        df.loc[idx, 'Actual_Round'] = actual_round
        df.loc[idx, 'Actual_Cost'] = get_round_value(actual_round)

    # Recalculate surplus with actual cost
    df['Actual_Surplus'] = df['Value'] - df['Actual_Cost']

    return df


def run_analysis(scan_statcast: bool = False):
    """Run the keeper analysis for The Nudes.

    Args:
        scan_statcast: If True, scan keepers for Statcast alerts
    """
    data_dir = Path(__file__).parent / 'data'
    proj_dir = data_dir / 'projections'
    roster_dir = data_dir / 'rosters'

    # Load SGP valuations (v3 = with position scarcity adjustments)
    valuations_file = proj_dir / 'sgp_player_values_v3.csv'
    if not valuations_file.exists():
        print("Error: Run SGP valuation first (python -m src.sgp_valuation)")
        return

    valuations = pd.read_csv(valuations_file)
    print(f"Loaded {len(valuations)} player valuations")

    # Load league rosters
    roster_file = roster_dir / 'yahoo_league.csv'
    all_rosters = pd.read_csv(roster_file)

    # Filter to The Nudes
    roster = all_rosters[all_rosters['Team'] == 'The Nudes'].copy()
    print(f"Found {len(roster)} players on The Nudes")

    # Analyze each player
    analysis = []
    ineligible = []

    for _, row in roster.iterrows():
        player = row['Player']
        position = row['Position']
        draft_round = int(row['DraftRound'])
        years_kept = int(row['YearsKept'])

        # Check eligibility
        is_ineligible = False
        ineligibility_reason = ""

        if draft_round in INELIGIBLE_ROUNDS:
            is_ineligible = True
            ineligibility_reason = f"Drafted in Round {draft_round} (rounds 1-3 cannot be kept)"
        elif years_kept >= MAX_YEARS_KEPT:
            is_ineligible = True
            ineligibility_reason = f"Already kept {years_kept} years (max {MAX_YEARS_KEPT})"

        # Find player value
        value_info = find_player_value(player, valuations)

        if not value_info['found']:
            # Player not in projections - skip
            ineligible.append({
                'Player': player,
                'Position': position,
                'Reason': "Not in projections (minor leaguer or injured?)"
            })
            continue

        if is_ineligible:
            ineligible.append({
                'Player': player,
                'Position': position,
                'Reason': ineligibility_reason,
                'Value': value_info['dollar_value'],
                'Rank': value_info['overall_rank']
            })
            continue

        # Calculate keeper value
        keeper_round = calculate_keeper_cost(draft_round)
        keeper_cost = get_round_value(keeper_round)
        surplus_value = value_info['dollar_value'] - keeper_cost
        years_remaining = MAX_YEARS_KEPT - years_kept

        # Calculate ADP-based value (where player would actually be drafted)
        adp_round = estimate_adp_round(int(value_info['overall_rank']))
        adp_savings = calculate_adp_savings(adp_round, keeper_round)

        analysis.append({
            'Player': player,
            'Position': position,
            'Value': value_info['dollar_value'],
            'Overall_Rank': value_info['overall_rank'],
            'Pos_Rank': value_info['position_rank'],
            'Type': value_info['player_type'],
            'Draft_Round': draft_round if draft_round > 0 else 'UD',
            'Keeper_Round': keeper_round,
            'Keeper_Cost': keeper_cost,
            'Surplus': surplus_value,
            'ADP_Round': adp_round,
            'ADP_Savings': adp_savings,
            'Years_Kept': years_kept,
            'Years_Remaining': years_remaining
        })

    # Sort by surplus value
    analysis_df = pd.DataFrame(analysis)
    analysis_df = analysis_df.sort_values('Surplus', ascending=False)

    # Display results - show BASE surplus (not adjusted for conflicts)
    print("\n" + "="*105)
    print("  THE NUDES - KEEPER ANALYSIS (SGP Valuation + ADP Comparison)")
    print("="*105)

    print(f"\n{'='*105}")
    print(f"  ALL ELIGIBLE KEEPERS (sorted by SGP surplus)")
    print(f"{'='*105}")
    print(f"{'#':<3} {'Player':<22} {'Pos':<8} {'Value':>6} {'Rank':>4} │ {'Kpr':>4} {'ADP':>4} {'Save':>5} │ {'Surplus':>8} │ {'Yrs':>3}")
    print("-"*105)

    for i, (_, row) in enumerate(analysis_df.iterrows(), 1):
        keeper_rd = int(row['Keeper_Round'])
        adp_rd = int(row['ADP_Round'])
        adp_save = int(row['ADP_Savings'])
        # Color-code ADP savings: positive is good
        save_str = f"+{adp_save}" if adp_save > 0 else str(adp_save)
        marker = " ◀" if i <= NUM_KEEPERS else ""
        print(f"{i:<3} {row['Player']:<22} {row['Position']:<8} ${row['Value']:>4.0f} {int(row['Overall_Rank']):>4} │ "
              f"Rd{keeper_rd:>2} Rd{adp_rd:>2} {save_str:>5} │ ${row['Surplus']:>6.1f} │ {row['Years_Remaining']:>3}{marker}")

    # Identify round conflicts among top keepers
    top_keepers = analysis_df.head(NUM_KEEPERS)
    round_counts = top_keepers['Keeper_Round'].value_counts()
    conflicts = round_counts[round_counts > 1]

    if len(conflicts) > 0:
        print(f"\n{'='*90}")
        print(f"  ⚠️  ROUND CONFLICTS (same keeper round)")
        print(f"{'='*90}")
        print("  If keeping multiple players at the same round, one must bump to an earlier round.")
        print()
        for rd, count in conflicts.items():
            players_in_round = top_keepers[top_keepers['Keeper_Round'] == rd]
            print(f"  Round {rd}: {count} players")
            for _, p in players_in_round.iterrows():
                bump_to = rd - 1
                bump_cost = get_round_value(bump_to)
                new_surplus = p['Value'] - bump_cost
                print(f"    • {p['Player']:<20} (${p['Surplus']:>5.1f} surplus → ${new_surplus:>5.1f} if bumped to Rd {bump_to})")
            print()


    # Ineligible players
    if ineligible:
        print(f"\n{'='*90}")
        print(f"  INELIGIBLE PLAYERS ({len(ineligible)})")
        print(f"{'='*90}")
        for p in ineligible:
            if 'Value' in p:
                print(f"  {p['Player']:<22} (${p['Value']:.1f}, Rank {int(p['Rank'])}) - {p['Reason']}")
            else:
                print(f"  {p['Player']:<22} - {p['Reason']}")

    # Summary
    print(f"\n{'='*90}")
    print("  SUMMARY")
    print(f"{'='*90}")
    print(f"  Eligible players: {len(analysis_df)}")
    print(f"  Ineligible players: {len(ineligible)}")
    print(f"  Keeper slots available: {NUM_KEEPERS}")

    print(f"\n  Top {NUM_KEEPERS} keepers (by base surplus):")
    print(f"    Total value: ${top_keepers['Value'].sum():.1f}")
    print(f"    Total base cost: ${top_keepers['Keeper_Cost'].sum():.1f}")
    print(f"    Total base surplus: ${top_keepers['Surplus'].sum():.1f}")

    if len(conflicts) > 0:
        # Calculate additional cost from bumps
        total_bump_cost = 0
        for rd, count in conflicts.items():
            # Each additional player at this round costs (count-1) bumps
            for i in range(1, count):
                bump_rd = rd - i
                total_bump_cost += get_round_value(bump_rd) - get_round_value(rd)
        print(f"    Additional cost from round conflicts: ~${total_bump_cost:.0f}")

    # Legend
    print(f"\n{'='*105}")
    print("  LEGEND")
    print(f"{'='*105}")
    print("  Value   = Projected dollar value (SGP method)")
    print("  Rank    = Overall player ranking")
    print("  Kpr     = Keeper round (draft round - 3, or Rd 18 for undrafted)")
    print("  ADP     = Expected draft round based on rank (where they'd actually go)")
    print("  Save    = Rounds saved by keeping (ADP - Keeper Rd; positive = value)")
    print("  Surplus = Value - Cost (the 'profit' from keeping based on SGP)")
    print("  Yrs     = Years remaining you can keep (max 3 total)")
    print("  ◀       = Recommended keeper (top 8 by surplus)")
    print()
    print("  NOTE: ADP shows market value. A player with negative SGP surplus but")
    print("        positive ADP savings may still be worth keeping if they'd go")
    print("        earlier in an open draft than their keeper cost.")
    print()

    # Optional Statcast scan
    if scan_statcast and STATCAST_AVAILABLE:
        print(f"{'='*90}")
        print("  STATCAST ALERT SCAN")
        print(f"{'='*90}")
        print("  Scanning top keepers for velocity/exit velo changes...")

        # Scan top keepers
        players_to_scan = [
            {'Player': row['Player'], 'Position': row['Position']}
            for _, row in top_keepers.iterrows()
        ]

        results = analyze_keeper_list(players_to_scan, verbose=True)
        print(summarize_alerts(results))

    elif scan_statcast and not STATCAST_AVAILABLE:
        print("\n  Warning: Statcast scanning requested but pybaseball not installed.")
        print("  Run: pip install pybaseball")

    return analysis_df


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Analyze keepers for The Nudes'
    )
    parser.add_argument(
        '--scan-alerts', '-s',
        action='store_true',
        help='Scan keepers for Statcast velocity/exit velo changes'
    )
    args = parser.parse_args()

    run_analysis(scan_statcast=args.scan_alerts)
