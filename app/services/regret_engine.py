"""Regret Engine Service - Precomputation of regret metrics.

Calculates three pillars of regret:
1. Draft Regret - Missed draft opportunities
2. Waiver Regret - Missed waiver wire pickups
3. Start/Sit Regret - Suboptimal lineup decisions
"""

import polars as pl
from typing import Dict, List, Any, Optional, Tuple
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.lineup_optimizer import LineupOptimizer

logger = logging.getLogger(__name__)


class DraftRegretCalculator:
    """Calculate draft regret metrics for each team."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def calculate_draft_regret(self, team_id: str) -> List[Dict[str, Any]]:
        """Calculate top 3 draft regrets for a team.

        For each draft pick, identify players drafted within ±3 picks
        at the same position and calculate the delta in season points.
        """
        from app.models import LeagueDraftResult, PlayerMap, NflGameLog

        # Get team's draft picks
        result = await self.session.execute(
            select(LeagueDraftResult)
            .where(LeagueDraftResult.team_id == team_id)
            .order_by(LeagueDraftResult.overall_pick)
        )
        team_picks = result.scalars().all()

        # Get all draft picks for comparison
        result = await self.session.execute(
            select(LeagueDraftResult)
            .order_by(LeagueDraftResult.overall_pick)
        )
        all_picks = result.scalars().all()

        # Get player mappings (yahoo_id -> gsis_id and position)
        result = await self.session.execute(select(PlayerMap))
        player_map_rows = result.scalars().all()
        player_maps = {row.yahoo_id: row.gsis_id for row in player_map_rows}
        player_names = {row.yahoo_id: row.full_name for row in player_map_rows}

        # Get all NFL game logs for season (points + positions)
        result = await self.session.execute(select(NflGameLog))
        game_logs = result.scalars().all()

        # Calculate season points and extract positions for each player
        player_season_points: Dict[str, float] = {}
        player_positions: Dict[str, str] = {}
        for log in game_logs:
            player_id = log.player_id
            points = log.fantasy_points
            if player_id not in player_season_points:
                player_season_points[player_id] = 0
            player_season_points[player_id] += points
            if log.raw_stats and "position" in log.raw_stats:
                player_positions[player_id] = log.raw_stats["position"]

        # Build yahoo_id -> position lookup via gsis_id
        yahoo_positions: Dict[str, str] = {}
        for yahoo_id, gsis_id in player_maps.items():
            if gsis_id in player_positions:
                yahoo_positions[yahoo_id] = player_positions[gsis_id]

        regrets = []

        for pick in team_picks:
            yahoo_id = pick.player_id
            gsis_id = player_maps.get(yahoo_id)

            if not gsis_id:
                logger.warning(f"No GSIS ID found for Yahoo ID {yahoo_id}")
                continue

            drafted_points = player_season_points.get(gsis_id, 0)
            drafted_position = yahoo_positions.get(yahoo_id, "")

            # Find players drafted within ±3 picks at the same position
            nearby_picks = [
                p for p in all_picks
                if abs(p.overall_pick - pick.overall_pick) <= 3
                and p.player_id != yahoo_id
                and yahoo_positions.get(p.player_id, "") == drafted_position
            ]

            for nearby_pick in nearby_picks:
                nearby_yahoo_id = nearby_pick.player_id
                nearby_gsis_id = player_maps.get(nearby_yahoo_id)

                if not nearby_gsis_id:
                    continue

                nearby_points = player_season_points.get(nearby_gsis_id, 0)

                # Calculate delta (negative means you made a good pick)
                delta = nearby_points - drafted_points

                if delta > 0:  # Only track misses
                    regrets.append({
                        "overall_pick": pick.overall_pick,
                        "round": pick.round,
                        "drafted_player_id": yahoo_id,
                        "drafted_player_name": player_names.get(yahoo_id, f"Player #{yahoo_id}"),
                        "drafted_player_points": drafted_points,
                        "drafted_position": drafted_position,
                        "missed_player_id": nearby_yahoo_id,
                        "missed_player_name": player_names.get(
                            nearby_yahoo_id, f"Player #{nearby_yahoo_id}"
                        ),
                        "missed_player_points": nearby_points,
                        "points_delta": delta,
                        "pick_distance": abs(nearby_pick.overall_pick - pick.overall_pick)
                    })

        # Sort by delta and keep top 3
        regrets.sort(key=lambda x: x["points_delta"], reverse=True)
        return regrets[:3]
    
    async def _resolve_player_name(self, yahoo_id: str) -> str:
        """Resolve a Yahoo player ID to a name via player_map."""
        from app.models import PlayerMap
        result = await self.session.execute(
            select(PlayerMap).where(PlayerMap.yahoo_id == yahoo_id)
        )
        pm = result.scalar_one_or_none()
        return pm.full_name if pm else f"Player #{yahoo_id}"

    async def generate_narrative(self, regret: Dict[str, Any]) -> str:
        """Generate narrative for draft regret spotlight card."""
        drafted_name = await self._resolve_player_name(regret["drafted_player_id"])
        missed_name = await self._resolve_player_name(regret["missed_player_id"])
        return (
            f"With pick #{regret['overall_pick']} (round {regret['round']}), "
            f"you drafted {drafted_name} ({regret['drafted_player_points']:.1f} pts) "
            f"instead of {missed_name} ({regret['missed_player_points']:.1f} pts). "
            f"That's {regret['points_delta']:.1f} points left on the table."
        )


class WaiverRegretCalculator:
    """Calculate waiver wire regret: best FA you could have signed."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._player_maps: Optional[Dict[str, str]] = None
        self._player_names: Optional[Dict[str, str]] = None
        self._ros_points: Optional[Dict[str, Dict[int, float]]] = None
        self._player_positions: Optional[Dict[str, str]] = None

    async def _load_lookups(self, season_year: int = 2024):
        """Load shared lookup tables once."""
        if self._player_maps is not None:
            return
        from app.models import PlayerMap, NflGameLog

        result = await self.session.execute(select(PlayerMap))
        maps = result.scalars().all()
        self._player_maps = {r.yahoo_id: r.gsis_id for r in maps}
        self._player_names = {r.yahoo_id: r.full_name for r in maps}

        # Build ROS points and position lookup from game logs
        result = await self.session.execute(
            select(NflGameLog).where(NflGameLog.season_year == season_year)
        )
        logs = result.scalars().all()

        # ros_points[gsis_id][from_week] = sum of points from from_week to 17
        pts_by_week: Dict[str, Dict[int, float]] = {}
        self._player_positions = {}
        for log in logs:
            pts_by_week.setdefault(log.player_id, {})[log.week] = log.fantasy_points
            if log.raw_stats and "position" in log.raw_stats:
                self._player_positions[log.player_id] = log.raw_stats["position"]

        self._ros_points = {}
        for gsis_id, weekly in pts_by_week.items():
            self._ros_points[gsis_id] = {}
            for from_week in range(1, 18):
                self._ros_points[gsis_id][from_week] = sum(
                    pts for wk, pts in weekly.items() if wk >= from_week
                )

    async def calculate_waiver_regrets(
        self, team_id: str, season_year: int = 2024
    ) -> List[Dict[str, Any]]:
        """Find top 3 FAs available each week that would have helped ROS.

        For each week, find the best available free agent (by ROS points)
        at a position where they would have outperformed the team's worst
        rostered player at that position for the rest of season.
        """
        from app.models import (
            LeagueWeeklyRoster, WaiverWireAvailability,
        )
        await self._load_lookups(season_year)

        regrets = []

        for week in range(1, 15):  # Weeks 1-14 (need ROS runway)
            # Get team's roster
            result = await self.session.execute(
                select(LeagueWeeklyRoster)
                .where(LeagueWeeklyRoster.team_id == team_id)
                .where(LeagueWeeklyRoster.week == week)
                .where(LeagueWeeklyRoster.season_year == season_year)
                .order_by(LeagueWeeklyRoster.created_at.desc())
                .limit(1)
            )
            roster = result.scalar_one_or_none()
            if not roster:
                continue

            # Build team's ROS points by position
            roster_data = roster.roster_snapshot.get("players", [])
            team_ros_by_pos: Dict[str, List[tuple]] = {}
            for player in roster_data:
                yahoo_id = str(player["player_id"])
                gsis_id = self._player_maps.get(yahoo_id)
                if not gsis_id or gsis_id not in self._ros_points:
                    continue
                pos = player.get("position", "")
                if pos in ("BN", "IR", "K", "DEF", ""):
                    continue
                ros = self._ros_points[gsis_id].get(week, 0)
                team_ros_by_pos.setdefault(pos, []).append((yahoo_id, ros))

            # Get worst rostered player per position
            worst_by_pos = {}
            for pos, players in team_ros_by_pos.items():
                worst = min(players, key=lambda x: x[1])
                worst_by_pos[pos] = worst  # (yahoo_id, ros_points)

            # Get available FAs this week
            result = await self.session.execute(
                select(WaiverWireAvailability)
                .where(WaiverWireAvailability.week == week)
                .where(WaiverWireAvailability.ownership_percentage <= 30)
            )
            fa_players = result.scalars().all()

            for fa in fa_players:
                fa_yahoo_id = str(fa.player_id)
                gsis_id = self._player_maps.get(fa_yahoo_id)
                if not gsis_id or gsis_id not in self._ros_points:
                    continue

                fa_ros = self._ros_points[gsis_id].get(week, 0)
                fa_pos = self._player_positions.get(gsis_id, "")
                if fa_pos not in worst_by_pos:
                    continue

                worst_yahoo_id, worst_ros = worst_by_pos[fa_pos]
                delta = fa_ros - worst_ros

                if delta > 20:  # Only meaningful misses
                    fa_name = self._player_names.get(fa_yahoo_id, f"Player #{fa_yahoo_id}")
                    worst_name = self._player_names.get(
                        worst_yahoo_id, f"Player #{worst_yahoo_id}"
                    )
                    regrets.append({
                        "week": week,
                        "fa_player_id": fa_yahoo_id,
                        "fa_name": fa_name,
                        "fa_ros_points": fa_ros,
                        "fa_position": fa_pos,
                        "fa_ownership_pct": fa.ownership_percentage,
                        "replaced_player_id": worst_yahoo_id,
                        "replaced_name": worst_name,
                        "replaced_ros_points": worst_ros,
                        "points_delta": delta,
                    })

        # Deduplicate: keep best week per FA player
        best_per_fa: Dict[str, Dict] = {}
        for r in regrets:
            key = r["fa_player_id"]
            if key not in best_per_fa or r["points_delta"] > best_per_fa[key]["points_delta"]:
                best_per_fa[key] = r

        deduped = sorted(best_per_fa.values(), key=lambda x: x["points_delta"], reverse=True)
        return deduped[:3]

    def generate_narrative(self, regret: Dict[str, Any]) -> str:
        """Generate narrative for waiver regret."""
        return (
            f"Week {regret['week']}: {regret['fa_name']} ({regret['fa_position']}) "
            f"was available ({regret['fa_ownership_pct']}% owned) and scored "
            f"{regret['fa_ros_points']:.1f} pts ROS. Your {regret['replaced_name']} "
            f"only managed {regret['replaced_ros_points']:.1f} pts ROS. "
            f"That's {regret['points_delta']:.1f} points you missed out on."
        )


