#!/usr/bin/env python3
"""
refresh_yahoo_rosters.py - Non-interactive Yahoo roster refresh

Usage: python refresh_yahoo_rosters.py
"""

import sys
sys.path.insert(0, 'src')

from yahoo_import import get_yahoo_query, get_all_rosters, save_rosters_to_csv

# League configuration from CLAUDE.md
LEAGUE_ID = "27545"
SEASON = 2026
GAME_ID = 469  # Yahoo game_id for MLB 2026

def main():
    print("=" * 60)
    print("  YAHOO FANTASY ROSTER REFRESH")
    print("=" * 60)
    print(f"\nLeague ID: {LEAGUE_ID}")
    print(f"Season: {SEASON}")
    print(f"Game ID: {GAME_ID}")
    print("\nConnecting to Yahoo Fantasy API...")
    print("(A browser window may open for authentication if needed)\n")

    try:
        query = get_yahoo_query(LEAGUE_ID, game_code="mlb", season=SEASON, game_id=GAME_ID)
        if not query:
            print("Failed to create Yahoo query. Check credentials.")
            return 1

        print("Fetching rosters for all teams...\n")
        rosters = get_all_rosters(query)

        if rosters:
            output_file = save_rosters_to_csv(rosters)
            print("\n" + "=" * 60)
            print("  REFRESH COMPLETE!")
            print("=" * 60)
            print(f"\nRosters saved to: {output_file}")

            # Show summary
            total_players = sum(len(r) for r in rosters.values())
            print(f"Total teams: {len(rosters)}")
            print(f"Total players: {total_players}")
            return 0
        else:
            print("No rosters retrieved. Check league ID and try again.")
            return 1

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
