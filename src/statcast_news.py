#!/usr/bin/env python3
"""
statcast_news.py - Statcast data and news integration for fantasy baseball

Provides velocity/spin rate analysis and news alerts to enhance keeper
and draft decisions.

Alert Thresholds:
- Fastball velocity: ±1.5 mph (yellow), ±2.5 mph (red)
- Spin rate: ±200 rpm (yellow)
- Exit velocity: ±2.0 mph (yellow)
"""

from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

# pybaseball imports
try:
    from pybaseball import (
        playerid_lookup,
        statcast_pitcher,
        statcast_batter,
        cache
    )
    # Enable caching to avoid repeated API calls
    cache.enable()
    PYBASEBALL_AVAILABLE = True
except ImportError:
    PYBASEBALL_AVAILABLE = False
    print("Warning: pybaseball not installed. Run: pip install pybaseball")


# Alert thresholds (user requested 1.5 mph, lower than typical 2.0)
VELOCITY_THRESHOLD_YELLOW = 1.5  # mph
VELOCITY_THRESHOLD_RED = 2.5    # mph
SPIN_THRESHOLD = 200            # rpm
EXIT_VELO_THRESHOLD = 2.0       # mph

# Fastball pitch types in Statcast
FASTBALL_TYPES = ['FF', 'SI', 'FC', 'FA']  # 4-seam, sinker, cutter, generic fastball


def get_player_id(first_name: str, last_name: str) -> Optional[int]:
    """
    Convert player name to MLBAM ID using pybaseball.

    Args:
        first_name: Player's first name
        last_name: Player's last name

    Returns:
        MLBAM player ID or None if not found
    """
    if not PYBASEBALL_AVAILABLE:
        return None

    try:
        result = playerid_lookup(last_name, first_name)
        if len(result) == 0:
            return None
        # Return the most recent player (highest key_mlbam)
        return int(result.iloc[0]['key_mlbam'])
    except Exception as e:
        print(f"Error looking up {first_name} {last_name}: {e}")
        return None


def parse_player_name(full_name: str) -> tuple:
    """Split 'First Last' into (first, last). Handles Jr., III, etc."""
    parts = full_name.strip().split()
    if len(parts) < 2:
        return (full_name, "")
    # Handle suffixes like Jr., III, II
    suffixes = ['jr.', 'jr', 'sr.', 'sr', 'ii', 'iii', 'iv']
    if parts[-1].lower() in suffixes:
        last = parts[-2] if len(parts) > 2 else parts[-1]
        first = ' '.join(parts[:-2]) if len(parts) > 2 else parts[0]
    else:
        first = parts[0]
        last = ' '.join(parts[1:])
    return (first, last)


def get_pitcher_velocity_data(
    player_id: int,
    start_date: str,
    end_date: str
) -> dict:
    """
    Fetch Statcast velocity/spin data for a pitcher.

    Args:
        player_id: MLBAM player ID
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format

    Returns:
        Dict with fastball_velo, fastball_spin, sample_size, or empty if no data
    """
    if not PYBASEBALL_AVAILABLE:
        return {}

    try:
        data = statcast_pitcher(start_date, end_date, player_id)
        if data is None or len(data) == 0:
            return {}

        # Filter to fastballs only
        fastballs = data[data['pitch_type'].isin(FASTBALL_TYPES)]
        if len(fastballs) == 0:
            return {}

        return {
            'fastball_velo': fastballs['release_speed'].mean(),
            'fastball_spin': fastballs['release_spin_rate'].mean(),
            'sample_size': len(fastballs),
            'start_date': start_date,
            'end_date': end_date
        }
    except Exception as e:
        print(f"Error fetching pitcher data for ID {player_id}: {e}")
        return {}


