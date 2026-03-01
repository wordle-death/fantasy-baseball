"""
data_loader.py - Load player projections from CSV files

This module handles reading Fangraphs projection exports and converting
them into a format our valuation engine can use.
"""

import pandas as pd
from pathlib import Path


def load_hitter_projections(filepath: str) -> pd.DataFrame:
    """
    Load hitter projections from a Fangraphs CSV export.

    Args:
        filepath: Path to the CSV file

    Returns:
        DataFrame with columns: Name, Team, PA, R, HR, RBI, SB, OBP

    What this does:
        1. Reads the CSV file into a pandas DataFrame (like a spreadsheet in Python)
        2. Keeps only the columns we need for our 5x5 categories
        3. Filters out players with very few projected plate appearances
    """
    # Read the CSV file
    df = pd.read_csv(filepath)

    # Fangraphs column names (may need adjustment based on actual export format)
    # Common column names: Name, Team, PA, R, HR, RBI, SB, OBP
    required_columns = ['Name', 'Team', 'PA', 'R', 'HR', 'RBI', 'SB', 'OBP']

    # Check which columns exist (Fangraphs exports can vary)
    available_columns = [col for col in required_columns if col in df.columns]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        print(f"Warning: Missing columns in hitter file: {missing_columns}")
        print(f"Available columns: {list(df.columns)}")

    # Keep only the columns we need
    df = df[available_columns].copy()

    # Filter to players with meaningful playing time (at least 200 PA projected)
    if 'PA' in df.columns:
        df = df[df['PA'] >= 200]

    return df


def load_pitcher_projections(filepath: str) -> pd.DataFrame:
    """
    Load pitcher projections from a Fangraphs CSV export.

    Args:
        filepath: Path to the CSV file

    Returns:
        DataFrame with columns: Name, Team, IP, W, SV, K (or SO), ERA, WHIP
    """
    df = pd.read_csv(filepath)

    # Fangraphs uses 'SO' for strikeouts, but we'll accept 'K' too
    required_columns = ['Name', 'Team', 'IP', 'W', 'SV', 'ERA', 'WHIP']

    # Handle strikeout column naming (Fangraphs uses 'SO')
    if 'SO' in df.columns:
        df = df.rename(columns={'SO': 'K'})
    required_columns.append('K')

    available_columns = [col for col in required_columns if col in df.columns]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        print(f"Warning: Missing columns in pitcher file: {missing_columns}")
        print(f"Available columns: {list(df.columns)}")

    df = df[available_columns].copy()

    # Filter to pitchers with meaningful innings (at least 30 IP)
    if 'IP' in df.columns:
        df = df[df['IP'] >= 30]

    return df


def load_roster(filepath: str) -> pd.DataFrame:
    """
    Load a team's roster with keeper information.

    Expected columns:
        - Player: Player name (must match Fangraphs spelling)
        - Position: Player's position (C, 1B, OF, SP, RP, etc.)
        - DraftRound: Round player was drafted last year (1-25, or 0 if undrafted/waiver)
        - YearsKept: How many years this player has been kept (0, 1, or 2)

    Returns:
        DataFrame with roster information
    """
    df = pd.read_csv(filepath)

    required_columns = ['Player', 'Position', 'DraftRound', 'YearsKept']
    available_columns = [col for col in required_columns if col in df.columns]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        print(f"Warning: Missing columns in roster file: {missing_columns}")
        print(f"Available columns: {list(df.columns)}")

    df = df[available_columns].copy()

    # Handle undrafted players - they get Round 18 value
    # DraftRound of 0 means undrafted (picked up off waivers, etc.)
    if 'DraftRound' in df.columns:
        df.loc[df['DraftRound'] == 0, 'DraftRound'] = 18

    return df


