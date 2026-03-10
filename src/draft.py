"""
draft.py - Draft recommendation engine

Scores available players and produces ranked recommendations based on:
1. Surplus value (40%) - SGP dollar value vs draft round cost
2. Category need (25%) - How well the player fills your weakest categories
3. Position need (20%) - Whether you need this roster slot filled
4. Keeper upside (15%) - Long-term value (age, keeper cost trajectory)

Weights shift by draft phase:
- Early rounds (1-8): surplus dominates
- Mid rounds (9-16): balanced
- Late rounds (17-25): keeper upside increases
"""

import pandas as pd
import numpy as np
from pathlib import Path
from difflib import SequenceMatcher

# Draft round value curve (what each round is "worth" in dollars)
# Shared with run_keeper_analysis.py
DRAFT_ROUND_VALUES = {
    1: 50, 2: 42, 3: 35, 4: 30, 5: 26, 6: 23, 7: 20, 8: 18,
    9: 16, 10: 14, 11: 12, 12: 10, 13: 9, 14: 8, 15: 7,
    16: 6, 17: 5, 18: 4, 19: 3, 20: 2, 21: 2, 22: 1, 23: 1, 24: 1, 25: 1
}

# Default scoring weights
DEFAULT_WEIGHTS = {
    'surplus': 0.40,
    'category': 0.25,
    'position': 0.20,
    'keeper': 0.15,
}

# Roster slot requirements (standard Yahoo fantasy baseball)
ROSTER_SLOTS = {
    'C': 1, '1B': 1, '2B': 1, '3B': 1, 'SS': 1,
    'OF': 3, 'Util': 2,
    'SP': 5, 'RP': 3,
    'BN': 4,
}

# Categories for 5x5
HITTING_CATS = ['R', 'HR', 'RBI', 'SB', 'OBP']
PITCHING_CATS = ['W', 'SV', 'K', 'ERA', 'WHIP']

# SGP denominators (from sgp_valuation.py) — how many stat points per standings position
SGP_DENOMINATORS = {
    'R': 22, 'HR': 9, 'RBI': 22, 'SB': 7,
    'W': 3, 'SV': 7, 'K': 35,
}

# Rate stat denominators (OBP, ERA, WHIP per standings position)
RATE_DENOMINATORS = {
    'OBP': 0.015,
    'ERA': 0.25,
    'WHIP': 0.04,
}

# Categories where lower is better
LOWER_IS_BETTER = {'ERA', 'WHIP'}


def get_phase_weights(current_round: int) -> dict:
    """
    Adjust scoring weights based on draft phase.

    Early rounds: surplus value matters most (getting best player available).
    Late rounds: keeper upside matters more (cheap keepers for future years).
    """
    if current_round <= 8:
        return {'surplus': 0.50, 'category': 0.20, 'position': 0.20, 'keeper': 0.10}
    elif current_round <= 16:
        return {'surplus': 0.35, 'category': 0.30, 'position': 0.20, 'keeper': 0.15}
    else:
        return {'surplus': 0.25, 'category': 0.25, 'position': 0.20, 'keeper': 0.30}


def load_prospect_watchlist(path: str = None) -> pd.DataFrame:
    """
    Load the prospect watchlist CSV and format it to match SGP values columns.

    Watchlist players are minor leaguers or unrojected players that should
    appear in draft recommendations despite having no Fangraphs projections.

    CSV format: Name, Position, EstimatedValue, Notes, Boost
    Boost is an optional multiplier (default 1.0) for players you like more than consensus.
    """
    if path is None:
        path = Path(__file__).parent.parent / 'data' / 'prospect_watchlist.csv'
    else:
        path = Path(path)

    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame()

    # Apply boost multiplier to estimated value (default 1.0)
    boost = df['Boost'].fillna(1.0) if 'Boost' in df.columns else 1.0
    boosted_value = df['EstimatedValue'] * boost

    # Map watchlist columns to match SGP values format
    result = pd.DataFrame({
        'Name': df['Name'],
        'primary_position': df['Position'],
        'dollar_value': boosted_value,
        'player_type': df['Position'].apply(
            lambda p: 'Pitcher' if p in ('SP', 'RP') else 'Hitter'
        ),
        'overall_rank': 999,
        'Team': 'Prospect',
        'total_sgp': 0,
        'ADP': None,
    })

    # Add empty stat columns so merging works
    for col in ['R', 'HR', 'RBI', 'SB', 'OBP', 'PA', 'W', 'SV', 'K', 'ERA', 'WHIP', 'IP']:
        result[col] = 0 if col not in ('OBP', 'ERA', 'WHIP') else None

    # Add notes if present
    if 'Notes' in df.columns:
        result['prospect_notes'] = df['Notes']

    return result