def get_career_baseline(
    player_id: int,
    years: int = 2,
    exclude_current_year: bool = True
) -> dict:
    """
    Get career baseline velocity/spin for comparison.

    Args:
        player_id: MLBAM player ID
        years: Number of years to include in baseline
        exclude_current_year: Whether to exclude current year from baseline

    Returns:
        Dict with baseline fastball_velo and fastball_spin
    """
    if not PYBASEBALL_AVAILABLE:
        return {}

    current_year = datetime.now().year

    # Build date range for baseline (regular season only)
    end_year = current_year - 1 if exclude_current_year else current_year
    start_year = end_year - years + 1

    all_data = []
    for year in range(start_year, end_year + 1):
        try:
            # Regular season: April 1 - October 1
            start = f"{year}-04-01"
            end = f"{year}-10-01"
            data = statcast_pitcher(start, end, player_id)
            if data is not None and len(data) > 0:
                all_data.append(data)
        except Exception:
            continue

    if not all_data:
        return {}

    combined = pd.concat(all_data, ignore_index=True)
    fastballs = combined[combined['pitch_type'].isin(FASTBALL_TYPES)]

    if len(fastballs) == 0:
        return {}

    return {
        'fastball_velo': fastballs['release_speed'].mean(),
        'fastball_spin': fastballs['release_spin_rate'].mean(),
        'sample_size': len(fastballs),
        'years': f"{start_year}-{end_year}"
    }


def flag_velocity_changes(
    current: dict,
    baseline: dict,
    velocity_threshold: float = VELOCITY_THRESHOLD_YELLOW,
    spin_threshold: float = SPIN_THRESHOLD
) -> list:
    """
    Flag significant changes in velocity/spin from baseline.

    Args:
        current: Current period data (from get_pitcher_velocity_data)
        baseline: Career baseline data (from get_career_baseline)
        velocity_threshold: MPH change to flag (default 1.5 per user)
        spin_threshold: RPM change to flag (default 200)

    Returns:
        List of alert strings
    """
    alerts = []

    if not current or not baseline:
        return alerts

    # Check velocity change
    if 'fastball_velo' in current and 'fastball_velo' in baseline:
        velo_change = current['fastball_velo'] - baseline['fastball_velo']

        if abs(velo_change) >= VELOCITY_THRESHOLD_RED:
            direction = "UP" if velo_change > 0 else "DOWN"
            emoji = "🟢" if velo_change > 0 else "🔴"
            alerts.append(
                f"{emoji} Fastball velocity {direction} {abs(velo_change):.1f} mph "
                f"({baseline['fastball_velo']:.1f} → {current['fastball_velo']:.1f})"
            )
        elif abs(velo_change) >= velocity_threshold:
            direction = "UP" if velo_change > 0 else "DOWN"
            emoji = "⬆️" if velo_change > 0 else "⚠️"
            alerts.append(
                f"{emoji} Fastball velocity {direction} {abs(velo_change):.1f} mph "
                f"({baseline['fastball_velo']:.1f} → {current['fastball_velo']:.1f})"
            )

    # Check spin rate change
    if 'fastball_spin' in current and 'fastball_spin' in baseline:
        spin_change = current['fastball_spin'] - baseline['fastball_spin']

        if abs(spin_change) >= spin_threshold:
            direction = "UP" if spin_change > 0 else "DOWN"
            emoji = "🔄" if spin_change > 0 else "⚠️"
            alerts.append(
                f"{emoji} Spin rate {direction} {abs(spin_change):.0f} rpm "
                f"({baseline['fastball_spin']:.0f} → {current['fastball_spin']:.0f})"
            )

    return alerts