def create_sample_projections():
    """
    Create sample projection files for testing.

    This lets us test the system before getting real Fangraphs data.
    These are approximate 2025 projections for well-known players.
    """
    data_dir = Path(__file__).parent.parent / 'data' / 'projections'
    data_dir.mkdir(parents=True, exist_ok=True)

    # Sample hitter projections (top players + some mid-tier)
    hitters = pd.DataFrame({
        'Name': [
            'Ronald Acuna Jr.', 'Mookie Betts', 'Shohei Ohtani', 'Corey Seager',
            'Julio Rodriguez', 'Gunnar Henderson', 'Bobby Witt Jr.', 'Trea Turner',
            'Juan Soto', 'Freddie Freeman', 'Yordan Alvarez', 'Aaron Judge',
            'Corbin Carroll', 'Marcus Semien', 'Rafael Devers', 'Matt Olson',
            'Elly De La Cruz', 'Francisco Lindor', 'Jose Ramirez', 'Kyle Tucker',
            # Mid-tier players
            'Ozzie Albies', 'Bo Bichette', 'Adley Rutschman', 'Will Smith',
            'Pete Alonso', 'Vladimir Guerrero Jr.', 'Bryce Harper', 'Mike Trout',
            'Luis Robert Jr.', 'Fernando Tatis Jr.', 'Manny Machado', 'Austin Riley'
        ],
        'Team': [
            'ATL', 'LAD', 'LAD', 'TEX', 'SEA', 'BAL', 'KC', 'PHI',
            'NYY', 'LAD', 'HOU', 'NYY', 'ARI', 'TEX', 'BOS', 'ATL',
            'CIN', 'NYM', 'CLE', 'HOU',
            'ATL', 'TOR', 'BAL', 'LAD', 'NYM', 'TOR', 'PHI', 'LAA',
            'CHW', 'SD', 'SD', 'ATL'
        ],
        'PA': [
            650, 650, 600, 620, 650, 650, 680, 600,
            650, 620, 580, 550, 620, 650, 620, 600,
            600, 640, 620, 580,
            550, 600, 580, 520, 600, 620, 550, 450,
            500, 500, 600, 600
        ],
        'R': [
            120, 110, 95, 100, 105, 110, 115, 95,
            110, 100, 90, 95, 100, 100, 95, 95,
            105, 100, 100, 95,
            85, 90, 80, 70, 85, 90, 85, 75,
            80, 85, 85, 90
        ],
        'HR': [
            35, 30, 40, 32, 28, 35, 28, 22,
            38, 25, 35, 45, 22, 25, 32, 35,
            20, 28, 30, 28,
            22, 22, 22, 25, 38, 32, 28, 30,
            25, 28, 28, 32
        ],
        'RBI': [
            100, 95, 105, 100, 95, 100, 105, 80,
            115, 95, 105, 110, 75, 85, 100, 105,
            75, 95, 105, 95,
            80, 85, 85, 80, 100, 100, 90, 75,
            80, 85, 90, 100
        ],
        'SB': [
            55, 15, 15, 5, 30, 15, 35, 25,
            10, 8, 5, 5, 45, 20, 3, 2,
            60, 25, 18, 25,
            15, 18, 3, 2, 2, 5, 10, 10,
            25, 25, 8, 5
        ],
        'OBP': [
            .395, .380, .365, .365, .350, .365, .355, .350,
            .410, .375, .380, .385, .365, .345, .365, .360,
            .330, .360, .370, .375,
            .335, .340, .365, .365, .350, .360, .380, .390,
            .335, .355, .350, .355
        ]
    })

    hitters.to_csv(data_dir / 'sample_hitters.csv', index=False)

    # Sample pitcher projections
    pitchers = pd.DataFrame({
        'Name': [
            'Spencer Strider', 'Zack Wheeler', 'Gerrit Cole', 'Corbin Burnes',
            'Tyler Glasnow', 'Logan Webb', 'Tarik Skubal', 'Zac Gallen',
            'Dylan Cease', 'Kevin Gausman', 'Pablo Lopez', 'Sonny Gray',
            # Relievers (saves)
            'Josh Hader', 'Emmanuel Clase', 'Felix Bautista', 'Ryan Helsley',
            'Devin Williams', 'Alexis Diaz', 'Andres Munoz', 'Pete Fairbanks',
            # More starters
            'Framber Valdez', 'Luis Castillo', 'Blake Snell', 'Max Fried',
            'Yoshinobu Yamamoto', 'Chris Sale', 'Shota Imanaga', 'Hunter Brown'
        ],
        'Team': [
            'ATL', 'PHI', 'NYY', 'BAL', 'LAD', 'SF', 'DET', 'ARI',
            'SD', 'TOR', 'MIN', 'STL',
            'HOU', 'CLE', 'BAL', 'STL', 'MIL', 'CIN', 'SEA', 'TB',
            'HOU', 'SEA', 'SF', 'ATL', 'LAD', 'ATL', 'CHC', 'HOU'
        ],
        'IP': [
            180, 200, 190, 195, 175, 195, 190, 180,
            190, 185, 180, 175,
            65, 70, 60, 65, 60, 65, 70, 60,
            190, 185, 160, 185, 170, 175, 165, 175
        ],
        'W': [
            15, 14, 13, 14, 12, 13, 14, 12,
            12, 12, 11, 11,
            3, 4, 3, 3, 3, 3, 4, 3,
            13, 12, 10, 13, 12, 12, 10, 11
        ],
        'SV': [
            0, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0,
            35, 40, 32, 35, 30, 32, 28, 28,
            0, 0, 0, 0, 0, 0, 0, 0
        ],
        'K': [
            250, 220, 210, 200, 210, 180, 220, 190,
            220, 190, 175, 170,
            85, 75, 80, 85, 90, 80, 85, 75,
            180, 195, 185, 175, 180, 190, 165, 180
        ],
        'ERA': [
            2.80, 3.10, 3.20, 2.90, 3.00, 3.25, 2.85, 3.30,
            3.40, 3.50, 3.60, 3.50,
            2.50, 1.80, 2.40, 2.30, 2.20, 3.00, 2.60, 3.00,
            3.20, 3.40, 3.30, 3.10, 3.00, 3.20, 3.40, 3.50
        ],
        'WHIP': [
            0.95, 1.05, 1.10, 1.00, 1.05, 1.10, 0.98, 1.12,
            1.15, 1.12, 1.18, 1.15,
            0.90, 0.85, 0.95, 0.92, 0.88, 1.05, 1.00, 1.05,
            1.10, 1.12, 1.15, 1.08, 1.05, 1.10, 1.12, 1.15
        ]
    })

    pitchers.to_csv(data_dir / 'sample_pitchers.csv', index=False)

    print(f"Created sample projections in {data_dir}")
    print(f"  - sample_hitters.csv ({len(hitters)} players)")
    print(f"  - sample_pitchers.csv ({len(pitchers)} players)")

    return data_dir


