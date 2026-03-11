"""
app.py - Streamlit draft day tool

Run locally:
    streamlit run app.py

Deploy to Streamlit Cloud:
    1. Push to GitHub
    2. Connect repo at share.streamlit.io
    3. Store Google credentials in Streamlit Secrets
"""

import re
import streamlit as st
import pandas as pd
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus


def normalize_name(name: str) -> str:
    """Normalize a player name for matching (strip accents, suffixes, lowercase)."""
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = ''.join(c for c in nfkd if not unicodedata.combining(c))
    name = ascii_name.lower().strip()
    # Strip common suffixes: Jr., Jr, Sr., Sr, II, III, IV
    name = re.sub(r'\b(jr\.?|sr\.?|ii|iii|iv)\s*$', '', name).strip()
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)
    return name

from src.draft import (
    get_recommendations, project_team_totals, calculate_league_targets,
    calculate_category_needs, calculate_position_needs,
    load_prospect_watchlist, merge_watchlist,
    DRAFT_ROUND_VALUES, HITTING_CATS, PITCHING_CATS, ROSTER_SLOTS,
    get_phase_weights,
)

# Statcast alerts (optional)
try:
    from src.statcast_news import analyze_keeper_list, summarize_alerts, get_news_search_query
    STATCAST_AVAILABLE = True
except ImportError:
    STATCAST_AVAILABLE = False

# --- Page Config ---
st.set_page_config(
    page_title="Fantasy Baseball Draft Tool",
    page_icon="⚾",
    layout="wide",
)

# --- Data Loading ---

@st.cache_data
def load_sgp_values():
    """Load SGP player valuations (cached)."""
    path = Path('data/projections/sgp_player_values_v3.csv')
    if not path.exists():
        st.error(f"SGP values not found at {path}. Run `python src/sgp_valuation.py` first.")
        st.stop()
    return pd.read_csv(path)


@st.cache_data
def load_draft_csv():
    """Load draft history CSV (for offline mode)."""
    path = Path('data/rosters/draft_2025_parsed.csv')
    if path.exists():
        return pd.read_csv(path)
    return None


def get_available_offline(sgp_values, draft_csv, team, max_round):
    """Get available players using CSV data (offline mode)."""
    if draft_csv is None:
        return sgp_values.copy(), pd.DataFrame()

    # Players drafted through the previous round
    drafted_through = draft_csv[draft_csv['DraftRound'] < max_round]
    drafted_names = set(drafted_through['Player'].dropna().apply(normalize_name))

    # My roster so far
    my_picks = drafted_through[drafted_through['Team'] == team].copy()
    my_picks = my_picks.rename(columns={'DraftRound': 'Round'})

    # Available = not yet drafted
    available = sgp_values[
        ~sgp_values['Name'].apply(normalize_name).isin(drafted_names)
    ].copy()

    return available, my_picks


def try_sheets_connection():
    """Try to connect to Google Sheets. Returns client or None."""
    try:
        from src.sheets import connect_to_sheets
        client = connect_to_sheets()
        return client
    except Exception:
        return None


# --- Sidebar ---

st.sidebar.title("Draft Settings")

# Mode selection
mode = st.sidebar.radio("Data Source", ["Google Sheets", "Offline (CSV)"], index=0)

# Round selection
current_round = st.sidebar.slider("Current Round", 1, 25, 7)

# Number of recommendations
num_recs = st.sidebar.slider("Recommendations", 3, 15, 8)

# Team
team_name = st.sidebar.text_input("Team Name", "The Nudes")

# Weight adjustment
st.sidebar.markdown("---")
st.sidebar.subheader("Scoring Weights")

phase_weights = get_phase_weights(current_round)
w_surplus = st.sidebar.slider("Surplus Value", 0.0, 1.0, phase_weights['surplus'], 0.05)
w_category = st.sidebar.slider("Category Need", 0.0, 1.0, phase_weights['category'], 0.05)
w_position = st.sidebar.slider("Position Need", 0.0, 1.0, phase_weights['position'], 0.05)
w_keeper = st.sidebar.slider("Keeper Upside", 0.0, 1.0, phase_weights['keeper'], 0.05)

# Normalize weights
total_w = w_surplus + w_category + w_position + w_keeper
if total_w > 0:
    weights = {
        'surplus': w_surplus / total_w,
        'category': w_category / total_w,
        'position': w_position / total_w,
        'keeper': w_keeper / total_w,
    }