def get_batter_statcast(
    player_id: int,
    start_date: str,
    end_date: str
) -> dict:
    """
    Fetch batter Statcast data (exit velocity, barrel rate).

    Args:
        player_id: MLBAM player ID
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format

    Returns:
        Dict with exit_velo, barrel_rate, hard_hit_rate, or empty if no data
    """
    if not PYBASEBALL_AVAILABLE:
        return {}

    try:
        data = statcast_batter(start_date, end_date, player_id)
        if data is None or len(data) == 0:
            return {}

        # Filter to batted balls only (has launch_speed)
        batted = data[data['launch_speed'].notna()]
        if len(batted) == 0:
            return {}

        # Calculate metrics
        exit_velo = batted['launch_speed'].mean()

        # Barrel: launch_speed >= 98 mph and optimal launch angle
        barrels = batted[
            (batted['launch_speed'] >= 98) &
            (batted['launch_angle'] >= 26) &
            (batted['launch_angle'] <= 30)
        ]
        barrel_rate = len(barrels) / len(batted) * 100 if len(batted) > 0 else 0

        # Hard hit: 95+ mph
        hard_hit = batted[batted['launch_speed'] >= 95]
        hard_hit_rate = len(hard_hit) / len(batted) * 100 if len(batted) > 0 else 0

        return {
            'exit_velo': exit_velo,
            'barrel_rate': barrel_rate,
            'hard_hit_rate': hard_hit_rate,
            'sample_size': len(batted),
            'start_date': start_date,
            'end_date': end_date
        }
    except Exception as e:
        print(f"Error fetching batter data for ID {player_id}: {e}")
        return {}


def get_batter_baseline(
    player_id: int,
    years: int = 2,
    exclude_current_year: bool = True
) -> dict:
    """Get career baseline exit velocity for batter comparison."""
    if not PYBASEBALL_AVAILABLE:
        return {}

    current_year = datetime.now().year
    end_year = current_year - 1 if exclude_current_year else current_year
    start_year = end_year - years + 1

    all_data = []
    for year in range(start_year, end_year + 1):
        try:
            start = f"{year}-04-01"
            end = f"{year}-10-01"
            data = statcast_batter(start, end, player_id)
            if data is not None and len(data) > 0:
                all_data.append(data)
        except Exception:
            continue

    if not all_data:
        return {}

    combined = pd.concat(all_data, ignore_index=True)
    batted = combined[combined['launch_speed'].notna()]

    if len(batted) == 0:
        return {}

    return {
        'exit_velo': batted['launch_speed'].mean(),
        'sample_size': len(batted),
        'years': f"{start_year}-{end_year}"
    }


def flag_batter_changes(
    current: dict,
    baseline: dict,
    exit_velo_threshold: float = EXIT_VELO_THRESHOLD
) -> list:
    """Flag significant changes in batter exit velocity."""
    alerts = []

    if not current or not baseline:
        return alerts

    if 'exit_velo' in current and 'exit_velo' in baseline:
        velo_change = current['exit_velo'] - baseline['exit_velo']

        if abs(velo_change) >= exit_velo_threshold:
            direction = "UP" if velo_change > 0 else "DOWN"
            emoji = "💪" if velo_change > 0 else "⚠️"
            alerts.append(
                f"{emoji} Exit velocity {direction} {abs(velo_change):.1f} mph "
                f"({baseline['exit_velo']:.1f} → {current['exit_velo']:.1f})"
            )

    return alerts


def get_spring_training_dates(year: int = None) -> tuple:
    """
    Get Spring Training date range for a given year.

    Returns:
        Tuple of (start_date, end_date) in 'YYYY-MM-DD' format
    """
    if year is None:
        year = datetime.now().year

    # Spring Training typically runs mid-Feb to late March
    start = f"{year}-02-20"
    end = f"{year}-03-28"

    return (start, end)


