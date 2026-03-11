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
        and calculate the delta in season points.
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
        
        # Get player mappings
        result = await self.session.execute(select(PlayerMap))
        player_maps = {row.yahoo_id: row.gsis_id for row in result.scalars().all()}
        
        # Get all NFL game logs for season
        result = await self.session.execute(select(NflGameLog))
        game_logs = result.scalars().all()
        
        # Calculate season points for each player
        player_season_points = {}
        for log in game_logs:
            player_id = log.player_id
            points = log.fantasy_points
            if player_id not in player_season_points:
                player_season_points[player_id] = 0
            player_season_points[player_id] += points
        
        regrets = []
        
        for pick in team_picks:
            yahoo_id = pick.player_id
            gsis_id = player_maps.get(yahoo_id)
            
            if not gsis_id:
                logger.warning(f"No GSIS ID found for Yahoo ID {yahoo_id}")
                continue
            
            drafted_points = player_season_points.get(gsis_id, 0)
            
            # Find players drafted within ±3 picks
            nearby_picks = [
                p for p in all_picks 
                if abs(p.overall_pick - pick.overall_pick) <= 3 and p.player_id != yahoo_id
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
                        "drafted_player_points": drafted_points,
                        "missed_player_id": nearby_yahoo_id,
                        "missed_player_points": nearby_points,
                        "points_delta": delta,
                        "pick_distance": abs(nearby_pick.overall_pick - pick.overall_pick)
                    })
        
        # Sort by delta and keep top 3
        regrets.sort(key=lambda x: x["points_delta"], reverse=True)
        return regrets[:3]
    
    def generate_narrative(self, regret: Dict[str, Any]) -> str:
        """Generate narrative for draft regret spotlight card."""
        return (
            f"With the {regret['overall_pick']}th pick in round {regret['round']}, "
            f"you left {regret['points_delta']:.1f} points on the table. "
            f"The player you missed scored {regret['missed_player_points']:.1f} points, "
            f"while your pick managed {regret['drafted_player_points']:.1f} points."
        )


class WaiverRegretCalculator:
    """Calculate waiver wire regret metrics for each team."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def calculate_weekly_waiver_regret(
        self, team_id: str, week: int, season_year: int = 2024
    ) -> List[Dict[str, Any]]:
        """Calculate top 3 waiver regrets for a team in a specific week.
        
        Identifies players on bench or waivers that would have outperformed
        the actual starters.
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
            return []
        
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
        
        # Separate starters and bench players
        starters = []
        bench = []
        
        for player in roster_data:
            yahoo_id = player["player_id"]
            gsis_id = player_maps.get(yahoo_id)
            
            if not gsis_id:
                continue
            
            points = player_week_points.get(gsis_id, 0)
            
            if player.get("selected_position", "BN") != "BN":
                starters.append({
                    "player_id": yahoo_id,
                    "name": player.get("name", ""),
                    "position": player.get("position", ""),
                    "points": points
                })
            else:
                bench.append({
                    "player_id": yahoo_id,
                    "name": player.get("name", ""),
                    "position": player.get("position", ""),
                    "points": points
                })
        
        regrets = []
        
        # Find bench players who would have outperformed starters at same position
        for starter in starters:
            starter_position = starter["position"]
            starter_points = starter["points"]
            
            # Find best bench player at same position
            position_matches = [
                p for p in bench 
                if p["position"] == starter_position and p["points"] > starter_points
            ]
            
            if position_matches:
                best_match = max(position_matches, key=lambda x: x["points"])
                delta = best_match["points"] - starter_points
                
                regrets.append({
                    "starter_id": starter["player_id"],
                    "starter_name": starter["name"],
                    "starter_points": starter_points,
                    "benched_id": best_match["player_id"],
                    "benched_name": best_match["name"],
                    "benched_points": best_match["points"],
                    "points_delta": delta,
                    "position": starter_position
                })
        
        # Sort by delta and keep top 3
        regrets.sort(key=lambda x: x["points_delta"], reverse=True)
        return regrets[:3]
    
    def generate_narrative(self, regret: Dict[str, Any], week: int) -> str:
        """Generate narrative for waiver regret spotlight card."""
        return (
            f"Week {week}: You started {regret['starter_name']} "
            f"({regret['starter_points']:.1f} pts) at {regret['position']} "
            f"when {regret['benched_name']} ({regret['benched_points']:.1f} pts) "
            f"sat on your bench, costing you {regret['points_delta']:.1f} points."
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
            yahoo_id = player["player_id"]
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
        
        return {
            "actual_points": actual_points,
            "optimal_points": optimal_points,
            "points_delta": optimal_points - actual_points,
            "comparison": comparison,
            "team_players": team_players
        }
    
    def generate_narrative(self, regret: Dict[str, Any], week: int) -> str:
        """Generate narrative for start/sit regret spotlight card."""
        comparison = regret.get("comparison", {})
        
        if comparison.get("improvement_percentage", 0) > 20:
            severity = "Brutal"
        elif comparison.get("improvement_percentage", 0) > 10:
            severity = "Costly"
        else:
            severity = "Minor"
        
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
        
        # Weekly regrets (waiver and start/sit)
        weekly_regrets = {}
        for week in range(1, 18):  # 17 weeks
            waiver_regrets = await self.waiver_calculator.calculate_weekly_waiver_regret(team_id, week)
            startsit_regret = await self.startsit_calculator.calculate_weekly_startsit_regret(team_id, week)
            
            if waiver_regrets or startsit_regret:
                weekly_regrets[week] = {
                    "waiver_regrets": waiver_regrets,
                    "startsit_regret": startsit_regret
                }
        
        return {
            "team_id": team_id,
            "draft_regrets": draft_regrets,
            "weekly_regrets": weekly_regrets
        }