def create_sample_roster():
    """
    Create a sample roster file for testing.

    This represents YOUR team's roster with keeper information.
    """
    data_dir = Path(__file__).parent.parent / 'data' / 'rosters'
    data_dir.mkdir(parents=True, exist_ok=True)

    # Sample roster - mix of keeper-worthy and not
    roster = pd.DataFrame({
        'Player': [
            'Julio Rodriguez', 'Gunnar Henderson', 'Corbin Carroll',
            'Pete Alonso', 'Bo Bichette', 'Adley Rutschman',
            'Tarik Skubal', 'Logan Webb', 'Emmanuel Clase',
            'Ozzie Albies', 'Luis Robert Jr.', 'Hunter Brown',
            'Devin Williams', 'Pablo Lopez', 'Austin Riley'
        ],
        'Position': [
            'OF', 'SS', 'OF', '1B', 'SS', 'C',
            'SP', 'SP', 'RP', 'SS', 'OF', 'SP',
            'RP', 'SP', '3B'
        ],
        'DraftRound': [
            15, 18, 12, 3, 4, 8,
            10, 7, 9, 11, 6, 0,
            14, 9, 5
        ],
        'YearsKept': [
            1, 0, 1, 0, 2, 0,
            1, 0, 1, 0, 0, 0,
            0, 0, 1
        ]
    })

    roster.to_csv(data_dir / 'sample_my_team.csv', index=False)

    print(f"Created sample roster in {data_dir}")
    print(f"  - sample_my_team.csv ({len(roster)} players)")

    return data_dir


