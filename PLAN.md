# PLAN: UI Overhaul — Timeline-Centric Regret Dashboard

## Vision

Consolidate the three-pillar layout into a **timeline-first** design. The weekly timeline becomes the primary visualization, showing both start/sit and waiver regrets in context. Draft regret gets a full-width showcase. Matchup outcomes drive the color scale — regrets that cost wins are red, harmless ones are green.

## Changes

### 1. Remove Start/Sit Pillar Card

The weekly timeline already tells the start/sit story better — bar heights show magnitude, click-to-expand shows specific swaps. The standalone start/sit pillar card is redundant. Remove it.

### 2. Merge Waiver Regret into Weekly Timeline

Move waiver regrets into the timeline's click-to-expand detail. When a user clicks a week:
- Show start/sit swaps (already there)
- Show waiver misses for that week: "Player X was available (12% owned) and scored Y pts ROS"
- Visual distinction between the two types (e.g. swap icon vs magnifying glass icon)

Remove the standalone waiver pillar card.

### 3. Expand Draft Regret to Full Width

With only one pillar remaining, draft regret gets the full page width:
- Expand from top 3 to **top 5** draft picks
- Each pick gets a richer card:
  - Player headshot photos (Yahoo player image URL)
  - Season stats summary (total points, points per game, best week)
  - Draft context (round, pick number, who was picked nearby)
  - Narrative text
- Horizontal card layout using the full width

### 4. Matchup-Aware Color Scale

Replace the current intensity-based color scale (magnitude of points left) with a **matchup-context** color scale:

- **Red**: Regret cost you the win — optimal lineup would have won, but you lost
- **Yellow/Amber**: Regret existed but didn't change the outcome — you lost anyway (even optimal wouldn't have won) or you won despite the suboptimal lineup
- **Green**: Clean week — no significant regret, or you set the optimal lineup

This requires comparing:
- `actual_points + points_delta` (optimal score) vs `opponent_score` (from `league_matchups`)
- `actual_points` vs `opponent_score` (actual result)

Logic:
```
if actual_win:
    color = green  # won anyway, regret is harmless
elif actual_points + points_delta > opponent_score:
    color = red    # optimal lineup would have won — this cost you
else:
    color = yellow # lost either way, regret didn't matter
```

### 5. Cumulative W-L Record on Timeline

Add a running win-loss record above/below the weekly timeline bars:
- Show cumulative record as "W-L" text under each week (e.g. "3-1", "3-2", "4-2")
- Pull from `league_matchups` table
- Helps contextualize when regrets mattered most (losing streaks, playoff push)

## Implementation Order

1. Add matchup context to timeline API (`/api/team/{team_id}/weekly-timeline`)
2. Update timeline color scale to matchup-aware red/yellow/green
3. Add cumulative W-L record to timeline
4. Merge waiver regrets into timeline detail expand
5. Remove start/sit and waiver pillar cards
6. Expand draft regret to full-width with 5 picks, photos, stats
