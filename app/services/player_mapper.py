import polars as pl
from typing import Dict, List, Tuple, Optional
import re
from rapidfuzz import fuzz, process
import logging

logger = logging.getLogger(__name__)


class PlayerMapper:
    """Handles mapping between Yahoo player IDs and NFL GSIS IDs using multiple strategies."""

    def __init__(self):
        self._yahoo_to_nfl_map: Dict[str, str] = {}
        self._nfl_to_yahoo_map: Dict[str, str] = {}
        self._name_to_gsis_map: Dict[str, str] = {}
        self._name_to_yahoo_map: Dict[str, str] = {}

    def normalize_name(self, name: str) -> str:
        """Normalize player name for fuzzy matching.

        - Remove common suffixes (Jr., III, etc.)
        - Remove special characters
        - Convert to lowercase
        - Strip extra whitespace
        """
        name = name.strip()
        
        # Remove suffixes like "Jr.", "II", "III", "IV", "Sr."
        suffixes = r'\b(Jr\.?|II|III|IV|Sr\.?|MD|PhD)\b\.?'
        name = re.sub(suffixes, '', name, flags=re.IGNORECASE)
        
        # Remove special characters except hyphens and apostrophes
        name = re.sub(r"[^\w\-'\s]", '', name)
        
        # Remove periods (from initials)
        name = name.replace('.', '')
        
        # Convert to lowercase and strip
        name = name.lower().strip()
        
        # Collapse multiple spaces
        name = re.sub(r'\s+', ' ', name)
        
        return name

    def build_name_index(self, player_ids: pl.DataFrame) -> None:
        """Build indexes for name-based lookup from NFL player data.

        Expected columns in player_ids:
        - gsis_id: NFLverse ID
        - full_name: Player full name (may be None)
        - first_name: First name
        - last_name: Last name
        """
        logger.info("Building name index from NFL player data")
        
        for row in player_ids.iter_rows(named=True):
            gsis_id = row.get("gsis_id")
            
            if not gsis_id:
                continue
            
            # Try full name first
            full_name = row.get("full_name")
            if full_name:
                normalized = self.normalize_name(full_name)
                self._name_to_gsis_map[normalized] = gsis_id
            
            # Also build from first_name + last_name
            first_name = row.get("first_name")
            last_name = row.get("last_name")
            if first_name and last_name:
                combined = f"{first_name} {last_name}"
                normalized = self.normalize_name(combined)
                if normalized not in self._name_to_gsis_map:
                    self._name_to_gsis_map[normalized] = gsis_id

    def map_yahoo_player_to_gsis(
        self, 
        yahoo_id: str, 
        yahoo_name: str,
        nfl_player_ids: Optional[pl.DataFrame] = None
    ) -> Tuple[Optional[str], float]:
        """Map a Yahoo player to NFL GSIS ID with confidence score.

        Returns:
            Tuple of (gsis_id, confidence_score)
            - gsis_id: The matched NFL player ID (None if no match)
            - confidence_score: 1.0 for exact ID match, 0.7-0.9 for fuzzy match
        """
        # Strategy 1: Direct ID lookup if available
        if yahoo_id in self._yahoo_to_nfl_map:
            return self._yahoo_to_nfl_map[yahoo_id], 1.0
        
        # Strategy 2: Fuzzy name matching
        if yahoo_name:
            return self._fuzzy_match_name(yahoo_name)
        
        return None, 0.0

    def _fuzzy_match_name(self, yahoo_name: str) -> Tuple[Optional[str], float]:
        """Perform fuzzy name matching against NFL player index.

        Returns:
            Tuple of (gsis_id, confidence_score)
        """
        normalized_yahoo = self.normalize_name(yahoo_name)
        
        if not normalized_yahoo:
            return None, 0.0
        
        # Direct lookup first (exact normalized match)
        if normalized_yahoo in self._name_to_gsis_map:
            return self._name_to_gsis_map[normalized_yahoo], 0.95
        
        # Fuzzy matching using rapidfuzz
        # Get top 3 matches and check if any are good enough
        matches = process.extract(
            normalized_yahoo,
            list(self._name_to_gsis_map.keys()),
            limit=3,
            scorer=fuzz.token_sort_ratio
        )
        
        if not matches:
            return None, 0.0
        
        # Check if the best match is good enough
        best_match, score, _ = matches[0]
        
        # Score thresholds
        if score >= 95:
            confidence = 0.95
        elif score >= 90:
            confidence = 0.85
        elif score >= 85:
            confidence = 0.75
        elif score >= 80:
            confidence = 0.60
        else:
            return None, 0.0
        
        gsis_id = self._name_to_gsis_map[best_match]
        logger.debug(f"Fuzzy match: '{yahoo_name}' -> '{best_match}' (score: {score}, confidence: {confidence})")
        
        return gsis_id, confidence

    def batch_map_yahoo_players(
        self,
        yahoo_players: List[Dict[str, str]],
        nfl_player_ids: pl.DataFrame
    ) -> List[Dict[str, any]]:
        """Batch map multiple Yahoo players to NFL IDs.

        Args:
            yahoo_players: List of dicts with 'player_id' and 'name' keys
            nfl_player_ids: DataFrame with NFL player data including GSIS IDs and names

        Returns:
            List of dicts with mapping results including confidence scores
        """
        # Build name index first
        self.build_name_index(nfl_player_ids)
        
        results = []
        unmatched = []
        
        for player in yahoo_players:
            yahoo_id = player.get("player_id", "")
            yahoo_name = player.get("name", "")
            
            gsis_id, confidence = self.map_yahoo_player_to_gsis(yahoo_id, yahoo_name, nfl_player_ids)
            
            result = {
                "yahoo_id": yahoo_id,
                "gsis_id": gsis_id,
                "full_name": yahoo_name,
                "match_confidence": confidence
            }
            
            if gsis_id:
                results.append(result)
            else:
                unmatched.append(player)
                results.append(result)  # Still add to maintain list order
        
        logger.info(f"Mapped {len([r for r in results if r['gsis_id']])}/{len(yahoo_players)} players successfully")
        if unmatched:
            logger.warning(f"Could not match {len(unmatched)} players")
            for player in unmatched[:5]:  # Log first 5 unmatched
                logger.debug(f"Unmatched: {player.get('name', 'Unknown')} (ID: {player.get('player_id', 'Unknown')})")
        
        return results

    def match_confidence_label(self, confidence: float) -> str:
        """Get a human-readable label for match confidence."""
        if confidence >= 0.95:
            return "Exact"
        elif confidence >= 0.85:
            return "High"
        elif confidence >= 0.75:
            return "Medium"
        elif confidence >= 0.60:
            return "Low"
        else:
            return "None"