"""
yahoo_import.py - Import roster data from Yahoo Fantasy Baseball

FIRST-TIME SETUP:
1. Go to https://developer.yahoo.com/apps/
2. Click "Create an App"
3. Fill in:
   - Application Name: "Fantasy Baseball Keeper Tool" (or anything)
   - Application Type: Select "Installed Application"
   - Description: Optional
   - Redirect URI(s): Leave blank (or use "oob")
   - API Permissions: Check "Fantasy Sports"
4. Click "Create App"
5. Copy your Client ID (Consumer Key) and Client Secret (Consumer Secret)
6. Create a file called 'yahoo_credentials.json' in this project folder with:
   {
     "consumer_key": "YOUR_CLIENT_ID",
     "consumer_secret": "YOUR_CLIENT_SECRET"
   }
7. Run this script - it will open a browser for you to authorize
8. Paste the verification code when prompted

After first auth, your token is saved and you won't need to re-authenticate.
"""

import json
from pathlib import Path
import pandas as pd

# Check if yfpy is installed
try:
    from yfpy.query import YahooFantasySportsQuery
except ImportError:
    print("Error: yfpy package not installed.")
    print("Run: pip install yfpy")
    print("Or: pip install -r requirements.txt")
    exit(1)


def setup_credentials():
    """Check if Yahoo credentials are set up."""
    creds_file = Path(__file__).parent.parent / 'yahoo_credentials.json'

    if not creds_file.exists():
        print("\n" + "=" * 60)
        print("  YAHOO FANTASY API SETUP REQUIRED")
        print("=" * 60)
        print("""
To connect to Yahoo Fantasy, you need to create a Developer App:

1. Go to: https://developer.yahoo.com/apps/
2. Click "Create an App"
3. Fill in:
   - Application Name: "Fantasy Baseball Keeper Tool"
   - Application Type: "Installed Application"
   - API Permissions: Check "Fantasy Sports"
4. Click "Create App"
5. Copy the Client ID and Client Secret

Now create a file called 'yahoo_credentials.json' in the project folder:
""")
        print(f"  Location: {creds_file}")
        print("""
Contents:
{
  "consumer_key": "YOUR_CLIENT_ID_HERE",
  "consumer_secret": "YOUR_CLIENT_SECRET_HERE"
}
""")
        print("After creating the file, run this script again.")
        print("=" * 60)
        return None

    with open(creds_file) as f:
        creds = json.load(f)

    if creds.get('consumer_key') == 'YOUR_CLIENT_ID_HERE':
        print("Error: Please update yahoo_credentials.json with your actual credentials.")
        return None

    return creds


def get_yahoo_query(league_id: str, game_code: str = "mlb", season: int = 2025, game_id: int = None):
    """
    Create a Yahoo Fantasy API query object.

    Args:
        league_id: Your Yahoo league ID (found in the league URL)
        game_code: "mlb" for baseball
        season: The season year to query
        game_id: Yahoo game ID (458 for MLB 2025, 422 for MLB 2024, etc.)

    Returns:
        YahooFantasySportsQuery object
    """
    creds = setup_credentials()
    if not creds:
        return None

    # Path for storing auth token (so you don't have to re-auth every time)
    auth_dir = Path(__file__).parent.parent

    query = YahooFantasySportsQuery(
        auth_dir=str(auth_dir),
        league_id=league_id,
        game_code=game_code,
        game_id=game_id,  # Explicit game_id for the season
        offline=False,
        all_output_as_json_str=False,
        consumer_key=creds['consumer_key'],
        consumer_secret=creds['consumer_secret'],
        browser_callback=True
    )

    return query


def get_league_teams(query) -> list:
    """Get all teams in the league."""
    teams = query.get_league_teams()
    return teams


def get_team_roster(query, team_key: str) -> list:
    """Get the roster for a specific team."""
    roster = query.get_team_roster_by_week(team_key, week="current")
    return roster


