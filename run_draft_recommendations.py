#!/usr/bin/env python3
"""
run_draft_recommendations.py - CLI draft recommendation tool

Usage:
    # Using Google Sheets (live draft board):
    python run_draft_recommendations.py --round 7

    # Using CSV data (offline/testing):
    python run_draft_recommendations.py --round 7 --offline

    # Specify number of recommendations:
    python run_draft_recommendations.py --round 7 -n 10

    # Custom weights:
    python run_draft_recommendations.py --round 7 --weights 0.5,0.2,0.2,0.1

    # Simulate: provide keepers + picks manually:
    python run_draft_recommendations.py --round 7 --roster "Garrett Crochet,Jackson Chourio,Elly De La Cruz"
"""

import argparse
import pandas as pd
from pathlib import Path
from urllib.parse import quote_plus

from src.draft import (
    get_recommendations, format_recommendations,
    project_team_totals, calculate_league_targets,
    calculate_category_needs, calculate_position_needs,
    load_prospect_watchlist, merge_watchlist,
    DRAFT_ROUND_VALUES, HITTING_CATS, PITCHING_CATS,
)
from src.sheets import connect_to_sheets, get_draft_board

# Statcast alerts (optional — pybaseball may not be installed)
try:
    from src.statcast_news import analyze_keeper_list, summarize_alerts, get_news_search_query
    STATCAST_AVAILABLE = True
except ImportError:
    STATCAST_AVAILABLE = False


import re
import unicodedata

def normalize_name(name: str) -> str:
    """Normalize a player name for matching (strip accents, suffixes, lowercase)."""
    # Decompose unicode accents and strip combining characters
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = ''.join(c for c in nfkd if not unicodedata.combining(c))
    name = ascii_name.lower().strip()
    # Strip common suffixes: Jr., Jr, Sr., Sr, II, III, IV
    name = re.sub(r'\b(jr\.?|sr\.?|ii|iii|iv)\s*$', '', name).strip()
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)
    return name


def load_sgp_values(path: str = None) -> pd.DataFrame:
    """Load the SGP player valuations."""
    if path is None:
        path = Path('data/projections/sgp_player_values_v3.csv')
    return pd.read_csv(path)


def build_roster_from_names(player_names: list, sgp_values: pd.DataFrame) -> pd.DataFrame:
    """Build a roster DataFrame from a list of player names."""
    rows = []
    for name in player_names:
        name = name.strip()
        if not name:
            continue
        rows.append({'Player': name, 'Round': 0})
    return pd.DataFrame(rows)


def build_roster_from_draft_csv(csv_path: str, team_name: str = 'The Nudes',
                                max_round: int = None) -> pd.DataFrame:
    """
    Build a roster from the draft CSV, optionally limited to a specific round.

    This lets you simulate "what if the draft is at round N" using 2025 data.
    """
    df = pd.read_csv(csv_path)
    team_df = df[df['Team'] == team_name].copy()

    if max_round is not None:
        team_df = team_df[team_df['DraftRound'] <= max_round]

    return team_df.rename(columns={'DraftRound': 'Round'})


def get_drafted_players_from_csv(csv_path: str, max_round: int = None) -> set:
    """Get all drafted player names from the CSV, up to a specific round."""
    df = pd.read_csv(csv_path)
    if max_round is not None:
        df = df[df['DraftRound'] <= max_round]
    return set(df['Player'].dropna().apply(normalize_name))


