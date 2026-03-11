"""
sheets.py - Google Sheets integration for the draft board

Reads the league draft board from Google Sheets to determine:
- Which players have been drafted (and by whom)
- Which players are kept (and at what round)
- Current draft position (round, pick, next Nudes pick)
- Available player pool

DRAFT BOARD FORMAT (grid layout):
- Row 0: Team names as column headers (e.g., "The Nudes", "Acuna Machado")
- Row 1: Owner first names (e.g., "Eli", "Matt") — skipped during parsing
- Rows 2-26: Rounds 1-25, column 0 = round number, columns 1-14 = pick cells
- Each pick cell = "{overall_pick_number} {Player Name}" or just "{number}" if unpicked
- Column 15 may repeat the round number (ignored)
- 14 team columns (1-14)
- Snake draft: odd rounds L→R, even rounds R→L

SPREADSHEET ID: 17AkutPs6lnXAiBk2Jt7LCjGwmckMcRuqdPcubJYrSaA
"""

import re
import unicodedata
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# Draft board Google Sheet (persistent across seasons)
SPREADSHEET_ID = '17AkutPs6lnXAiBk2Jt7LCjGwmckMcRuqdPcubJYrSaA'

# Team name mapping: header text in sheet → canonical team name
# The sheet headers include manager names (e.g., "The Nudes Eli")
# This maps to the canonical names used in yahoo_league.csv
TEAM_NAME_MAP = {
    'giant city': 'Giant City',
    'fire bad': 'Fire Bad',
    'nudes': 'The Nudes',
    'the nudes': 'The Nudes',
    'cybulski': 'Cybulski Tax Service',
    'jeters': 'Jeters Never Win',
    'hebrew': 'Hebrew Nationals',
    'k-nines': 'K-Nines',
    'funeral': 'The Funeral Home',
    'bowls': 'Bowls on Parade',
    'acuna': 'Acuna Machado',
    'topline': 'Topline Jobbers',
    'high falls': 'High Falls Heroes',
    'phenomenal': 'The Phenomenal Smiths',
    'kiki': 'Kiki Kankles',
}


def connect_to_sheets(credentials_path: str = 'google_service_account.json') -> gspread.Client:
    """
    Connect to Google Sheets using a service account.

    Tries Streamlit secrets first (for Cloud deployment), then falls back
    to a local JSON key file.

    Args:
        credentials_path: Path to the Google service account JSON key file

    Returns:
        Authenticated gspread client
    """
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive.readonly',
    ]

    # Try Streamlit secrets first (for Streamlit Cloud deployment)
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=scopes
            )
            return gspread.authorize(creds)
    except Exception:
        pass

    # Fall back to local file
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return gspread.authorize(creds)


def normalize_team_name(header_text: str) -> str:
    """
    Convert a sheet header like "The Nudes Eli" to canonical team name "The Nudes".

    Tries partial matching against TEAM_NAME_MAP keys.
    """
    text_lower = header_text.lower().strip()

    # Try each known team name fragment
    for fragment, canonical in TEAM_NAME_MAP.items():
        if fragment in text_lower:
            return canonical

    # Fallback: return the header text as-is
    return header_text.strip()


def parse_draft_cell(cell_value: str) -> tuple:
    """
    Parse a draft board cell into (pick_number, player_name).

    Cell formats:
    - "10 Ronald Acuña Jr." → (10, "Ronald Acuña Jr.")
    - "10" → (10, None)  # not yet picked
    - "" → (None, None)  # empty cell
    - "K: Ronald Acuña Jr." → (None, "Ronald Acuña Jr.")  # keeper notation

    Returns:
        (pick_number, player_name) — player_name is None if cell is unpicked
    """
    if not cell_value or not cell_value.strip():
        return (None, None)

    text = cell_value.strip()

    # Check for keeper notation (e.g., "K: Player Name" or "K - Player Name")
    keeper_match = re.match(r'^[Kk][:\-\s]+(.+)$', text)
    if keeper_match:
        return (None, keeper_match.group(1).strip())

    # Try to parse "number PlayerName" format
    match = re.match(r'^(\d+)\s+(.+)$', text)
    if match:
        pick_num = int(match.group(1))
        player_name = match.group(2).strip()
        # Clean up common annotations:
        # "(B)" or "(P)" = batter/pitcher tag
        # "(2)" or "(3)" = years kept count
        # "(P) (2)" = pitcher tag + years kept
        player_name = re.sub(r'\s*\([BPbp]\)', '', player_name)
        player_name = re.sub(r'\s*\(\d\)', '', player_name)
        player_name = player_name.strip()
        return (pick_num, player_name)

    # Number only = unpicked slot
    if text.isdigit():
        return (int(text), None)

    # Text only (no number) = possibly a keeper or annotation
    return (None, text if len(text) > 2 else None)