def analyze_pitcher(player_name: str, verbose: bool = True) -> dict:
    """
    Full pitcher analysis with velocity/spin comparison.

    Args:
        player_name: Full name like "Gerrit Cole"
        verbose: Whether to print results

    Returns:
        Dict with current data, baseline, and alerts
    """
    first, last = parse_player_name(player_name)
    player_id = get_player_id(first, last)

    if not player_id:
        if verbose:
            print(f"Could not find player ID for {player_name}")
        return {'error': 'Player not found'}

    # Get Spring Training data
    st_start, st_end = get_spring_training_dates()
    current = get_pitcher_velocity_data(player_id, st_start, st_end)

    # Get career baseline
    baseline = get_career_baseline(player_id)

    # Flag changes
    alerts = flag_velocity_changes(current, baseline)

    result = {
        'player_name': player_name,
        'player_id': player_id,
        'spring_training': current,
        'career_baseline': baseline,
        'alerts': alerts
    }

    if verbose:
        print(f"\n{'='*60}")
        print(f"  PITCHER ANALYSIS: {player_name}")
        print(f"{'='*60}")

        if baseline:
            print(f"\n  Career Baseline ({baseline.get('years', 'N/A')}):")
            print(f"    Fastball: {baseline.get('fastball_velo', 0):.1f} mph")
            print(f"    Spin: {baseline.get('fastball_spin', 0):.0f} rpm")
            print(f"    Sample: {baseline.get('sample_size', 0):,} pitches")

        if current:
            print(f"\n  Spring Training 2026:")
            print(f"    Fastball: {current.get('fastball_velo', 0):.1f} mph")
            print(f"    Spin: {current.get('fastball_spin', 0):.0f} rpm")
            print(f"    Sample: {current.get('sample_size', 0):,} pitches")
        else:
            print(f"\n  No Spring Training data yet")

        if alerts:
            print(f"\n  Alerts:")
            for alert in alerts:
                print(f"    {alert}")
        else:
            print(f"\n  No significant changes detected")

    return result


def analyze_batter(player_name: str, verbose: bool = True) -> dict:
    """
    Full batter analysis with exit velocity comparison.

    Args:
        player_name: Full name like "Aaron Judge"
        verbose: Whether to print results

    Returns:
        Dict with current data, baseline, and alerts
    """
    first, last = parse_player_name(player_name)
    player_id = get_player_id(first, last)

    if not player_id:
        if verbose:
            print(f"Could not find player ID for {player_name}")
        return {'error': 'Player not found'}

    # Get Spring Training data
    st_start, st_end = get_spring_training_dates()
    current = get_batter_statcast(player_id, st_start, st_end)

    # Get career baseline
    baseline = get_batter_baseline(player_id)

    # Flag changes
    alerts = flag_batter_changes(current, baseline)

    result = {
        'player_name': player_name,
        'player_id': player_id,
        'spring_training': current,
        'career_baseline': baseline,
        'alerts': alerts
    }

    if verbose:
        print(f"\n{'='*60}")
        print(f"  BATTER ANALYSIS: {player_name}")
        print(f"{'='*60}")

        if baseline:
            print(f"\n  Career Baseline ({baseline.get('years', 'N/A')}):")
            print(f"    Exit Velocity: {baseline.get('exit_velo', 0):.1f} mph")
            print(f"    Sample: {baseline.get('sample_size', 0):,} batted balls")

        if current:
            print(f"\n  Spring Training 2026:")
            print(f"    Exit Velocity: {current.get('exit_velo', 0):.1f} mph")
            print(f"    Barrel Rate: {current.get('barrel_rate', 0):.1f}%")
            print(f"    Hard Hit Rate: {current.get('hard_hit_rate', 0):.1f}%")
            print(f"    Sample: {current.get('sample_size', 0):,} batted balls")
        else:
            print(f"\n  No Spring Training data yet")

        if alerts:
            print(f"\n  Alerts:")
            for alert in alerts:
                print(f"    {alert}")
        else:
            print(f"\n  No significant changes detected")

    return result


def is_pitcher(player_name: str, position: str = None) -> bool:
    """Determine if a player is a pitcher based on position."""
    if position:
        pos_upper = position.upper()
        return 'SP' in pos_upper or 'RP' in pos_upper or 'P' in pos_upper
    # Default to False if no position info
    return False


def analyze_player(player_name: str, position: str = None, verbose: bool = True) -> dict:
    """
    Analyze any player (auto-detects pitcher vs batter).

    Args:
        player_name: Full name like "Shohei Ohtani"
        position: Optional position hint (SP, RP, C, 1B, etc.)
        verbose: Whether to print results

    Returns:
        Analysis result dict
    """
    if is_pitcher(player_name, position):
        return analyze_pitcher(player_name, verbose)
    else:
        return analyze_batter(player_name, verbose)