def display_team_state(team_totals: dict, targets: dict, category_needs: dict,
                       position_needs: dict):
    """Display current team state and needs."""
    print(f"\n{'─'*60}")
    print(f"  TEAM STATE")
    print(f"{'─'*60}")

    print(f"\n  Category Projections:")
    print(f"  {'Category':<10} {'My Team':>10} {'Target':>10} {'Gap':>10} {'Need':>8}")
    print(f"  {'-'*48}")

    all_cats = HITTING_CATS + PITCHING_CATS
    for cat in all_cats:
        my_val = team_totals.get(cat, 0)
        target = targets.get(cat, 0)
        need = category_needs.get(cat, 0)

        if cat in ('OBP', 'ERA', 'WHIP'):
            gap = target - my_val if cat == 'OBP' else my_val - target
            my_str = f"{my_val:.3f}"
            target_str = f"{target:.3f}"
            gap_str = f"{gap:+.3f}"
        else:
            gap = target - my_val
            my_str = f"{my_val:.0f}"
            target_str = f"{target:.0f}"
            gap_str = f"{gap:+.0f}"

        need_indicator = "HIGH" if need > 1.0 else "ok" if need > 0 else "SURPLUS"
        print(f"  {cat:<10} {my_str:>10} {target_str:>10} {gap_str:>10} {need_indicator:>8}")

    print(f"\n  Position Needs:")
    for pos, need in sorted(position_needs.items(), key=lambda x: -x[1]):
        status = "EMPTY" if need >= 1.5 else "partial" if need >= 1.2 else "filled"
        print(f"    {pos:<5} {status}")


