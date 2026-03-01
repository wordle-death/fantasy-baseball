#!/usr/bin/env python3
"""
run_league_keeper_analysis.py - Analyze keepers for all teams in the league

Shows likely keepers and bubble players for each team.
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
INELIGIBLE_ROUNDS = [1, 2, 3]

# 2025 Final Standings - Keeper slots by team
TEAM_KEEPER_SLOTS = {
    'Giant City': 6,           # 1st
    'Fire Bad': 6,             # 2nd
    'Kiki Kankles': 6,         # 3rd
    'High Falls Heroes': 6,    # 4th
    'The Nudes': 8,            # 5th
    'Acuna Machado': 8,        # 6th
    'Cybulski Tax Service': 8, # 7th
    'K-Nines': 8,              # 8th
    'The Phenomenal Smiths': 7,# 9th
    'Jeters Never Win': 7,     # 10th
    'Topline Jobbers': 7,      # 11th
    'Bowls on Parade': 6,      # 12th
    'Hebrew Nationals': 6,     # 13th
    'The Funeral Home': 6,     # 14th
}

DEFAULT_KEEPER_SLOTS = 7  # Fallback if team not found

# Draft round value curve
DRAFT_ROUND_VALUES = {
    1: 50, 2: 42, 3: 35, 4: 30, 5: 26, 6: 23, 7: 20, 8: 18,
    9: 16, 10: 14, 11: 12, 12: 10, 13: 9, 14: 8, 15: 7,
    16: 6, 17: 5, 18: 4, 19: 3, 20: 2, 21: 2, 22: 1, 23: 1, 24: 1, 25: 1
}


def fuzzy_match(name1: str, name2: str) -> float:
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    return SequenceMatcher(None, n1, n2).ratio()


def find_player_value(player_name: str, valuations_df: pd.DataFrame) -> dict:
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
        if score > best_score and score > 0.8:
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
    round_num = max(1, min(25, round_num))
    return DRAFT_ROUND_VALUES.get(round_num, 1)


def analyze_team(team_name: str, roster: pd.DataFrame, valuations: pd.DataFrame, num_keepers: int) -> dict:
    """Analyze keeper candidates for a single team."""
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
            ineligibility_reason = f"Rd {draft_round}"
        elif years_kept >= MAX_YEARS_KEPT:
            is_ineligible = True
            ineligibility_reason = f"{years_kept}yr kept"

        # Find player value
        value_info = find_player_value(player, valuations)

        if not value_info['found']:
            ineligible.append({
                'Player': player,
                'Position': position,
                'Reason': "Not in projections"
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

        analysis.append({
            'Player': player,
            'Position': position,
            'Value': value_info['dollar_value'],
            'Overall_Rank': value_info['overall_rank'],
            'Draft_Round': draft_round if draft_round > 0 else 'UD',
            'Keeper_Round': keeper_round,
            'Keeper_Cost': keeper_cost,
            'Surplus': surplus_value,
            'Years_Kept': years_kept
        })

    # Sort by surplus value
    analysis_df = pd.DataFrame(analysis) if analysis else pd.DataFrame()
    if len(analysis_df) > 0:
        analysis_df = analysis_df.sort_values('Surplus', ascending=False)

    return {
        'team': team_name,
        'num_keepers': num_keepers,
        'eligible': analysis_df,
        'ineligible': ineligible
    }


def run_league_analysis(scan_statcast: bool = False):
    """Run keeper analysis for all teams.

    Args:
        scan_statcast: If True, run Statcast analysis on likely keepers
    """
    data_dir = Path(__file__).parent / 'data'
    proj_dir = data_dir / 'projections'
    roster_dir = data_dir / 'rosters'

    # Load SGP valuations
    valuations_file = proj_dir / 'sgp_player_values_v3.csv'
    if not valuations_file.exists():
        print("Error: Run SGP valuation first (python -m src.sgp_valuation)")
        return

    valuations = pd.read_csv(valuations_file)
    print(f"Loaded {len(valuations)} player valuations")

    # Load league rosters
    roster_file = roster_dir / 'yahoo_league.csv'
    all_rosters = pd.read_csv(roster_file)

    # Get all teams
    teams = all_rosters['Team'].unique()
    print(f"Analyzing {len(teams)} teams\n")

    print("=" * 100)
    print("  LEAGUE-WIDE KEEPER PREDICTIONS")
    print("=" * 100)

    all_keepers = []
    all_bubble = []  # Track players teams can't keep (draft targets)

    for team in sorted(teams):
        team_roster = all_rosters[all_rosters['Team'] == team].copy()
        num_keepers = TEAM_KEEPER_SLOTS.get(team, DEFAULT_KEEPER_SLOTS)

        result = analyze_team(team, team_roster, valuations, num_keepers)
        eligible = result['eligible']
        ineligible = result['ineligible']

        print(f"\n{'─' * 100}")
        print(f"  {team.upper()} ({num_keepers} keepers)")
        print(f"{'─' * 100}")

        if len(eligible) == 0:
            print("  No eligible keepers found")
            continue

        # Show likely keepers
        likely_keepers = eligible.head(num_keepers)
        # Top 3 players they CAN'T keep (regardless of surplus)
        bubble_players = eligible.iloc[num_keepers:num_keepers+3]

        print(f"  {'#':<2} {'Player':<22} {'Pos':<8} {'Value':>6} {'Rank':>4} │ {'Kpr Rd':>6} │ {'Surplus':>7}")
        print(f"  {'-' * 70}")

        for i, (_, row) in enumerate(likely_keepers.iterrows(), 1):
            rd_str = f"Rd {row['Keeper_Round']}"
            print(f"  {i:<2} {row['Player']:<22} {row['Position']:<8} ${row['Value']:>4.0f} {int(row['Overall_Rank']):>4} │ {rd_str:>6} │ ${row['Surplus']:>5.1f}")
            all_keepers.append({
                'Team': team,
                'Player': row['Player'],
                'Position': row['Position'],
                'Value': row['Value'],
                'Rank': row['Overall_Rank'],
                'Keeper_Round': row['Keeper_Round'],
                'Surplus': row['Surplus']
            })

        # Show top 3 players they can't keep (draft targets)
        if len(bubble_players) > 0:
            print(f"  {'─' * 70}")
            print(f"  Can't Keep (returning to draft pool):")
            for _, row in bubble_players.iterrows():
                rd_str = f"Rd {row['Keeper_Round']}"
                print(f"     {row['Player']:<22} {row['Position']:<8} ${row['Value']:>4.0f} {int(row['Overall_Rank']):>4} │ {rd_str:>6} │ ${row['Surplus']:>5.1f}")
                all_bubble.append({
                    'Team': team,
                    'Player': row['Player'],
                    'Position': row['Position'],
                    'Value': row['Value'],
                    'Rank': row['Overall_Rank']
                })

        # Show notable ineligible players (high-value players they can't keep)
        notable_ineligible = [p for p in ineligible if 'Value' in p and p['Value'] >= 20]
        if notable_ineligible:
            print(f"  {'─' * 70}")
            print(f"  Ineligible (high-value, returning to draft):")
            for p in notable_ineligible[:3]:
                print(f"     {p['Player']:<22} ${p['Value']:.0f} - {p['Reason']}")
                all_bubble.append({
                    'Team': team,
                    'Player': p['Player'],
                    'Position': p['Position'],
                    'Value': p['Value'],
                    'Rank': p.get('Rank', 999)
                })

    # Summary
    print(f"\n{'=' * 100}")
    print("  KEEPER SUMMARY")
    print(f"{'=' * 100}")
    print(f"  Total projected keepers: {len(all_keepers)}")

    # Count by round
    keeper_df = pd.DataFrame(all_keepers)
    if len(keeper_df) > 0:
        round_counts = keeper_df['Keeper_Round'].value_counts().sort_index()
        print(f"\n  Keepers by round:")
        for rd, count in round_counts.items():
            print(f"    Round {int(rd):>2}: {count} keepers")

    # Draft Pool Analysis - Best players returning to draft
    print(f"\n{'=' * 100}")
    print("  DRAFT POOL: BEST PLAYERS RETURNING")
    print(f"{'=' * 100}")

    if all_bubble:
        # Sort by value and show top 20
        sorted_bubble = sorted(all_bubble, key=lambda x: x['Value'], reverse=True)

        print(f"\n  Top 20 Draft Targets (players teams can't keep):")
        print(f"  {'Rank':<5} {'Player':<24} {'Team':<22} {'Pos':<8} {'Value':>6}")
        print(f"  {'-' * 75}")

        for i, p in enumerate(sorted_bubble[:20], 1):
            print(f"  {i:<5} {p['Player']:<24} {p['Team']:<22} {p['Position']:<8} ${p['Value']:>4.0f}")

        # Position breakdown
        print(f"\n  By Position (returning to draft pool):")
        positions = {}
        for p in all_bubble:
            pos = p['Position'].split(',')[0] if ',' in p['Position'] else p['Position']
            if pos not in positions:
                positions[pos] = []
            positions[pos].append(p['Value'])

        for pos in sorted(positions.keys()):
            values = positions[pos]
            avg_val = sum(values) / len(values)
            print(f"    {pos:<6}: {len(values):>2} players (avg ${avg_val:.0f})")

    # Optional Statcast analysis
    if scan_statcast and STATCAST_AVAILABLE:
        print(f"\n{'=' * 100}")
        print("  STATCAST ALERT SCAN")
        print(f"{'=' * 100}")
        print("  Scanning likely keepers for velocity/exit velo changes...")
        print("  (This may take a few minutes due to API calls)")

        # Convert all_keepers to format expected by analyze_keeper_list
        players_to_scan = [
            {'Player': k['Player'], 'Position': k['Position']}
            for k in all_keepers
        ]

        results = analyze_keeper_list(players_to_scan, verbose=True)
        print(summarize_alerts(results))

    elif scan_statcast and not STATCAST_AVAILABLE:
        print("\n  Warning: Statcast scanning requested but pybaseball not installed.")
        print("  Run: pip install pybaseball")

    return all_keepers


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Analyze keepers for all teams in the league'
    )
    parser.add_argument(
        '--scan-alerts', '-s',
        action='store_true',
        help='Scan likely keepers for Statcast velocity/exit velo changes'
    )
    args = parser.parse_args()

    run_league_analysis(scan_statcast=args.scan_alerts)