# Convenience function for quick lookups
def quick_check(player_name: str, position: str = None) -> list:
    """
    Quick check for alerts only (minimal output).

    Args:
        player_name: Full name
        position: Optional position hint

    Returns:
        List of alert strings (empty if no alerts)
    """
    result = analyze_player(player_name, position, verbose=False)
    return result.get('alerts', [])


# ============================================================================
# NEWS SEARCH FUNCTIONS
# ============================================================================
# These functions generate search queries for use with Claude Code's WebSearch
# or can be used to construct RSS/API queries for injury/news monitoring.

# Keywords that indicate fantasy-relevant news
INJURY_KEYWORDS = [
    'injury', 'injured', 'IL', 'DL', 'surgery', 'rehab',
    'strain', 'sprain', 'fracture', 'torn', 'out',
    'day-to-day', 'week-to-week', 'season-ending'
]

PLAYING_TIME_KEYWORDS = [
    'lineup', 'starting', 'bench', 'platoon', 'roster',
    'called up', 'optioned', 'DFA', 'waived', 'traded',
    'depth chart', 'everyday', 'role'
]

VELOCITY_NEWS_KEYWORDS = [
    'velocity', 'mph', 'fastball', 'spin rate',
    'mechanical', 'delivery', 'arm angle'
]


def get_news_search_query(player_name: str, query_type: str = 'all') -> str:
    """
    Generate a search query for player news.

    Args:
        player_name: Full player name
        query_type: 'injury', 'playing_time', 'velocity', or 'all'

    Returns:
        Search query string optimized for finding relevant news
    """
    base_query = f"{player_name} MLB 2026"

    if query_type == 'injury':
        return f"{base_query} injury update"
    elif query_type == 'playing_time':
        return f"{base_query} playing time roster"
    elif query_type == 'velocity':
        return f"{base_query} velocity spring training"
    else:
        return f"{base_query} fantasy baseball news"


def format_news_for_display(headlines: list, max_items: int = 3) -> str:
    """
    Format news headlines for display in keeper/draft analysis.

    Args:
        headlines: List of headline strings
        max_items: Maximum number to display

    Returns:
        Formatted string for console output
    """
    if not headlines:
        return "  No recent news found"

    output = []
    for headline in headlines[:max_items]:
        # Truncate long headlines
        if len(headline) > 70:
            headline = headline[:67] + "..."
        output.append(f"  - {headline}")

    return "\n".join(output)


def check_headline_for_concerns(headline: str) -> list:
    """
    Check a headline for concerning keywords.

    Args:
        headline: News headline text

    Returns:
        List of concern types found ('injury', 'playing_time', etc.)
    """
    concerns = []
    headline_lower = headline.lower()

    for keyword in INJURY_KEYWORDS:
        if keyword.lower() in headline_lower:
            if 'injury' not in concerns:
                concerns.append('injury')
            break

    for keyword in PLAYING_TIME_KEYWORDS:
        if keyword.lower() in headline_lower:
            if 'playing_time' not in concerns:
                concerns.append('playing_time')
            break

    return concerns


def generate_player_summary(
    player_name: str,
    position: str = None,
    include_news_queries: bool = True
) -> dict:
    """
    Generate a comprehensive player summary for keeper/draft decisions.

    This combines Statcast analysis with news search queries that can be
    executed using Claude Code's WebSearch tool.

    Args:
        player_name: Full player name
        position: Position hint (SP, RP, C, 1B, etc.)
        include_news_queries: Whether to include news search queries

    Returns:
        Dict with:
        - statcast_analysis: Results from analyze_player()
        - alerts: Combined list of all alerts
        - news_queries: Search queries to run for news (if requested)
    """
    # Get Statcast analysis
    statcast = analyze_player(player_name, position, verbose=False)

    summary = {
        'player_name': player_name,
        'position': position,
        'statcast_analysis': statcast,
        'alerts': statcast.get('alerts', [])
    }

    if include_news_queries:
        summary['news_queries'] = {
            'general': get_news_search_query(player_name, 'all'),
            'injury': get_news_search_query(player_name, 'injury'),
            'playing_time': get_news_search_query(player_name, 'playing_time')
        }

    return summary