def get_draft_board(client: gspread.Client,
                    tab_name: str = '2026',
                    spreadsheet_id: str = SPREADSHEET_ID) -> pd.DataFrame:
    """
    Read the draft board from Google Sheets into a structured DataFrame.

    Returns DataFrame with columns:
        Round, Pick, OverallPick, Team, Player, IsPicked

    Args:
        client: Authenticated gspread client
        tab_name: Sheet tab name (e.g., '2026', '2025')
        spreadsheet_id: Google Sheets document ID
    """
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(tab_name)

    # Get all values as a 2D list
    all_values = worksheet.get_all_values()

    if len(all_values) < 2:
        raise ValueError(f"Sheet '{tab_name}' has too few rows")

    # Row 0 = headers (team names), but first/last columns may be round numbers or labels
    header_row = all_values[0]

    # Find the team columns (skip first column if it's a round number/label)
    # The team columns have text that matches known team names
    team_columns = {}  # col_index → team_name
    for col_idx, header in enumerate(header_row):
        if not header.strip():
            continue
        normalized = normalize_team_name(header)
        # Skip if it looks like a year or round number
        if header.strip().isdigit():
            continue
        if normalized != header.strip() or any(frag in header.lower() for frag in TEAM_NAME_MAP.keys()):
            team_columns[col_idx] = normalized

    if not team_columns:
        # Fallback: assume columns 1-14 are teams (column 0 and 15 are round numbers)
        for col_idx in range(1, min(15, len(header_row))):
            header = header_row[col_idx].strip()
            if header and not header.isdigit():
                team_columns[col_idx] = normalize_team_name(header)

    if not team_columns:
        raise ValueError("Could not identify team columns in sheet header row")

    # Find the first row that starts with a round number (1)
    # This skips any extra header rows (e.g., owner names row in 2026 tab)
    data_start = 1  # default: rows start right after header
    for row_idx in range(1, min(5, len(all_values))):
        first_cell = all_values[row_idx][0].strip() if all_values[row_idx] else ''
        if first_cell == '1':
            data_start = row_idx
            break

    # Parse each round row
    picks = []
    for row_idx in range(data_start, len(all_values)):
        row = all_values[row_idx]
        if not row or not any(cell.strip() for cell in row):
            continue

        # Determine round number from first column (round label)
        first_cell = row[0].strip() if row else ''
        if first_cell.isdigit():
            draft_round = int(first_cell)
        else:
            continue  # Skip non-round rows
        if draft_round > 25:
            break  # Only 25 rounds

        for col_idx, team_name in team_columns.items():
            if col_idx >= len(row):
                continue

            cell_value = row[col_idx]
            pick_num, player_name = parse_draft_cell(cell_value)

            picks.append({
                'Round': draft_round,
                'OverallPick': pick_num,
                'Team': team_name,
                'Player': player_name,
                'IsPicked': player_name is not None,
                'RawCell': cell_value,
            })

    df = pd.DataFrame(picks)

    # Add pick-within-round numbering
    if not df.empty:
        df['Pick'] = df.groupby('Round').cumcount() + 1

    return df


def get_draft_state(draft_board: pd.DataFrame, my_team: str = 'The Nudes') -> dict:
    """
    Determine the current draft state from the draft board.

    Returns dict with:
        current_round: int - current round being drafted
        current_pick: int - pick number within the round
        total_picks_made: int - how many picks have been made
        total_picks: int - total picks in the draft (25 × 14 = 350)
        next_nudes_round: int - next round The Nudes picks
        next_nudes_pick: int - pick within that round
        picks_until_nudes: int - how many picks until The Nudes' next pick
        is_nudes_turn: bool - whether it's currently The Nudes' turn
        draft_complete: bool - whether the draft is finished
    """
    total_picks = len(draft_board)
    picked = draft_board[draft_board['IsPicked']]

    # Sort unpicked by OverallPick to get correct snake-draft order
    # (column order is always L→R, but even rounds draft R→L)
    unpicked = draft_board[~draft_board['IsPicked']].copy()
    unpicked = unpicked.dropna(subset=['OverallPick']).sort_values('OverallPick')

    if unpicked.empty:
        return {
            'current_round': 25,
            'current_pick': 14,
            'total_picks_made': total_picks,
            'total_picks': total_picks,
            'next_nudes_round': None,
            'next_nudes_pick': None,
            'picks_until_nudes': 0,
            'is_nudes_turn': False,
            'draft_complete': True,
        }

    # Current position = first unpicked slot in draft order
    next_pick = unpicked.iloc[0]
    current_round = next_pick['Round']
    current_pick = next_pick['OverallPick']

    # Find next Nudes pick (in draft order)
    nudes_unpicked = unpicked[unpicked['Team'] == my_team]
    if nudes_unpicked.empty:
        next_nudes_round = None
        next_nudes_pick = None
        picks_until_nudes = 0
        is_nudes_turn = False
    else:
        next_nudes = nudes_unpicked.iloc[0]
        next_nudes_round = next_nudes['Round']
        next_nudes_pick = next_nudes['OverallPick']
        # Count picks before the first Nudes pick in draft order
        picks_until_nudes = len(unpicked[
            unpicked['OverallPick'] < next_nudes_pick
        ])
        is_nudes_turn = picks_until_nudes == 0

    return {
        'current_round': current_round,
        'current_pick': current_pick,
        'total_picks_made': len(picked),
        'total_picks': total_picks,
        'next_nudes_round': next_nudes_round,
        'next_nudes_pick': next_nudes_pick,
        'picks_until_nudes': picks_until_nudes,
        'is_nudes_turn': is_nudes_turn,
        'draft_complete': False,
    }


