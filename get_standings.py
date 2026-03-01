#!/usr/bin/env python3
"""
get_standings.py - Fetch league standings from Yahoo

Run this script and it will output the 2025 standings.
"""

import sys
sys.path.insert(0, 'src')

from yahoo_import import get_yahoo_query

LEAGUE_ID = "27545"
GAME_ID = 458

def main():
    print("Fetching standings from Yahoo...\n")

    query = get_yahoo_query(LEAGUE_ID, game_code="mlb", season=2025, game_id=GAME_ID)
    if not query:
        print("Failed to connect. Check auth.")
        return

    try:
        standings = query.get_league_standings()

        print("2025 FINAL STANDINGS")
        print("=" * 40)

        teams_by_rank = []
        for team in standings.teams:
            t = team.team
            rank = int(t.team_standings.rank) if hasattr(t, 'team_standings') else 99
            teams_by_rank.append((rank, t.name))

        teams_by_rank.sort()

        for rank, name in teams_by_rank:
            keepers = 6  # default
            if 1 <= rank <= 4:
                keepers = 6
            elif 5 <= rank <= 8:
                keepers = 8
            elif 9 <= rank <= 11:
                keepers = 7
            else:
                keepers = 6
            print(f"{rank:>2}. {name:<25} ({keepers} keepers)")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