def print_player_report(player_name: str, position: str = None):
    """
    Print a formatted player report for keeper/draft analysis.

    Args:
        player_name: Full player name
        position: Position hint
    """
    print(f"\n{'='*70}")
    print(f"  PLAYER REPORT: {player_name}")
    print(f"{'='*70}")

    # Run analysis (this prints its own output)
    analyze_player(player_name, position, verbose=True)

    # Show news search queries
    print(f"\n  News Search Queries (run with WebSearch):")
    print(f"    General: \"{get_news_search_query(player_name, 'all')}\"")
    print(f"    Injury:  \"{get_news_search_query(player_name, 'injury')}\"")
    print()


# ============================================================================
# BATCH ANALYSIS FOR KEEPER LISTS
# ============================================================================

def analyze_keeper_list(players: list, verbose: bool = True) -> list:
    """
    Analyze a list of players for keeper decisions.

    Args:
        players: List of dicts with 'Player' and 'Position' keys
        verbose: Whether to print progress

    Returns:
        List of player summaries with alerts
    """
    results = []

    if verbose:
        print(f"\nAnalyzing {len(players)} players for alerts...")
        print("-" * 50)

    for i, player_info in enumerate(players):
        name = player_info.get('Player', player_info.get('player', ''))
        pos = player_info.get('Position', player_info.get('position', ''))

        if verbose:
            print(f"  [{i+1}/{len(players)}] {name}...", end=" ")

        try:
            summary = generate_player_summary(name, pos, include_news_queries=False)
            alerts = summary.get('alerts', [])

            if verbose:
                if alerts:
                    print(f"ALERTS: {len(alerts)}")
                    for alert in alerts:
                        print(f"         {alert}")
                else:
                    print("OK")

            results.append({
                'player': name,
                'position': pos,
                'alerts': alerts,
                'has_alerts': len(alerts) > 0
            })
        except Exception as e:
            if verbose:
                print(f"ERROR: {e}")
            results.append({
                'player': name,
                'position': pos,
                'alerts': [],
                'has_alerts': False,
                'error': str(e)
            })

    return results


def summarize_alerts(results: list) -> str:
    """
    Summarize alerts from a batch analysis.

    Args:
        results: Output from analyze_keeper_list()

    Returns:
        Formatted summary string
    """
    players_with_alerts = [r for r in results if r.get('has_alerts')]

    if not players_with_alerts:
        return "No alerts found for any players."

    output = [f"\n{'='*60}"]
    output.append(f"  ALERT SUMMARY: {len(players_with_alerts)} players with alerts")
    output.append(f"{'='*60}\n")

    for result in players_with_alerts:
        output.append(f"  {result['player']} ({result['position']}):")
        for alert in result['alerts']:
            output.append(f"    {alert}")
        output.append("")

    return "\n".join(output)


if __name__ == '__main__':
    # Test the module
    print("Testing Statcast News Module")
    print("=" * 60)

    if not PYBASEBALL_AVAILABLE:
        print("pybaseball not installed. Install with: pip install pybaseball")
    else:
        # Test with a known pitcher
        print("\nTesting pitcher lookup and analysis...")
        analyze_pitcher("Gerrit Cole")

        print("\nTesting batter lookup and analysis...")
        analyze_batter("Aaron Judge")

        # Test news query generation
        print("\n" + "=" * 60)
        print("  NEWS QUERY GENERATION TEST")
        print("=" * 60)
        print(f"\nGeneral query: {get_news_search_query('Jackson Holliday', 'all')}")
        print(f"Injury query:  {get_news_search_query('Jackson Holliday', 'injury')}")

        # Test batch analysis with sample players
        print("\n" + "=" * 60)
        print("  BATCH ANALYSIS TEST (sample players)")
        print("=" * 60)
        sample_players = [
            {'Player': 'Bobby Witt Jr.', 'Position': 'SS'},
            {'Player': 'Elly De La Cruz', 'Position': 'SS'},
        ]
        results = analyze_keeper_list(sample_players)
        print(summarize_alerts(results))
