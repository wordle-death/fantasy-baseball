#!/usr/bin/env python3
"""
merge_draft_history.py - Merge draft history data into Yahoo roster

Yahoo roster has current position eligibility.
Draft history has DraftRound and YearsKept.
This script merges them using fuzzy matching.
"""

import pandas as pd
from pathlib import Path
from difflib import SequenceMatcher


def fuzzy_match(name1: str, name2: str) -> float:
    """Calculate similarity between two player names."""
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    return SequenceMatcher(None, n1, n2).ratio()


def merge_rosters():
    """
    Merge draft history into Yahoo roster.

    IMPORTANT: Players may have been traded, so we match by player NAME
    across ALL teams in the draft history, not just the current team.
    """
    data_dir = Path(__file__).parent / 'data' / 'rosters'

    # Load files
    yahoo = pd.read_csv(data_dir / 'yahoo_league.csv')
    draft = pd.read_csv(data_dir / 'draft_2025_parsed.csv')

    print(f"Loaded {len(yahoo)} Yahoo roster entries")
    print(f"Loaded {len(draft)} draft history entries")

    # Build GLOBAL draft lookup: {player_lower: (round, years, original_team)}
    # This allows matching traded players to their original draft position
    all_drafted = {}
    for _, row in draft.iterrows():
        player = row['Player'].lower().strip()
        draft_round = row['DraftRound']
        years_kept = row['YearsKept']
        original_team = row['Team']

        # Store player's draft info (first occurrence wins if duplicates)
        if player not in all_drafted:
            all_drafted[player] = (draft_round, years_kept, original_team)

    print(f"Built lookup for {len(all_drafted)} unique drafted players")

    # Match Yahoo roster to draft history by NAME (across all teams)
    matches = 0
    fuzzy_matches = 0
    traded = []
    no_match = []

    for idx, row in yahoo.iterrows():
        current_team = row['Team']
        player = row['Player']
        player_lower = player.lower().strip()

        # Try exact match first (across ALL teams)
        if player_lower in all_drafted:
            round_val, years, original_team = all_drafted[player_lower]
            yahoo.at[idx, 'DraftRound'] = round_val
            yahoo.at[idx, 'YearsKept'] = years
            matches += 1
            if original_team != current_team:
                traded.append((player, original_team, current_team, round_val))
            continue

        # Try fuzzy matching across ALL drafted players
        best_match = None
        best_score = 0
        for draft_player, (round_val, years, orig_team) in all_drafted.items():
            score = fuzzy_match(player, draft_player)
            if score > best_score and score > 0.8:
                best_score = score
                best_match = (draft_player, round_val, years, orig_team)

        if best_match:
            yahoo.at[idx, 'DraftRound'] = best_match[1]
            yahoo.at[idx, 'YearsKept'] = best_match[2]
            fuzzy_matches += 1
            if best_match[3] != current_team:
                traded.append((player, best_match[3], current_team, best_match[1]))
        else:
            # No match - treat as undrafted pickup (Round 0 -> keeper round 15)
            yahoo.at[idx, 'DraftRound'] = 0
            yahoo.at[idx, 'YearsKept'] = 0
            no_match.append((current_team, player))

    print(f"\nMatching results:")
    print(f"  Exact matches: {matches}")
    print(f"  Fuzzy matches: {fuzzy_matches}")
    print(f"  Traded players found: {len(traded)}")
    print(f"  Undrafted (waiver pickups): {len(no_match)}")

    # Show traded players
    if traded:
        print(f"\n  Traded players matched to original draft:")
        for player, orig, curr, rd in traded[:10]:  # Show first 10
            print(f"    {player}: {orig} → {curr} (Rd {rd})")

    # Save updated roster
    output_file = data_dir / 'yahoo_league.csv'
    yahoo.to_csv(output_file, index=False)
    print(f"\nSaved updated roster to: {output_file}")

    # Show The Nudes roster with draft info
    nudes = yahoo[yahoo['Team'] == 'The Nudes'].sort_values('DraftRound')
    print(f"\n{'='*70}")
    print(f"  THE NUDES - ROSTER WITH DRAFT HISTORY")
    print(f"{'='*70}")
    print(f"{'Player':<25} {'Position':<12} {'Round':>6} {'YrsKept':>8}")
    print(f"{'-'*70}")
    for _, row in nudes.iterrows():
        rd = row['DraftRound'] if row['DraftRound'] > 0 else 'UD'
        print(f"{row['Player']:<25} {row['Position']:<12} {str(rd):>6} {int(row['YearsKept']):>8}")

    return yahoo


if __name__ == '__main__':
    merge_rosters()