def load_league_rosters(filepath: str) -> dict:
    """
    Load all teams' rosters from a single CSV file.

    Expected columns:
        - Team: Team name (e.g., "Team Alpha", "The Bombers")
        - Player: Player name
        - Position: Player position
        - DraftRound: Round drafted last year (0 = undrafted)
        - YearsKept: Years already kept (0, 1, or 2)

    Returns:
        Dict of {team_name: roster_dataframe}
    """
    df = pd.read_csv(filepath)

    # Handle undrafted players
    if 'DraftRound' in df.columns:
        df.loc[df['DraftRound'] == 0, 'DraftRound'] = 18

    # Group by team
    teams = {}
    for team_name in df['Team'].unique():
        team_roster = df[df['Team'] == team_name].copy()
        # Drop the Team column since it's redundant now
        team_roster = team_roster.drop(columns=['Team'])
        teams[team_name] = team_roster

    return teams


def create_sample_league():
    """
    Create a sample league file with multiple teams for testing league-wide predictions.

    This creates 5 sample teams (not all 15) to keep it manageable for testing.
    """
    data_dir = Path(__file__).parent.parent / 'data' / 'rosters'
    data_dir.mkdir(parents=True, exist_ok=True)

    # Define keeper slots based on standings (your league rules)
    # Top 4: 6 keepers, 5-8: 8 keepers, 9-11: 7 keepers, 12-15: 6 keepers
    teams_data = []

    # Team 1: "Your Team" (5th-8th place, 8 keepers) - same as sample_my_team
    your_team = [
        ('Your Team', 'Julio Rodriguez', 'OF', 15, 1),
        ('Your Team', 'Gunnar Henderson', 'SS', 18, 0),
        ('Your Team', 'Corbin Carroll', 'OF', 12, 1),
        ('Your Team', 'Pete Alonso', '1B', 3, 0),
        ('Your Team', 'Bo Bichette', 'SS', 4, 2),
        ('Your Team', 'Adley Rutschman', 'C', 8, 0),
        ('Your Team', 'Tarik Skubal', 'SP', 10, 1),
        ('Your Team', 'Logan Webb', 'SP', 7, 0),
        ('Your Team', 'Emmanuel Clase', 'RP', 9, 1),
        ('Your Team', 'Ozzie Albies', '2B', 11, 0),
        ('Your Team', 'Luis Robert Jr.', 'OF', 6, 0),
        ('Your Team', 'Hunter Brown', 'SP', 0, 0),
        ('Your Team', 'Devin Williams', 'RP', 14, 0),
        ('Your Team', 'Pablo Lopez', 'SP', 9, 0),
        ('Your Team', 'Austin Riley', '3B', 5, 1),
    ]
    teams_data.extend(your_team)

    # Team 2: "Dynasty Kings" (1st place, 6 keepers)
    dynasty = [
        ('Dynasty Kings', 'Ronald Acuna Jr.', 'OF', 1, 2),
        ('Dynasty Kings', 'Juan Soto', 'OF', 2, 1),
        ('Dynasty Kings', 'Aaron Judge', 'OF', 3, 0),
        ('Dynasty Kings', 'Spencer Strider', 'SP', 8, 1),
        ('Dynasty Kings', 'Bobby Witt Jr.', 'SS', 5, 1),
        ('Dynasty Kings', 'Corbin Burnes', 'SP', 4, 0),
        ('Dynasty Kings', 'Marcus Semien', '2B', 10, 0),
        ('Dynasty Kings', 'Dylan Cease', 'SP', 12, 0),
        ('Dynasty Kings', 'Will Smith', 'C', 9, 0),
        ('Dynasty Kings', 'Sonny Gray', 'SP', 15, 0),
    ]
    teams_data.extend(dynasty)

    # Team 3: "The Underdogs" (12th place, 6 keepers)
    underdogs = [
        ('The Underdogs', 'Elly De La Cruz', 'SS', 0, 0),  # Undrafted breakout
        ('The Underdogs', 'Shohei Ohtani', 'OF', 1, 2),
        ('The Underdogs', 'Mookie Betts', 'OF', 2, 2),
        ('The Underdogs', 'Framber Valdez', 'SP', 11, 0),
        ('The Underdogs', 'Josh Hader', 'RP', 7, 1),
        ('The Underdogs', 'Kevin Gausman', 'SP', 8, 0),
        ('The Underdogs', 'Vladimir Guerrero Jr.', '1B', 4, 2),
        ('The Underdogs', 'Bryce Harper', '1B', 3, 2),
        ('The Underdogs', 'Luis Castillo', 'SP', 10, 0),
        ('The Underdogs', 'Alexis Diaz', 'RP', 18, 0),
    ]
    teams_data.extend(underdogs)

    # Team 4: "Moneyball" (9th place, 7 keepers)
    moneyball = [
        ('Moneyball', 'Jose Ramirez', '3B', 3, 1),
        ('Moneyball', 'Kyle Tucker', 'OF', 6, 0),
        ('Moneyball', 'Trea Turner', 'SS', 2, 1),
        ('Moneyball', 'Tyler Glasnow', 'SP', 9, 0),
        ('Moneyball', 'Ryan Helsley', 'RP', 15, 0),
        ('Moneyball', 'Zac Gallen', 'SP', 10, 0),
        ('Moneyball', 'Fernando Tatis Jr.', 'SS', 4, 2),
        ('Moneyball', 'Mike Trout', 'OF', 1, 2),
        ('Moneyball', 'Max Fried', 'SP', 8, 0),
        ('Moneyball', 'Andres Munoz', 'RP', 16, 0),
        ('Moneyball', 'Pete Fairbanks', 'RP', 17, 0),
    ]
    teams_data.extend(moneyball)

    # Team 5: "Rebuilding" (last place, 6 keepers)
    rebuilding = [
        ('Rebuilding', 'Corey Seager', 'SS', 2, 1),
        ('Rebuilding', 'Matt Olson', '1B', 4, 0),
        ('Rebuilding', 'Freddie Freeman', '1B', 3, 2),
        ('Rebuilding', 'Zack Wheeler', 'SP', 5, 1),
        ('Rebuilding', 'Gerrit Cole', 'SP', 1, 2),
        ('Rebuilding', 'Rafael Devers', '3B', 6, 0),
        ('Rebuilding', 'Francisco Lindor', 'SS', 4, 1),
        ('Rebuilding', 'Felix Bautista', 'RP', 14, 0),
        ('Rebuilding', 'Blake Snell', 'SP', 7, 0),
        ('Rebuilding', 'Manny Machado', '3B', 5, 1),
    ]
    teams_data.extend(rebuilding)

    # Create DataFrame
    league_df = pd.DataFrame(teams_data, columns=['Team', 'Player', 'Position', 'DraftRound', 'YearsKept'])
    league_df.to_csv(data_dir / 'sample_league.csv', index=False)

    print(f"\nCreated sample league in {data_dir}")
    print(f"  - sample_league.csv ({len(league_df)} players across {league_df['Team'].nunique()} teams)")

    return data_dir


# Standings-based keeper slots for your league
STANDINGS_KEEPER_SLOTS = {
    # 1st-4th place: 6 keepers
    'Dynasty Kings': 6,
    # 5th-8th place: 8 keepers
    'Your Team': 8,
    # 9th-11th place: 7 keepers
    'Moneyball': 7,
    # 12th-15th place: 6 keepers
    'The Underdogs': 6,
    'Rebuilding': 6,
}


if __name__ == '__main__':
    # If you run this file directly, it creates sample data
    print("Creating sample data files for testing...")
    create_sample_projections()
    create_sample_roster()
    create_sample_league()
    print("\nSample data created! You can now test the valuation engine.")