def get_my_roster(draft_board: pd.DataFrame, my_team: str = 'The Nudes') -> pd.DataFrame:
    """
    Get the current roster for a team (keepers + drafted players so far).

    Returns DataFrame with columns: Player, Round, OverallPick
    """
    team_picks = draft_board[
        (draft_board['Team'] == my_team) & (draft_board['IsPicked'])
    ].copy()

    return team_picks[['Player', 'Round', 'OverallPick']].reset_index(drop=True)


def _normalize_name(name: str) -> str:
    """Normalize a player name for matching (strip accents, suffixes, lowercase)."""
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = ''.join(c for c in nfkd if not unicodedata.combining(c))
    name = ascii_name.lower().strip()
    # Strip common suffixes: Jr., Jr, Sr., Sr, II, III, IV
    name = re.sub(r'\b(jr\.?|sr\.?|ii|iii|iv)\s*$', '', name).strip()
    name = re.sub(r'\s+', ' ', name)
    return name


def get_drafted_players(draft_board: pd.DataFrame) -> set:
    """Get set of all player names that have been drafted or kept."""
    picked = draft_board[draft_board['IsPicked']]
    return set(picked['Player'].dropna().apply(_normalize_name))


def get_available_players(draft_board: pd.DataFrame,
                          sgp_values: pd.DataFrame) -> pd.DataFrame:
    """
    Get SGP-valued players that haven't been drafted yet.

    Cross-references the draft board with SGP valuations to return
    only players still available, with their projected values.
    """
    drafted = get_drafted_players(draft_board)

    # Filter SGP values to undrafted players
    available = sgp_values[
        ~sgp_values['Name'].apply(_normalize_name).isin(drafted)
    ].copy()

    return available.sort_values('dollar_value', ascending=False)


def push_recommendations_to_sheet(client: gspread.Client,
                                  recommendations: pd.DataFrame,
                                  tab_name: str = 'Recommendations',
                                  spreadsheet_id: str = SPREADSHEET_ID):
    """
    Push draft recommendations to a tab in the draft Google Sheet.

    Creates or updates a "Recommendations" tab with the current top picks.
    This serves as a mobile-friendly fallback (view via Google Sheets app).
    """
    spreadsheet = client.open_by_key(spreadsheet_id)

    # Create or get the recommendations tab
    try:
        worksheet = spreadsheet.worksheet(tab_name)
        worksheet.clear()
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=50, cols=15)

    # Format recommendations for the sheet
    headers = ['Rank', 'Player', 'Position', 'Value', 'Surplus', 'Category Fit',
               'Position Fit', 'Total Score', 'Notes']

    rows = [headers]
    for idx, row in recommendations.head(15).iterrows():
        rows.append([
            idx + 1,
            row.get('Name', ''),
            row.get('primary_position', ''),
            f"${row.get('dollar_value', 0):.1f}",
            f"${row.get('surplus', 0):.1f}",
            f"{row.get('category_score', 0):.2f}",
            f"{row.get('position_score', 0):.2f}",
            f"{row.get('total_score', 0):.2f}",
            row.get('notes', ''),
        ])

    worksheet.update(range_name='A1', values=rows)


# For testing without Google credentials
def load_draft_board_from_csv(csv_path: str, team_name: str = None) -> pd.DataFrame:
    """
    Load a draft board from a CSV file (for testing or offline use).

    Uses the existing draft_2025_parsed.csv format:
    Team, Player, DraftRound, YearsKept, OverallPick
    """
    df = pd.read_csv(csv_path)

    # Convert to draft board format
    board = df.rename(columns={'DraftRound': 'Round'})
    board['IsPicked'] = board['Player'].notna()
    board['Pick'] = board.groupby('Round').cumcount() + 1

    if team_name:
        board = board[board['Team'] == team_name]

    return board
