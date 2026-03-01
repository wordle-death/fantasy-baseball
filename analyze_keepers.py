#!/usr/bin/env python3
"""
analyze_keepers.py - Main entry point for Fantasy Baseball Keeper Analysis

USAGE:
    python analyze_keepers.py              # Analyze your team only
    python analyze_keepers.py --league     # Predict all teams' keepers
    python analyze_keepers.py --setup      # Create sample data files
    python analyze_keepers.py --help       # Show help

This tool helps you decide which players to keep for your fantasy baseball draft.
It calculates "keeper value" (surplus value) based on:
    1. Projected player performance (from Fangraphs)
    2. Your keeper cost (last year's draft round - 3)

Higher keeper value = better keeper decision.
"""

import argparse
from pathlib import Path


def setup_sample_data():
    """Create sample projection and roster files for testing."""
    from src.data_loader import create_sample_projections, create_sample_roster, create_sample_league

    print("\n" + "=" * 60)
    print("  CREATING SAMPLE DATA")
    print("=" * 60 + "\n")

    create_sample_projections()
    create_sample_roster()
    create_sample_league()

    print("\nSample data created! You can now run:")
    print("  python analyze_keepers.py           # Your team only")
    print("  python analyze_keepers.py --league  # All teams + available players")
    print()


def run_analysis(hitter_file: str = None,
                 pitcher_file: str = None,
                 roster_file: str = None,
                 num_keepers: int = 8):
    """
    Run the full keeper analysis.

    Args:
        hitter_file: Path to hitter projections CSV (or None for sample)
        pitcher_file: Path to pitcher projections CSV (or None for sample)
        roster_file: Path to your roster CSV (or None for sample)
        num_keepers: Number of keeper slots you have
    """
    from src.data_loader import load_hitter_projections, load_pitcher_projections, load_roster
    from src.valuation import calculate_hitter_zscores, calculate_pitcher_zscores, combine_player_values, display_top_players
    from src.keepers import calculate_keeper_values, display_keeper_recommendations

    # Default to sample data if no files provided
    data_dir = Path(__file__).parent / 'data'
    proj_dir = data_dir / 'projections'
    roster_dir = data_dir / 'rosters'

    if hitter_file is None:
        hitter_file = proj_dir / 'sample_hitters.csv'
    if pitcher_file is None:
        pitcher_file = proj_dir / 'sample_pitchers.csv'
    if roster_file is None:
        roster_file = roster_dir / 'sample_my_team.csv'

    # Check if files exist
    for filepath in [hitter_file, pitcher_file, roster_file]:
        if not Path(filepath).exists():
            print(f"\nError: File not found: {filepath}")
            print("\nRun 'python analyze_keepers.py --setup' to create sample data.")
            return

    print("\n" + "=" * 60)
    print("  FANTASY BASEBALL KEEPER ANALYSIS")
    print("=" * 60)
    print(f"\nLoading data...")
    print(f"  Hitters:  {hitter_file}")
    print(f"  Pitchers: {pitcher_file}")
    print(f"  Roster:   {roster_file}")

    # Step 1: Load projections
    hitters = load_hitter_projections(hitter_file)
    pitchers = load_pitcher_projections(pitcher_file)
    print(f"\nLoaded {len(hitters)} hitters and {len(pitchers)} pitchers")

    # Step 2: Calculate player values
    print("\nCalculating player values (z-scores)...")
    hitters_valued = calculate_hitter_zscores(hitters)
    pitchers_valued = calculate_pitcher_zscores(pitchers)
    all_players = combine_player_values(hitters_valued, pitchers_valued)

    # Step 3: Show top players overall (for context)
    display_top_players(all_players, n=20)

    # Step 4: Load your roster
    print("\nAnalyzing your roster...")
    my_roster = load_roster(roster_file)
    print(f"Found {len(my_roster)} players on your roster")

    # Step 5: Calculate keeper values
    keeper_analysis = calculate_keeper_values(my_roster, all_players)

    # Step 6: Display recommendations
    display_keeper_recommendations(keeper_analysis, num_keepers=num_keepers)

    print("\n" + "=" * 60)
    print("  ANALYSIS COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Review the keeper recommendations above")
    print("  2. Compare bubble players if decisions are close")
    print("  3. Consider keeper years remaining for long-term value")
    print("  4. Run with --league to see predicted available players")
    print()