class StartSitRegretCalculator:
    """Calculate start/sit regret metrics with lineup optimization."""
    
    def __init__(self, session: AsyncSession, roster_requirements: Dict[str, Any]):
        self.session = session
        self.optimizer = LineupOptimizer(roster_requirements)
    
    async def calculate_weekly_startsit_regret(
        self, team_id: str, week: int, season_year: int = 2024
    ) -> Dict[str, Any]:
        """Calculate lineup optimization regret for a team in a specific week.
        
        Compares actual lineup points to optimal lineup points
        given the team's full roster.
        """
        from app.models import LeagueWeeklyRoster, PlayerMap, NflGameLog
        
        # Get team's roster for the week (most recent entry)
        result = await self.session.execute(
            select(LeagueWeeklyRoster)
            .where(LeagueWeeklyRoster.team_id == team_id)
            .where(LeagueWeeklyRoster.week == week)
            .where(LeagueWeeklyRoster.season_year == season_year)
            .order_by(LeagueWeeklyRoster.created_at.desc())
            .limit(1)
        )
        roster = result.scalar_one_or_none()
        
        if not roster:
            logger.warning(f"No roster found for team {team_id}, week {week}, season {season_year}")
            return {}
        
        roster_data = roster.roster_snapshot.get("players", [])
        
        # Get player mappings
        result = await self.session.execute(select(PlayerMap))
        player_maps = {row.yahoo_id: row.gsis_id for row in result.scalars().all()}
        
        # Get game logs for this week and season
        result = await self.session.execute(
            select(NflGameLog)
            .where(NflGameLog.week == week)
            .where(NflGameLog.season_year == season_year)
        )
        week_logs = result.scalars().all()
        
        # Create player points lookup
        player_week_points = {log.player_id: log.fantasy_points for log in week_logs}
        
        # Build roster with fantasy points
        team_players = []
        for player in roster_data:
            yahoo_id = str(player["player_id"])
            gsis_id = player_maps.get(yahoo_id)

            if not gsis_id:
                continue

            points = player_week_points.get(gsis_id, 0)

            team_players.append({
                "player_id": yahoo_id,
                "name": player.get("name", ""),
                "eligible_positions": player.get("eligible_positions", []),
                "actual_position": player.get("selected_position", "BN"),
                "points": points,
                "is_starter": player.get("selected_position", "BN") != "BN"
            })
        
        # Calculate actual points
        actual_points = sum(p["points"] for p in team_players if p["is_starter"])
        
        # Optimize lineup using LineupOptimizer
        optimal_result = self.optimizer.optimize_lineup(team_players, week)
        optimal_points = optimal_result["optimal_points"]
        
        # Compare lineups
        comparison = self.optimizer.compare_lineups(team_players, optimal_result)

        # Build specific swap details: which bench player should replace which starter
        swaps = []
        should_bench_ids = comparison.get("should_bench", set())
        should_start_ids = comparison.get("should_start", set())

        # Map player_id -> player info for quick lookup
        player_by_id = {p["player_id"]: p for p in team_players}

        benched_list = sorted(
            [player_by_id[pid] for pid in should_bench_ids if pid in player_by_id],
            key=lambda p: p["points"],
        )
        started_list = sorted(
            [player_by_id[pid] for pid in should_start_ids if pid in player_by_id],
            key=lambda p: p["points"],
            reverse=True,
        )

        for bench_player, start_player in zip(benched_list, started_list):
            swaps.append({
                "bench_player_id": bench_player["player_id"],
                "bench_player_name": bench_player.get("name", ""),
                "bench_player_points": bench_player["points"],
                "bench_position": bench_player.get("actual_position", ""),
                "start_player_id": start_player["player_id"],
                "start_player_name": start_player.get("name", ""),
                "start_player_points": start_player["points"],
                "swap_delta": start_player["points"] - bench_player["points"],
            })

        return {
            "actual_points": actual_points,
            "optimal_points": optimal_points,
            "points_delta": optimal_points - actual_points,
            "comparison": comparison,
            "swaps": swaps,
            "team_players": team_players
        }
    
    def generate_narrative(self, regret: Dict[str, Any], week: int) -> str:
        """Generate narrative for start/sit regret spotlight card."""
        comparison = regret.get("comparison", {})
        swaps = regret.get("swaps", [])

        if comparison.get("improvement_percentage", 0) > 20:
            severity = "Brutal"
        elif comparison.get("improvement_percentage", 0) > 10:
            severity = "Costly"
        else:
            severity = "Minor"

        if swaps:
            top_swap = swaps[0]
            narrative = (
                f"Week {week}: {severity} lineup decision. "
                f"You started {top_swap['bench_player_name']} "
                f"({top_swap['bench_player_points']:.1f} pts) over "
                f"{top_swap['start_player_name']} "
                f"({top_swap['start_player_points']:.1f} pts) on your bench. "
                f"That's {top_swap['swap_delta']:.1f} points left on the table."
            )
            if len(swaps) > 1:
                narrative += f" ({len(swaps)} total swaps would have helped.)"
            return narrative

        return (
            f"Week {week}: {severity} lineup decision. Your starters scored "
            f"{regret['actual_points']:.1f} points, but the optimal lineup "
            f"would have scored {regret['optimal_points']:.1f} points. "
            f"You left {regret['points_delta']:.1f} points on the bench "
            f"({comparison.get('improvement_percentage', 0):.1f}% improvement)."
        )