def get_all_rosters(query) -> dict:
    """
    Get rosters for all teams in the league.

    Returns:
        Dict of {team_name: roster_dataframe}
    """
    print("Fetching league teams...")
    teams = query.get_league_teams()

    all_rosters = {}

    for team in teams:
        team_name = team.name.decode() if isinstance(team.name, bytes) else team.name
        team_key = team.team_key
        # Extract just the team number (e.g., "1" from "458.l.27545.t.1")
        team_num = team_key.split('.t.')[-1]

        print(f"  Fetching roster for {team_name}...")

        try:
            # Use get_team_info which includes roster data
            team_info = query.get_team_info(team_num)

            if not hasattr(team_info, 'roster') or not team_info.roster:
                print(f"    No roster found for {team_name}")
                continue

            roster = team_info.roster
            players = []

            # roster.players is a list of player objects
            if hasattr(roster, 'players'):
                for player_entry in roster.players:
                    # Each entry has a 'player' attribute with the actual data
                    player = player_entry.get('player', player_entry) if isinstance(player_entry, dict) else player_entry

                    # Get player name
                    if hasattr(player, 'name'):
                        if hasattr(player.name, 'full'):
                            player_name = player.name.full
                        else:
                            player_name = str(player.name)
                    else:
                        player_name = str(player)

                    # Get position
                    if hasattr(player, 'display_position'):
                        position = player.display_position
                    elif hasattr(player, 'primary_position'):
                        position = player.primary_position
                    else:
                        position = 'Unknown'

                    player_data = {
                        'Player': player_name,
                        'Position': position,
                        'Team': team_name,
                        'DraftRound': 0,  # Will update from draft results
                        'YearsKept': 0    # Will need manual input
                    }
                    players.append(player_data)

            all_rosters[team_name] = pd.DataFrame(players)
            print(f"    Found {len(players)} players")

        except Exception as e:
            print(f"    Error fetching {team_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return all_rosters


def get_draft_results(query) -> pd.DataFrame:
    """
    Get the draft results to determine what round each player was drafted.

    Returns:
        DataFrame with player names and draft rounds
    """
    print("Fetching draft results...")

    try:
        draft_results = query.get_league_draft_results()

        picks = []
        for pick in draft_results:
            pick_data = {
                'Player': pick.player_key,  # May need to resolve to name
                'DraftRound': pick.round,
                'DraftPick': pick.pick,
                'Team': pick.team_key
            }
            picks.append(pick_data)

        return pd.DataFrame(picks)

    except Exception as e:
        print(f"Error fetching draft results: {e}")
        return pd.DataFrame()


def save_rosters_to_csv(all_rosters: dict, output_dir: Path = None):
    """Save all rosters to a single CSV file for the keeper tool."""
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / 'data' / 'rosters'

    output_dir.mkdir(parents=True, exist_ok=True)

    # Combine all rosters into one dataframe
    combined = []
    for team_name, roster_df in all_rosters.items():
        roster_df['Team'] = team_name
        combined.append(roster_df)

    all_players = pd.concat(combined, ignore_index=True)

    # Reorder columns
    columns = ['Team', 'Player', 'Position', 'DraftRound', 'YearsKept']
    all_players = all_players[columns]

    output_file = output_dir / 'yahoo_league.csv'
    all_players.to_csv(output_file, index=False)

    print(f"\nSaved {len(all_players)} players to: {output_file}")
    return output_file


def interactive_import():
    """Interactive import process."""
    print("\n" + "=" * 60)
    print("  YAHOO FANTASY ROSTER IMPORT")
    print("=" * 60)

    # Check credentials first
    creds = setup_credentials()
    if not creds:
        return

    # Get league ID from user
    print("\nYou'll need your Yahoo League ID.")
    print("Find it in your league URL: https://baseball.fantasysports.yahoo.com/b1/XXXXX")
    print("The XXXXX part is your league ID.\n")

    league_id = input("Enter your League ID: ").strip()

    if not league_id:
        print("No league ID provided. Exiting.")
        return

    # Get season
    season = input("Enter season year (default 2024): ").strip() or "2024"
    season = int(season)

    print(f"\nConnecting to Yahoo Fantasy for league {league_id}, season {season}...")
    print("(A browser window may open for authentication)\n")

    try:
        query = get_yahoo_query(league_id, season=season)
        if not query:
            return

        # Get all rosters
        rosters = get_all_rosters(query)

        if rosters:
            # Save to CSV
            output_file = save_rosters_to_csv(rosters)

            print("\n" + "=" * 60)
            print("  IMPORT COMPLETE!")
            print("=" * 60)
            print(f"\nRosters saved to: {output_file}")
            print("\nNext steps:")
            print("1. Review the CSV file")
            print("2. Add DraftRound values (from draft history)")
            print("3. Add YearsKept values (for players kept previously)")
            print("4. Run: python analyze_keepers.py --league --league-file data/rosters/yahoo_league.csv")
        else:
            print("No rosters retrieved. Check your league ID and try again.")

    except Exception as e:
        print(f"\nError: {e}")
        print("\nTroubleshooting:")
        print("- Make sure your League ID is correct")
        print("- Check that the season year matches your league")
        print("- Try re-authenticating by deleting the token file")


if __name__ == '__main__':
    interactive_import()