def merge_watchlist(available: pd.DataFrame, watchlist: pd.DataFrame) -> pd.DataFrame:
    """Merge prospect watchlist players into the available player pool."""
    if watchlist.empty:
        return available

    # Only add watchlist players not already in available pool
    existing_names = set(available['Name'].str.lower().str.strip())
    new_prospects = watchlist[
        ~watchlist['Name'].str.lower().str.strip().isin(existing_names)
    ]

    if new_prospects.empty:
        return available

    return pd.concat([available, new_prospects], ignore_index=True)


def adp_to_round(adp: float, num_teams: int = 14) -> int:
    """Convert Fangraphs ADP (overall pick number) to draft round."""
    if pd.isna(adp) or adp <= 0:
        return 25  # No ADP data = late round default
    return min(25, max(1, int((adp - 1) // num_teams) + 1))


def calculate_surplus(available: pd.DataFrame, current_round: int,
                      num_teams: int = 14) -> pd.Series:
    """
    Calculate surplus value with ADP availability adjustment.

    Base surplus = SGP dollar value - round cost.
    Then penalize players whose ADP says they'd already be drafted by now.
    This makes the simulation realistic: don't recommend players who are
    likely already off the board.
    """
    round_cost = DRAFT_ROUND_VALUES.get(current_round, 1)
    sgp_surplus = available['dollar_value'] - round_cost

    if 'ADP' not in available.columns:
        return sgp_surplus

    # Current pick number (approximate: start of this round)
    current_pick = (current_round - 1) * num_teams + 1

    def _adjust(row):
        adp = row.get('ADP', None)
        surplus = row['dollar_value'] - round_cost

        if pd.isna(adp) or adp <= 0:
            return surplus  # No ADP data, use raw surplus

        # If player's ADP is well before this pick, they're likely gone.
        # Apply a penalty proportional to how far before our pick they go.
        if adp < current_pick:
            # Penalty: reduces surplus by up to 50% for players gone early
            gone_ratio = min(1.0, (current_pick - adp) / current_pick)
            penalty = gone_ratio * 0.5
            return surplus * (1 - penalty)

        return surplus

    return available.apply(_adjust, axis=1)


def flag_likely_gone(available: pd.DataFrame, current_round: int,
                     num_teams: int = 14) -> pd.Series:
    """
    Flag players whose ADP suggests they'd already be drafted by this round.

    Returns a Series of strings: empty if available, warning if likely gone.
    """
    if 'ADP' not in available.columns:
        return pd.Series('', index=available.index)

    # Approximate overall pick number for start of current round
    current_pick_overall = (current_round - 1) * num_teams + 1

    def _flag(adp):
        if pd.isna(adp) or adp <= 0:
            return ''
        if adp < current_pick_overall * 0.7:
            return f'ADP {adp:.0f} — likely gone'
        return ''

    return available['ADP'].apply(_flag)


def project_team_totals(roster: pd.DataFrame, sgp_values: pd.DataFrame) -> dict:
    """
    Project category totals for the current team roster.

    Matches roster player names to SGP values to get projected stats,
    then sums counting stats and calculates weighted rate stats.

    Returns:
        Dict with projected totals: {R: 850, HR: 210, ..., OBP: 0.340, ERA: 3.75, ...}
    """
    if roster.empty:
        return {cat: 0 for cat in HITTING_CATS + PITCHING_CATS}

    # Match roster players to SGP values
    matched = _match_roster_to_values(roster, sgp_values)

    totals = {}

    # Counting stats: simple sum
    for cat in ['R', 'HR', 'RBI', 'SB', 'W', 'SV', 'K']:
        totals[cat] = matched[cat].sum() if cat in matched.columns else 0

    # Rate stats: weighted average
    # OBP = sum(OBP_i * PA_i) / sum(PA_i)
    if 'OBP' in matched.columns and 'PA' in matched.columns:
        hitters = matched[matched['PA'].notna() & (matched['PA'] > 0)]
        if not hitters.empty:
            totals['OBP'] = (hitters['OBP'] * hitters['PA']).sum() / hitters['PA'].sum()
        else:
            totals['OBP'] = 0
    else:
        totals['OBP'] = 0

    # ERA = sum(ERA_i * IP_i) / sum(IP_i)
    if 'ERA' in matched.columns and 'IP' in matched.columns:
        pitchers = matched[matched['IP'].notna() & (matched['IP'] > 0)]
        if not pitchers.empty:
            totals['ERA'] = (pitchers['ERA'] * pitchers['IP']).sum() / pitchers['IP'].sum()
        else:
            totals['ERA'] = 0
    else:
        totals['ERA'] = 0

    # WHIP = sum(WHIP_i * IP_i) / sum(IP_i)
    if 'WHIP' in matched.columns and 'IP' in matched.columns:
        pitchers = matched[matched['IP'].notna() & (matched['IP'] > 0)]
        if not pitchers.empty:
            totals['WHIP'] = (pitchers['WHIP'] * pitchers['IP']).sum() / pitchers['IP'].sum()
        else:
            totals['WHIP'] = 0
    else:
        totals['WHIP'] = 0

    # Also track total PA and IP for rate stat calculations
    totals['total_PA'] = matched['PA'].sum() if 'PA' in matched.columns else 0
    totals['total_IP'] = matched['IP'].sum() if 'IP' in matched.columns else 0

    return totals


def calculate_league_targets(sgp_values: pd.DataFrame, num_teams: int = 14) -> dict:
    """
    Calculate league-average team targets from the player pool.

    Builds 14 "average" teams by distributing the top players evenly,
    then computes the per-team average for each category.
    """
    hitters = sgp_values[sgp_values['player_type'] == 'Hitter'].head(14 * 14)  # ~14 hitters per team
    pitchers = sgp_values[sgp_values['player_type'] == 'Pitcher'].head(14 * 9)  # ~9 pitchers per team

    targets = {}

    # Counting stats: total pool / num_teams
    for cat in ['R', 'HR', 'RBI', 'SB']:
        if cat in hitters.columns:
            targets[cat] = hitters[cat].sum() / num_teams
    for cat in ['W', 'SV', 'K']:
        if cat in pitchers.columns:
            targets[cat] = pitchers[cat].sum() / num_teams

    # Rate stats: average of top players
    if 'OBP' in hitters.columns:
        top_hitters = hitters.nlargest(num_teams * 10, 'dollar_value')
        targets['OBP'] = top_hitters['OBP'].mean() if not top_hitters.empty else 0.330
    else:
        targets['OBP'] = 0.330

    if 'ERA' in pitchers.columns:
        top_pitchers = pitchers.nlargest(num_teams * 7, 'dollar_value')
        targets['ERA'] = top_pitchers['ERA'].mean() if not top_pitchers.empty else 3.80
    else:
        targets['ERA'] = 3.80

    if 'WHIP' in pitchers.columns:
        top_pitchers = pitchers.nlargest(num_teams * 7, 'dollar_value')
        targets['WHIP'] = top_pitchers['WHIP'].mean() if not top_pitchers.empty else 1.20
    else:
        targets['WHIP'] = 1.20

    return targets


def calculate_category_needs(team_totals: dict, targets: dict) -> dict:
    """
    Calculate how much the team needs each category.

    Returns dict of {category: need_score} where higher = more need.
    Need is measured in SGP units (standings positions behind target).
    """
    needs = {}

    for cat in HITTING_CATS + PITCHING_CATS:
        my_total = team_totals.get(cat, 0)
        target = targets.get(cat, 0)

        if cat in SGP_DENOMINATORS:
            # Counting stat: gap in SGP terms
            gap = target - my_total
            needs[cat] = gap / SGP_DENOMINATORS[cat]
        elif cat in RATE_DENOMINATORS:
            # Rate stat: gap in SGP terms
            if cat in LOWER_IS_BETTER:
                gap = my_total - target  # Higher ERA = worse = more need
            else:
                gap = target - my_total  # Lower OBP = worse = more need
            needs[cat] = gap / RATE_DENOMINATORS[cat]

    return needs


def score_player_category_fit(player: pd.Series, category_needs: dict,
                              team_totals: dict) -> float:
    """
    Score how well a player fills the team's category needs.

    For counting stats: player's SGP contribution × category need weight.
    For rate stats: calculate new team rate after adding player, measure improvement.
    """
    score = 0.0

    for cat in HITTING_CATS + PITCHING_CATS:
        need = category_needs.get(cat, 0)
        if need <= 0:
            # Team is at or above target in this category
            # Still give small credit for counting stats (more is always better)
            need = max(need, 0.1) if cat not in LOWER_IS_BETTER else 0

        player_stat = player.get(cat, 0)
        if pd.isna(player_stat) or player_stat == 0:
            continue

        if cat in SGP_DENOMINATORS:
            # Counting stat: contribution in SGP terms
            contribution = player_stat / SGP_DENOMINATORS[cat]
            score += contribution * max(need, 0.1)

        elif cat == 'OBP':
            # Rate stat: calculate new team OBP after adding player
            player_pa = player.get('PA', 0)
            if pd.isna(player_pa) or player_pa == 0:
                continue
            total_pa = team_totals.get('total_PA', 0)
            current_obp = team_totals.get('OBP', 0)
            if total_pa > 0:
                new_obp = (current_obp * total_pa + player_stat * player_pa) / (total_pa + player_pa)
                improvement = (new_obp - current_obp) / RATE_DENOMINATORS['OBP']
            else:
                improvement = (player_stat - 0.320) / RATE_DENOMINATORS['OBP']
            score += improvement * max(need, 0.1)

        elif cat in ('ERA', 'WHIP'):
            # Rate stat (lower is better): calculate new team rate
            player_ip = player.get('IP', 0)
            if pd.isna(player_ip) or player_ip == 0:
                continue
            total_ip = team_totals.get('total_IP', 0)
            current_rate = team_totals.get(cat, 0)
            if total_ip > 0:
                new_rate = (current_rate * total_ip + player_stat * player_ip) / (total_ip + player_ip)
                improvement = (current_rate - new_rate) / RATE_DENOMINATORS[cat]
            else:
                replacement = 4.50 if cat == 'ERA' else 1.35
                improvement = (replacement - player_stat) / RATE_DENOMINATORS[cat]
            score += improvement * max(need, 0.1)

    return score


def calculate_position_needs(roster: pd.DataFrame, sgp_values: pd.DataFrame) -> dict:
    """
    Determine which roster positions are filled vs empty.

    Returns dict of {position: need_multiplier}:
    - Empty starting position → 1.5
    - Partially filled (e.g., 2 of 3 OF) → 1.2
    - Already filled → 0.8
    """
    # Count filled positions
    filled = {}
    if not roster.empty:
        matched = _match_roster_to_values(roster, sgp_values)
        if 'primary_position' in matched.columns:
            filled = matched['primary_position'].value_counts().to_dict()

    needs = {}
    for pos, slots in ROSTER_SLOTS.items():
        if pos == 'BN':
            continue  # Bench doesn't have position need
        if pos == 'Util':
            continue  # Util is flexible

        current = filled.get(pos, 0)
        if current == 0:
            needs[pos] = 1.5  # High need: no one at this position
        elif current < slots:
            needs[pos] = 1.2  # Moderate need: partially filled
        else:
            needs[pos] = 0.8  # Low need: already filled

    return needs


def score_player_position_fit(player: pd.Series, position_needs: dict) -> float:
    """
    Score how well a player fills a positional need.
    """
    pos = player.get('primary_position', 'Util')
    if pd.isna(pos):
        pos = 'Util'

    return position_needs.get(pos, 1.0)


def calculate_keeper_premium(player: pd.Series, current_round: int) -> float:
    """
    Calculate keeper league upside for a player.

    In a keeper league, drafting a player late gives you cheap keeper value
    for up to 3 years. The premium is based on:
    1. How late in the draft (cheaper keeper cost)
    2. How much value relative to that cost

    Keeper cost trajectory:
    - Year 1: drafted at round N
    - Year 2: kept at round N-3
    - Year 3: kept at round N-6
    """
    dollar_value = player.get('dollar_value', 0)
    if pd.isna(dollar_value):
        return 0

    # Keeper cost for future years
    # Year 2: current_round - 3 (minimum round 1)
    # Year 3: current_round - 6 (minimum round 1)
    year2_round = max(1, current_round - 3)
    year3_round = max(1, current_round - 6)

    year2_cost = DRAFT_ROUND_VALUES.get(year2_round, 50)
    year3_cost = DRAFT_ROUND_VALUES.get(year3_round, 50)

    # Can't keep players drafted in rounds 1-3
    # If keeper round would be 1-3, player becomes ineligible
    if year2_round <= 3:
        year2_surplus = 0
        year3_surplus = 0
    elif year3_round <= 3:
        year2_surplus = max(0, dollar_value - year2_cost)
        year3_surplus = 0
    else:
        year2_surplus = max(0, dollar_value - year2_cost)
        year3_surplus = max(0, dollar_value - year3_cost)

    # Discount future value (player might decline, uncertainty)
    future_value = year2_surplus * 0.7 + year3_surplus * 0.4

    # Late-round bonus: bigger premium for cheap picks
    if current_round >= 18:
        future_value *= 1.3  # Extra bonus for waiver-wire-level picks
    elif current_round >= 13:
        future_value *= 1.1

    return future_value


def normalize_scores(series: pd.Series) -> pd.Series:
    """Normalize a score series to 0-1 range."""
    min_val = series.min()
    max_val = series.max()
    if max_val == min_val:
        return pd.Series(0.5, index=series.index)
    return (series - min_val) / (max_val - min_val)


def get_recommendations(available_players: pd.DataFrame,
                        my_roster: pd.DataFrame,
                        sgp_values: pd.DataFrame,
                        current_round: int,
                        num_recommendations: int = 8,
                        weights: dict = None) -> pd.DataFrame:
    """
    Score all available players and return top recommendations.

    Args:
        available_players: SGP-valued players not yet drafted
        my_roster: DataFrame of my current picks (Player, Round columns)
        sgp_values: Full SGP values DataFrame (for lookups)
        current_round: Current draft round (1-25)
        num_recommendations: How many players to recommend
        weights: Override scoring weights {surplus, category, position, keeper}

    Returns:
        DataFrame with columns:
            Name, primary_position, dollar_value, surplus, category_score,
            position_score, keeper_score, total_score, category_impact, notes
    """
    if available_players.empty:
        return pd.DataFrame()

    # Use phase-appropriate weights if not overridden
    if weights is None:
        weights = get_phase_weights(current_round)

    # Calculate team state
    team_totals = project_team_totals(my_roster, sgp_values)
    targets = calculate_league_targets(sgp_values)
    category_needs = calculate_category_needs(team_totals, targets)
    position_needs = calculate_position_needs(my_roster, sgp_values)

    # Score each available player
    results = available_players.copy()

    # Component A: Surplus value
    results['surplus'] = calculate_surplus(results, current_round)

    # Component B: Category fit
    results['category_score'] = results.apply(
        lambda row: score_player_category_fit(row, category_needs, team_totals),
        axis=1
    )

    # Component C: Position fit
    results['position_score'] = results.apply(
        lambda row: score_player_position_fit(row, position_needs),
        axis=1
    )

    # Component D: Keeper upside
    results['keeper_score'] = results.apply(
        lambda row: calculate_keeper_premium(row, current_round),
        axis=1
    )

    # Normalize each component to 0-1
    results['norm_surplus'] = normalize_scores(results['surplus'])
    results['norm_category'] = normalize_scores(results['category_score'])
    results['norm_position'] = normalize_scores(results['position_score'])
    results['norm_keeper'] = normalize_scores(results['keeper_score'])

    # Weighted composite score
    results['total_score'] = (
        weights['surplus'] * results['norm_surplus'] +
        weights['category'] * results['norm_category'] +
        weights['position'] * results['norm_position'] +
        weights['keeper'] * results['norm_keeper']
    )

    # Sort by total score
    results = results.sort_values('total_score', ascending=False)

    # Add category impact summary
    results['category_impact'] = results.apply(
        lambda row: _format_category_impact(row, category_needs),
        axis=1
    )

    # Add position need note
    results['position_note'] = results.apply(
        lambda row: _format_position_note(row, position_needs),
        axis=1
    )

    # Flag players likely already gone based on ADP
    results['adp_flag'] = flag_likely_gone(results, current_round)
    results['notes'] = results['adp_flag']

    # Select output columns
    output_cols = [
        'Name', 'Team', 'primary_position', 'player_type',
        'dollar_value', 'surplus', 'category_score', 'position_score',
        'keeper_score', 'total_score', 'category_impact', 'position_note', 'notes',
        'R', 'HR', 'RBI', 'SB', 'OBP', 'W', 'SV', 'K', 'ERA', 'WHIP',
        'ADP', 'overall_rank', 'playing_time',
    ]
    output_cols = [c for c in output_cols if c in results.columns]

    return results[output_cols].head(num_recommendations).reset_index(drop=True)


def format_recommendations(recs: pd.DataFrame, current_round: int,
                           category_needs: dict = None) -> str:
    """
    Format recommendations for display (CLI or Streamlit).

    Returns a formatted string showing each recommendation with context.
    """
    if recs.empty:
        return "No recommendations available."

    lines = []
    lines.append(f"\n{'='*75}")
    lines.append(f"  DRAFT RECOMMENDATIONS — Round {current_round}")
    lines.append(f"{'='*75}")

    for idx, row in recs.iterrows():
        rank = idx + 1
        name = row.get('Name', '?')
        pos = row.get('primary_position', '?')
        team = row.get('Team', '?')
        value = row.get('dollar_value', 0)
        surplus = row.get('surplus', 0)
        total = row.get('total_score', 0)
        cat_impact = row.get('category_impact', '')
        pos_note = row.get('position_note', '')
        notes = row.get('notes', '')

        lines.append(f"\n  {rank}. {name} ({pos}, {team})")
        lines.append(f"     Value: ${value:.1f}  |  Surplus: ${surplus:+.1f}  |  Score: {total:.3f}")

        if cat_impact:
            lines.append(f"     Categories: {cat_impact}")
        if pos_note:
            lines.append(f"     Position: {pos_note}")
        if notes:
            lines.append(f"     {notes}")

    lines.append(f"\n{'='*75}")
    return '\n'.join(lines)


# --- Internal helpers ---

def _match_roster_to_values(roster: pd.DataFrame,
                            sgp_values: pd.DataFrame) -> pd.DataFrame:
    """
    Match roster player names to SGP values using fuzzy matching.
    Returns the SGP rows for matched players.
    """
    if roster.empty:
        return pd.DataFrame()

    matched_rows = []
    for _, roster_row in roster.iterrows():
        player_name = roster_row.get('Player', '')
        if not player_name or pd.isna(player_name):
            continue

        # Try exact match
        exact = sgp_values[sgp_values['Name'].str.lower().str.strip() ==
                           player_name.lower().strip()]
        if not exact.empty:
            matched_rows.append(exact.iloc[0])
            continue

        # Try fuzzy match
        best_score = 0
        best_row = None
        for _, val_row in sgp_values.iterrows():
            score = SequenceMatcher(
                None, player_name.lower().strip(), val_row['Name'].lower().strip()
            ).ratio()
            if score > best_score and score > 0.8:
                best_score = score
                best_row = val_row

        if best_row is not None:
            matched_rows.append(best_row)

    if not matched_rows:
        return pd.DataFrame()

    return pd.DataFrame(matched_rows)


def _format_category_impact(player: pd.Series, category_needs: dict) -> str:
    """Format a short string showing which categories this player helps most."""
    impacts = []

    for cat in HITTING_CATS + PITCHING_CATS:
        val = player.get(cat, 0)
        need = category_needs.get(cat, 0)
        if pd.isna(val) or val == 0:
            continue

        if cat in SGP_DENOMINATORS:
            sgp_contribution = val / SGP_DENOMINATORS[cat]
            if need > 0.5 and sgp_contribution > 0.5:
                impacts.append(f"+{val:.0f} {cat}")
        elif cat == 'OBP' and need > 0.5:
            impacts.append(f".{int(val*1000):03d} OBP")
        elif cat in LOWER_IS_BETTER and need > 0.5:
            impacts.append(f"{val:.2f} {cat}")

    if not impacts:
        # Show top 2 stats regardless of need
        for cat in ['HR', 'SB', 'R', 'K', 'SV', 'W']:
            val = player.get(cat, 0)
            if not pd.isna(val) and val > 0:
                impacts.append(f"+{val:.0f} {cat}")
            if len(impacts) >= 2:
                break

    return ', '.join(impacts[:4])


def _format_position_note(player: pd.Series, position_needs: dict) -> str:
    """Format a note about position fit."""
    pos = player.get('primary_position', 'Util')
    if pd.isna(pos):
        pos = 'Util'

    need = position_needs.get(pos, 1.0)
    if need >= 1.5:
        return f"{pos} — HIGH NEED (empty slot)"
    elif need >= 1.2:
        return f"{pos} — partial need"
    elif need <= 0.8:
        return f"{pos} — already filled"
    return pos