else:
    weights = phase_weights

# Position filter
st.sidebar.markdown("---")
filter_positions = st.sidebar.multiselect(
    "Filter by Position",
    ['C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP', 'Util'],
    default=[],
)

filter_type = st.sidebar.multiselect(
    "Filter by Type",
    ['Hitter', 'Pitcher'],
    default=[],
)


# --- Main Content ---

st.title("Fantasy Baseball Draft Tool")

# Load data
sgp_values = load_sgp_values()

if mode == "Google Sheets":
    sheets_client = try_sheets_connection()
    if sheets_client is None:
        st.warning("Could not connect to Google Sheets. Falling back to offline mode.")
        st.info("To enable: add `google_service_account.json` to project root, or configure `gcp_service_account` in Streamlit Secrets.")
        mode = "Offline (CSV)"

if mode == "Offline (CSV)":
    draft_csv = load_draft_csv()
    available, my_roster = get_available_offline(sgp_values, draft_csv, team_name, current_round)
else:
    # Google Sheets mode — matches CLI --keepers logic
    from src.sheets import get_draft_board, get_draft_state
    if st.button("Refresh Draft Board"):
        st.cache_data.clear()

    try:
        board = get_draft_board(sheets_client, tab_name='2026')
        all_picked = board[board['IsPicked'] == True].copy()

        # Filter out trade annotations
        all_picked = all_picked[
            ~all_picked['Player'].str.contains('TRADED', case=False, na=False)
        ]

        # All kept/drafted players are unavailable (normalized for accent/typo matching)
        drafted_players = set(
            normalize_name(p) for p in all_picked['Player'].dropna()
        )

        # Build my roster from my picks
        my_picks = all_picked[all_picked['Team'] == team_name]
        my_roster = pd.DataFrame({
            'Player': my_picks['Player'].values,
            'Round': my_picks['Round'].values,
        })

        # Filter to available players
        available = sgp_values[
            ~sgp_values['Name'].apply(normalize_name).isin(drafted_players)
        ].copy()

        # Draft state for status display
        state = get_draft_state(board, team_name)
        current_round = state['current_round']

        # Show draft state
        st.caption(f"Keepers/picks loaded: {len(my_roster)} yours, {len(drafted_players)} total")
        if state['draft_complete']:
            st.success("Draft is complete!")
        elif state['is_nudes_turn']:
            st.error(f"IT'S YOUR PICK! Round {current_round}")
        else:
            st.info(
                f"Round {state['current_round']}, Pick {state['current_pick']} | "
                f"Next {team_name} pick: Round {state['next_nudes_round']} "
                f"({state['picks_until_nudes']} picks away)"
            )
    except Exception as e:
        st.error(f"Error reading draft board: {e}")
        st.stop()

# Merge prospect watchlist
watchlist = load_prospect_watchlist()
if not watchlist.empty:
    available = merge_watchlist(available, watchlist)

# Apply position/type filters (check all eligible positions, not just primary)
if filter_positions:
    def matches_position_filter(row):
        eligible = row.get('eligible_positions', '') or ''
        if not eligible or (isinstance(eligible, float) and pd.isna(eligible)):
            eligible = row.get('primary_position', 'Util') or 'Util'
        positions = [p.strip() for p in str(eligible).split(',')]
        return any(p in filter_positions for p in positions)
    available = available[available.apply(matches_position_filter, axis=1)]
if filter_type:
    available = available[available['player_type'].isin(filter_type)]

# Calculate team state
team_totals = project_team_totals(my_roster, sgp_values)
targets = calculate_league_targets(sgp_values)
category_needs = calculate_category_needs(team_totals, targets)
position_needs = calculate_position_needs(my_roster, sgp_values)

# --- Layout: Two Columns ---
col_team, col_recs = st.columns([1, 1.5])