def run_league_analysis(hitter_file: str = None,
                        pitcher_file: str = None,
                        league_file: str = None,
                        your_team_name: str = 'Your Team'):
    """
    Run league-wide keeper prediction analysis.

    Predicts which players each team will keep, then shows you:
    1. Your recommended keepers
    2. Predicted keepers for all other teams
    3. Best available players (predicted to NOT be kept)
    """
    from src.data_loader import (load_hitter_projections, load_pitcher_projections,
                                  load_league_rosters, STANDINGS_KEEPER_SLOTS)
    from src.valuation import (calculate_hitter_zscores, calculate_pitcher_zscores,
                               combine_player_values)
    from src.keepers import (calculate_keeper_values, display_keeper_recommendations,
                             calculate_all_team_keepers, get_available_players,
                             display_available_players)

    # Default to sample data
    data_dir = Path(__file__).parent / 'data'
    proj_dir = data_dir / 'projections'
    roster_dir = data_dir / 'rosters'

    if hitter_file is None:
        hitter_file = proj_dir / 'sample_hitters.csv'
    if pitcher_file is None:
        pitcher_file = proj_dir / 'sample_pitchers.csv'
    if league_file is None:
        league_file = roster_dir / 'sample_league.csv'

    # Check files exist
    for filepath in [hitter_file, pitcher_file, league_file]:
        if not Path(filepath).exists():
            print(f"\nError: File not found: {filepath}")
            print("\nRun 'python analyze_keepers.py --setup' to create sample data.")
            return

    print("\n" + "=" * 70)
    print("  LEAGUE-WIDE KEEPER PREDICTION")
    print("=" * 70)
    print(f"\nLoading data...")
    print(f"  Projections: {hitter_file}, {pitcher_file}")
    print(f"  League:      {league_file}")

    # Load and calculate player values
    hitters = load_hitter_projections(hitter_file)
    pitchers = load_pitcher_projections(pitcher_file)
    hitters_valued = calculate_hitter_zscores(hitters)
    pitchers_valued = calculate_pitcher_zscores(pitchers)
    all_players = combine_player_values(hitters_valued, pitchers_valued)

    print(f"\nLoaded {len(hitters)} hitters and {len(pitchers)} pitchers")

    # Load league rosters
    league_rosters = load_league_rosters(league_file)
    print(f"Loaded {len(league_rosters)} teams")

    # Calculate keepers for all teams
    print("\nPredicting keepers for each team...")
    all_keepers = calculate_all_team_keepers(league_rosters, all_players, STANDINGS_KEEPER_SLOTS)

    # Display your team's recommendations first
    if your_team_name in league_rosters:
        print(f"\n{'═'*70}")
        print(f"  YOUR TEAM: {your_team_name}")
        print(f"{'═'*70}")
        your_keeper_slots = STANDINGS_KEEPER_SLOTS.get(your_team_name, 8)
        your_analysis = calculate_keeper_values(league_rosters[your_team_name], all_players)
        display_keeper_recommendations(your_analysis, num_keepers=your_keeper_slots)

    # Show other teams' predicted keepers
    print(f"\n{'═'*70}")
    print(f"  PREDICTED KEEPERS FOR OTHER TEAMS")
    print(f"{'═'*70}")

    for team_name, keepers_df in all_keepers.items():
        if team_name == your_team_name:
            continue

        slots = STANDINGS_KEEPER_SLOTS.get(team_name, 6)
        print(f"\n{team_name} ({slots} keepers):")

        for _, row in keepers_df.iterrows():
            surplus = row['keeper_value']
            sign = '+' if surplus >= 0 else ''
            print(f"  • {row['Player']:<22} (${row['dollar_value']:>5.1f} value, {sign}${surplus:.1f} surplus)")

    # Show available players
    available = get_available_players(all_keepers, all_players)
    display_available_players(available, n=25)

    print("\n" + "=" * 70)
    print("  LEAGUE ANALYSIS COMPLETE")
    print("=" * 70)
    print("\nThese are players projected to be available in the draft.")
    print("Target high-value players that other teams aren't keeping!")
    print()


def main():
    """Main entry point with command line argument handling."""
    parser = argparse.ArgumentParser(
        description='Fantasy Baseball Keeper Analysis Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze_keepers.py                    # Analyze your team only
  python analyze_keepers.py --league           # Predict all teams' keepers
  python analyze_keepers.py --setup            # Create sample data files
  python analyze_keepers.py --keepers 6        # Analyze for 6 keeper slots

  # Using your own data:
  python analyze_keepers.py \\
      --hitters data/projections/fangraphs_hitters.csv \\
      --pitchers data/projections/fangraphs_pitchers.csv \\
      --roster data/rosters/my_team.csv \\
      --keepers 8

  # League-wide with your own data:
  python analyze_keepers.py --league \\
      --hitters data/projections/fangraphs_hitters.csv \\
      --pitchers data/projections/fangraphs_pitchers.csv \\
      --league-file data/rosters/all_teams.csv
        """
    )

    parser.add_argument('--setup', action='store_true',
                       help='Create sample data files for testing')

    parser.add_argument('--league', action='store_true',
                       help='Run league-wide analysis (predict all keepers)')

    parser.add_argument('--hitters', type=str, default=None,
                       help='Path to hitter projections CSV')

    parser.add_argument('--pitchers', type=str, default=None,
                       help='Path to pitcher projections CSV')

    parser.add_argument('--roster', type=str, default=None,
                       help='Path to your team roster CSV (for single-team mode)')

    parser.add_argument('--league-file', type=str, default=None,
                       help='Path to league rosters CSV (for --league mode)')

    parser.add_argument('--keepers', type=int, default=8,
                       help='Number of keeper slots (default: 8)')

    parser.add_argument('--team-name', type=str, default='Your Team',
                       help='Your team name in the league file (default: "Your Team")')

    args = parser.parse_args()

    if args.setup:
        setup_sample_data()
    elif args.league:
        run_league_analysis(
            hitter_file=args.hitters,
            pitcher_file=args.pitchers,
            league_file=args.league_file,
            your_team_name=args.team_name
        )
    else:
        run_analysis(
            hitter_file=args.hitters,
            pitcher_file=args.pitchers,
            roster_file=args.roster,
            num_keepers=args.keepers
        )


if __name__ == '__main__':
    main()