class RegretEngine:
    """Main regret engine orchestrator."""
    
    def __init__(self, session: AsyncSession, roster_requirements: Dict[str, Any] = {}):
        self.session = session
        self.draft_calculator = DraftRegretCalculator(session)
        self.waiver_calculator = WaiverRegretCalculator(session)
        self.startsit_calculator = StartSitRegretCalculator(session, roster_requirements)
    
    async def calculate_all_regrets(self, team_id: str) -> Dict[str, Any]:
        """Calculate all regret metrics for a team."""
        logger.info(f"Calculating all regrets for team {team_id}")

        # Draft regret (season-long)
        draft_regrets = await self.draft_calculator.calculate_draft_regret(team_id)

        # Waiver regret (season-long: best FA misses)
        waiver_regrets = await self.waiver_calculator.calculate_waiver_regrets(team_id)

        # Weekly start/sit regrets
        weekly_regrets = {}
        for week in range(1, 18):
            startsit_regret = await self.startsit_calculator.calculate_weekly_startsit_regret(
                team_id, week
            )
            if startsit_regret:
                weekly_regrets[week] = {"startsit_regret": startsit_regret}

        return {
            "team_id": team_id,
            "draft_regrets": draft_regrets,
            "waiver_regrets": waiver_regrets,
            "weekly_regrets": weekly_regrets,
        }