def main():
    parser = argparse.ArgumentParser(description='Draft recommendations')
    parser.add_argument('--round', type=int, required=True, help='Current draft round (1-25)')
    parser.add_argument('-n', '--num', type=int, default=8, help='Number of recommendations')
    parser.add_argument('--offline', action='store_true', help='Use 2025 CSV data for simulation')
    parser.add_argument('--keepers', action='store_true',
                        help='Read keepers from Google Sheets 2026 tab; use your keepers as roster')
    parser.add_argument('--sim', action='store_true',
                        help='Simulate by removing top players by ADP (more realistic than --offline)')
    parser.add_argument('--roster', type=str, help='Comma-separated player names for your roster')
    parser.add_argument('--team', type=str, default='The Nudes', help='Team name')
    parser.add_argument('--weights', type=str, help='Custom weights: surplus,category,position,keeper')
    parser.add_argument('--values', type=str, help='Path to SGP values CSV')
    parser.add_argument('--draft-csv', type=str, help='Path to draft CSV (for simulation)')
    parser.add_argument('--scan-alerts', action='store_true',
                        help='Scan recommended players for Statcast velocity/spin alerts')
    args = parser.parse_args()

    # Load SGP values
    sgp_values = load_sgp_values(args.values)
    print(f"Loaded {len(sgp_values)} player valuations")

    # Parse weights
    weights = None
    if args.weights:
        parts = [float(x) for x in args.weights.split(',')]
        if len(parts) == 4:
            weights = {
                'surplus': parts[0], 'category': parts[1],
                'position': parts[2], 'keeper': parts[3],
            }

    # Build roster and determine drafted/kept players
    if args.keepers:
        # Read keepers from Google Sheets 2026 tab
        print("Connecting to Google Sheets...")
        client = connect_to_sheets()
        board = get_draft_board(client, tab_name='2026')
        all_picked = board[board['IsPicked'] == True].copy()

        # Filter out trade annotations
        all_picked = all_picked[~all_picked['Player'].str.contains('TRADED', case=False, na=False)]

        # All kept/drafted players are unavailable (normalized for accent/typo matching)
        drafted_players = set(
            normalize_name(p) for p in all_picked['Player'].dropna()
        )

        # Build my roster from my keepers
        my_keepers = all_picked[all_picked['Team'] == args.team]
        my_roster = pd.DataFrame({
            'Player': my_keepers['Player'].values,
            'Round': my_keepers['Round'].values,
        })
        print(f"Loaded {len(my_roster)} keepers for {args.team}")
        print(f"Total kept players across league: {len(drafted_players)}")

    elif args.roster:
        # Manual roster input
        names = args.roster.split(',')
        my_roster = build_roster_from_names(names, sgp_values)
        drafted_players = set(n.lower().strip() for n in names)
    elif args.sim:
        # ADP-based simulation: remove top N players by ADP, assume empty roster
        # This simulates "what would round N look like in a typical draft?"
        num_gone = (args.round - 1) * 14  # 14 teams × (round - 1) picks
        players_with_adp = sgp_values[sgp_values['ADP'].notna() & (sgp_values['ADP'] > 0)]
        players_with_adp = players_with_adp.sort_values('ADP')
        gone_by_adp = set(players_with_adp.head(num_gone)['Name'].str.lower().str.strip())
        drafted_players = gone_by_adp
        my_roster = pd.DataFrame(columns=['Player', 'Round'])
        print(f"ADP simulation: removed top {num_gone} players by ADP (rounds 1-{args.round - 1})")
        print(f"Your roster is empty (no keepers specified)")
    elif args.draft_csv or args.offline:
        # Simulate using draft CSV
        csv_path = args.draft_csv or 'data/rosters/draft_2025_parsed.csv'
        my_roster = build_roster_from_draft_csv(csv_path, args.team, max_round=args.round - 1)
        drafted_players = get_drafted_players_from_csv(csv_path, max_round=args.round - 1)
        print(f"Loaded {len(my_roster)} players for {args.team} through round {args.round - 1}")
        print(f"Total players drafted by all teams: {len(drafted_players)}")
    else:
        # Live Google Sheets mode — reads current draft state
        print("Connecting to Google Sheets...")
        client = connect_to_sheets()
        board = get_draft_board(client, tab_name='2026')
        all_picked = board[board['IsPicked'] == True].copy()
        all_picked = all_picked[~all_picked['Player'].str.contains('TRADED', case=False, na=False)]

        drafted_players = set(
            normalize_name(p) for p in all_picked['Player'].dropna()
        )

        my_picks = all_picked[all_picked['Team'] == args.team]
        my_roster = pd.DataFrame({
            'Player': my_picks['Player'].values,
            'Round': my_picks['Round'].values,
        })
        print(f"Loaded {len(my_roster)} picks for {args.team}")
        print(f"Total drafted/kept players: {len(drafted_players)}")

    # Filter to available players (use normalized names for accent/typo tolerance)
    available = sgp_values[
        ~sgp_values['Name'].apply(normalize_name).isin(drafted_players)
    ].copy()

    # Merge prospect watchlist
    watchlist = load_prospect_watchlist()
    if not watchlist.empty:
        available = merge_watchlist(available, watchlist)
        print(f"Added {len(watchlist)} prospect watchlist players")

    print(f"Available players: {len(available)}")

    # Show team state
    team_totals = project_team_totals(my_roster, sgp_values)
    targets = calculate_league_targets(sgp_values)
    category_needs = calculate_category_needs(team_totals, targets)
    position_needs = calculate_position_needs(my_roster, sgp_values)
    display_team_state(team_totals, targets, category_needs, position_needs)

    # Get recommendations
    recs = get_recommendations(
        available_players=available,
        my_roster=my_roster,
        sgp_values=sgp_values,
        current_round=args.round,
        num_recommendations=args.num,
        weights=weights,
    )

    # Display
    output = format_recommendations(recs, args.round, category_needs)
    print(output)

    # News search links for each recommendation
    if not recs.empty:
        print(f"\n{'─'*60}")
        print(f"  NEWS LINKS")
        print(f"{'─'*60}")
        for _, row in recs.iterrows():
            name = row.get('Name', '?')
            pos = row.get('primary_position', '?')
            query = f"{name} MLB 2026 fantasy baseball news"
            url = f"https://news.google.com/search?q={quote_plus(query)}"
            print(f"  {name} ({pos}): {url}")

    # Statcast alerts
    if args.scan_alerts:
        if not STATCAST_AVAILABLE:
            print("\nStatcast scanning requires pybaseball: pip install pybaseball")
        elif not recs.empty:
            print(f"\n{'─'*60}")
            print(f"  STATCAST ALERTS")
            print(f"{'─'*60}")
            players_to_scan = []
            for _, row in recs.iterrows():
                pos = row.get('primary_position', 'Util')
                players_to_scan.append({
                    'Player': row['Name'],
                    'Position': pos,
                })
            results = analyze_keeper_list(players_to_scan, verbose=True)
            print(summarize_alerts(results))


if __name__ == '__main__':
    main()