# --- Left Column: Team State ---
with col_team:
    st.subheader(f"Round {current_round} — {team_name}")

    # My Roster
    if not my_roster.empty:
        st.markdown("**My Roster**")
        roster_display = my_roster[['Player', 'Round']].copy() if 'Round' in my_roster.columns else my_roster
        st.dataframe(roster_display, use_container_width=True, hide_index=True, height=200)
    else:
        st.info("No players on roster yet")

    # Category Projections
    st.markdown("**Category Projections**")
    cat_data = []
    for cat in HITTING_CATS + PITCHING_CATS:
        my_val = team_totals.get(cat, 0)
        target = targets.get(cat, 0)
        need = category_needs.get(cat, 0)

        if cat in ('OBP', 'ERA', 'WHIP'):
            my_str = f"{my_val:.3f}"
            target_str = f"{target:.3f}"
        else:
            my_str = f"{my_val:.0f}"
            target_str = f"{target:.0f}"

        status = "HIGH NEED" if need > 1.0 else "Need" if need > 0 else "OK"
        cat_data.append({
            'Category': cat,
            'My Team': my_str,
            'Target': target_str,
            'Status': status,
        })

    st.dataframe(pd.DataFrame(cat_data), use_container_width=True, hide_index=True)

    # Position Needs
    st.markdown("**Position Needs**")
    pos_data = []
    for pos, need in sorted(position_needs.items(), key=lambda x: -x[1]):
        if need >= 1.5:
            status = "EMPTY"
        elif need >= 1.2:
            status = "Partial"
        else:
            status = "Filled"
        pos_data.append({'Position': pos, 'Status': status})

    st.dataframe(pd.DataFrame(pos_data), use_container_width=True, hide_index=True)

# --- Right Column: Recommendations ---
with col_recs:
    st.subheader("Recommendations")

    recs = get_recommendations(
        available_players=available,
        my_roster=my_roster,
        sgp_values=sgp_values,
        current_round=current_round,
        num_recommendations=num_recs,
        weights=weights,
    )

    if recs.empty:
        st.warning("No recommendations available")
    else:
        # Statcast alert scanning
        alert_results = {}
        if STATCAST_AVAILABLE and st.button("Scan Statcast Alerts"):
            with st.spinner("Scanning velocity/spin/exit-velo data..."):
                players_to_scan = [
                    {'Player': row['Name'], 'Position': row.get('primary_position', 'Util')}
                    for _, row in recs.iterrows()
                ]
                results = analyze_keeper_list(players_to_scan, verbose=False)
                for r in results:
                    if r.get('alerts'):
                        alert_results[r['player']] = r['alerts']
                st.session_state['alert_results'] = alert_results
                if not alert_results:
                    st.success("No Statcast alerts found")

        # Use cached alerts if available
        if 'alert_results' in st.session_state:
            alert_results = st.session_state['alert_results']

        for idx, row in recs.iterrows():
            name = row.get('Name', '?')
            eligible = row.get('eligible_positions', '')
            if not eligible or (isinstance(eligible, float) and pd.isna(eligible)):
                eligible = row.get('primary_position', '?')
            pos = str(eligible).replace(',', '/')
            team = row.get('Team', '?')
            value = row.get('dollar_value', 0)
            surplus = row.get('surplus', 0)
            total = row.get('total_score', 0)
            cat_impact = row.get('category_impact', '')
            pos_note = row.get('position_note', '')
            notes = row.get('notes', '')

            with st.container(border=True):
                rank_col, info_col, score_col = st.columns([0.5, 3, 1])

                with rank_col:
                    st.markdown(f"### {idx + 1}")

                with info_col:
                    st.markdown(f"**{name}** ({pos}, {team})")
                    details = []
                    if cat_impact:
                        details.append(f"Categories: {cat_impact}")
                    if pos_note:
                        details.append(f"Position: {pos_note}")
                    if notes:
                        details.append(notes)
                    if details:
                        st.caption(' | '.join(details))

                    # Statcast alerts inline
                    if name in alert_results:
                        for alert in alert_results[name]:
                            st.warning(alert, icon="⚠️")

                    # News search link
                    query = f"{name} MLB 2026 fantasy baseball news"
                    news_url = f"https://news.google.com/search?q={quote_plus(query)}"
                    st.caption(f"[News]({news_url})")

                with score_col:
                    st.metric("Value", f"${value:.1f}", f"${surplus:+.1f}")

    # Expandable full table
    with st.expander("Full Available Players"):
        display_cols = ['Name', 'eligible_positions', 'primary_position', 'Team', 'dollar_value', 'overall_rank', 'player_type']
        display_cols = [c for c in display_cols if c in available.columns]
        st.dataframe(
            available[display_cols].head(50),
            use_container_width=True,
            hide_index=True,
        )

# --- Footer ---
st.markdown("---")
st.caption(
    f"Weights: Surplus={weights['surplus']:.0%}, "
    f"Category={weights['category']:.0%}, "
    f"Position={weights['position']:.0%}, "
    f"Keeper={weights['keeper']:.0%}"
)
