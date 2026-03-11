"""Advanced lineup optimization algorithm for fantasy football."""

from typing import List, Dict, Any, Optional, Set
import logging

logger = logging.getLogger(__name__)


class LineupOptimizer:
    """Optimize fantasy football lineup given roster and scoring rules."""
    
    # Position eligibility rules (simplified for common formats)
    POSITION_TYPES = {
        "QB": ["QB"],
        "RB": ["RB", "FLEX"],
        "WR": ["WR", "FLEX"],
        "TE": ["TE", "FLEX"],
        "FLEX": ["RB", "WR", "TE"],
        "K": ["K"],
        "DEF": ["DEF"]
    }
    
    def __init__(self, roster_requirements: Dict[str, Any]):
        self.roster_requirements = self._parse_requirements(roster_requirements)
    
    def _parse_requirements(self, requirements: Dict[str, Any]) -> Dict[str, int]:
        """Parse roster requirements into position count dict.
        
        Example input: [{"position": "QB", "count": 1}, ...]
        Example output: {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}
        """
        requirements_dict = {}
        
        if isinstance(requirements, list):
            for req in requirements:
                position = req.get("position", "")
                count = req.get("count", 1)
                if position:
                    requirements_dict[position] = requirements_dict.get(position, 0) + count
        
        elif isinstance(requirements, dict):
            requirements_dict = requirements.copy()
        
        # Set defaults if not specified
        defaults = {
            "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1
        }
        for position, count in defaults.items():
            if position not in requirements_dict:
                requirements_dict[position] = count
        
        logger.info(f"Parsed roster requirements: {requirements_dict}")
        return requirements_dict
    
    def optimize_lineup(
        self,
        roster_players: List[Dict[str, Any]],
        week: int,
        bye_weeks: Dict[str, List[int]] = None,
        injury_status: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """Find optimal lineup from roster.
        
        Args:
            roster_players: List of players with fantasy points
            week: Week number
            bye_weeks: Dict mapping player IDs to bye weeks
            injury_status: Dict mapping player IDs to injury status
        
        Returns:
            Dict with optimal lineup details and comparison to actual
        """
        # Filter out unavailable players
        available_players = self._filter_available_players(
            roster_players, week, bye_weeks, injury_status
        )
        
        # Create position pools
        position_pools = self._create_position_pools(available_players)
        
        # Fill positions using greedy algorithm
        optimal_lineup = self._fill_positions(position_pools)
        
        # Calculate total points
        optimal_points = sum(p["points"] for p in optimal_lineup.values() if p is not None)
        
        return {
            "optimal_lineup": optimal_lineup,
            "optimal_points": optimal_points,
            "available_players": available_players,
            "position_pools": {k: len(v) for k, v in position_pools.items()}
        }
    
    def _filter_available_players(
        self,
        roster_players: List[Dict[str, Any]],
        week: int,
        bye_weeks: Dict[str, List[int]] = None,
        injury_status: Dict[str, str] = None
    ) -> List[Dict[str, Any]]:
        """Filter out players on bye or injured."""
        available = []
        
        for player in roster_players:
            player_id = player["player_id"]
            
            # Check bye week
            if bye_weeks and player_id in bye_weeks:
                if week in bye_weeks[player_id]:
                    logger.debug(f"  {player['name']} on bye week {week}")
                    continue
            
            # Check injury status
            if injury_status and player_id in injury_status:
                status = injury_status[player_id]
                if status in ["OUT", "IR", "DOUBTFUL"]:
                    logger.debug(f"  {player['name']} status: {status}")
                    continue
            
            available.append(player)
        
        return available
    
    def _create_position_pools(
        self, players: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Create pools of available players for each position."""
        pools = {
            "QB": [],
            "RB": [],
            "WR": [],
            "TE": [],
            "K": [],
            "DEF": [],
            "FLEX": []
        }
        
        for player in players:
            eligible_positions = player.get("eligible_positions", [])
            points = player["points"]
            
            # Add to appropriate pools based on eligibility
            for position in eligible_positions:
                if position in pools:
                    pools[position].append(player)
        
        # Sort each pool by points (descending)
        for position in pools:
            pools[position].sort(key=lambda x: x["points"], reverse=True)
        
        return pools
    
    def _fill_positions(
        self, position_pools: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """Fill roster positions using greedy algorithm."""
        lineup = {position: None for position in self.roster_requirements.keys()}
        used_players = set()
        
        # Fill positions in priority order
        # Strategy: Fill position-specific slots first, then FLEX
        position_order = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"]
        
        for position in position_order:
            if position not in self.roster_requirements:
                continue
            
            count = self.roster_requirements[position]
            
            for _ in range(count):
                # Find best available player for this position
                player = self._find_best_player(
                    position, position_pools, used_players, lineup
                )
                
                if player:
                    # Assign to position
                    if lineup[position] is None:
                        lineup[position] = player
                    else:
                        # Multiple players at this position (e.g., 2 RB slots)
                        # Store as list for this position
                        existing = lineup[position]
                        if not isinstance(existing, list):
                            lineup[position] = [existing]
                        lineup[position].append(player)
                    
                    used_players.add(player["player_id"])
                else:
                    logger.warning(f"Could not find player for {position}")
                    break
        
        return lineup
    
    def _find_best_player(
        self,
        position: str,
        position_pools: Dict[str, List[Dict[str, Any]]],
        used_players: Set[str],
        lineup: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Find best available player for a position slot."""
        # Get eligible positions for this slot
        eligible_positions = self.POSITION_TYPES.get(position, [position])
        
        # Find best unused player from eligible pools
        best_player = None
        best_points = -1
        
        for pool_position in eligible_positions:
            if pool_position not in position_pools:
                continue
            
            pool = position_pools[pool_position]
            
            for player in pool:
                if player["player_id"] in used_players:
                    continue
                
                # Don't use FLEX pool players for FLEX slots if they could be used elsewhere
                # (simplified logic - could be more sophisticated)
                
                if player["points"] > best_points:
                    best_points = player["points"]
                    best_player = player
        
        return best_player
    
    def compare_lineups(
        self,
        actual_lineup: List[Dict[str, Any]],
        optimal_lineup: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compare actual lineup to optimal lineup.
        
        Returns detailed analysis of differences and missed opportunities.
        """
        # Calculate actual points
        actual_points = sum(
            p["points"] for p in actual_lineup if p.get("is_starter", False)
        )
        
        # Get optimal lineup players
        optimal_players = []
        for position, player_data in optimal_lineup.items():
            if player_data is None:
                continue
            
            if isinstance(player_data, list):
                optimal_players.extend(player_data)
            else:
                optimal_players.append(player_data)
        
        optimal_points = optimal_lineup["optimal_points"]
        delta = optimal_points - actual_points
        
        # Find differences
        actual_starter_ids = {
            p["player_id"] for p in actual_lineup if p.get("is_starter", False)
        }
        optimal_starter_ids = {
            p["player_id"] for p in optimal_players
        }
        
        # Players started that should have been benched
        should_bench = actual_starter_ids - optimal_starter_ids
        
        # Players benched that should have started
        should_start = optimal_starter_ids - actual_starter_ids
        
        return {
            "actual_points": actual_points,
            "optimal_points": optimal_points,
            "points_delta": delta,
            "should_bench": should_bench,
            "should_start": should_start,
            "improvement_percentage": (delta / actual_points * 100) if actual_points > 0 else 0
        }