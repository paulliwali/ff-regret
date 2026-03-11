# Yahoo OAuth Setup Guide

Follow these steps to connect your Yahoo Fantasy Football account to the Regret Engine.

## Step 1: Create Yahoo Developer Account

1. Go to: https://developer.yahoo.com/
2. Sign in with your Yahoo account
3. If you don't have a developer account, create one (it's free)

## Step 2: Create a Yahoo App

1. Go to: https://developer.yahoo.com/apps/create/
2. Fill in the required fields:
   - **Application Name**: Fantasy Football Regret Engine
   - **Application Type**: Web Application
   - **Description**: Personal fantasy football regret analysis tool
   - **Callback Domain/DNS**: Leave blank for now
   - **Callback URL**: `https://api.login.yahoo.com/oauth2/request_auth`
3. Click "Create App"
4. Copy your **Consumer Key** and **Consumer Secret**

## Step 3: Get Access Tokens

Run the setup script to get your access tokens:

```bash
uv run python scripts/setup_yahoo_auth.py
```

You'll be prompted to:
1. Enter your Consumer Key
2. Enter your Consumer Secret (hidden input)
3. Follow the Yahoo authorization link in your browser
4. Copy the generated tokens

## Step 4: Update .env File

Update your `.env` file with the credentials:

```env
# Yahoo Fantasy API (replace with your actual values)
YAHOO_CONSUMER_KEY=your_consumer_key_here
YAHOO_CONSUMER_SECRET=your_consumer_secret_here
YAHOO_ACCESS_TOKEN=your_access_token_here
YAHOO_ACCESS_TOKEN_SECRET=your_access_token_secret_here

# Find your league ID and add it
YAHOO_LEAGUE_ID=your_league_id_here
YAHOO_GAME_ID=nfl
SEASON_YEAR=2025
```

## Step 5: Find Your League ID

To find your Yahoo League ID:

1. Go to your Yahoo Fantasy Football league page
2. Look at the URL in your browser
3. Find the number after `/nfl/` and before `/league/`
4. Example: `https://football.fantasysports.yahoo.com/nfl/123456/league/789012`
   - League ID: `789012`

## Step 6: Test the Connection

Run the test script to verify everything works:

```bash
uv run python scripts/test_yahoo_connection.py
```

This will:
- ✓ Test your OAuth credentials
- ✓ Connect to your league
- ✓ Display league info (name, teams, scoring type)
- ✓ Test fetching draft results

## Troubleshooting

### "Invalid OAuth credentials"
- Double-check your Consumer Key and Secret
- Make sure you copied the tokens correctly
- Tokens may expire - re-run the setup script

### "League not found"
- Verify your League ID is correct
- Make sure you're using the right game ID (usually "nfl")
- Check that you have access to the league

### "Authentication failed"
- Your tokens may have expired
- Re-run: `uv run python scripts/setup_yahoo_auth.py`

## Next Steps

Once your connection is working, you can:

```bash
# Initialize league data in the database
uv run python scripts/initialize_data.py
```

This will fetch and store:
- League configuration (scoring rules, roster requirements)
- Draft results
- Weekly rosters
- Waiver wire availability
