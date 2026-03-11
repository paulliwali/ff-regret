# Fantasy Football Regret Engine

An interactive web application for Yahoo Fantasy Football managers to visualize the "what-ifs" of their previous season.

## Features

- **Draft Regret**: See who you should have drafted instead
- **Waiver Regret**: Discover missed opportunities on the waiver wire
- **Start/Sit Regret**: Optimize your weekly lineup decisions
- **"The One That Got Away" Spotlight**: Narrative-driven cards telling the story of your worst decisions

## Tech Stack

- **Backend**: Python (FastAPI)
- **Database**: PostgreSQL / SQLite (for local development)
- **Data Processing**: Polars, nfl_data_py
- **Frontend**: HTMX + Tailwind (Dark Mode)

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for package management

### Installation

1. Clone the repository:
```bash
git clone <repo-url>
cd ff-regret
```

2. Install dependencies:
```bash
uv sync
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your Yahoo Fantasy API credentials
```

### Environment Variables

Create a `.env` file with the following:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/ff_regret
YAHOO_CONSUMER_KEY=your_consumer_key
YAHOO_CONSUMER_SECRET=your_consumer_secret
YAHOO_ACCESS_TOKEN=your_access_token
YAHOO_ACCESS_TOKEN_SECRET=your_access_token_secret
YAHOO_LEAGUE_ID=your_league_id
YAHOO_GAME_ID=nfl
SEASON_YEAR=2025
```

### Local Development

For local development, you can use SQLite instead of PostgreSQL:

```env
DATABASE_URL=sqlite+aiosqlite:///./ff_regret.db
```

### Running the Application

1. Start the FastAPI server:
```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

2. Access the API:
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Initializing Data

Run the data initialization script to fetch and store league data:

```bash
uv run python scripts/initialize_data.py
```

This will:
1. Fetch Yahoo Fantasy League data (draft, rosters, waiver wire)
2. Fetch NFL game logs and player data
3. Map Yahoo player IDs to NFL IDs
4. Calculate fantasy points
5. Store everything in the database

### Development

Run linting and type checking:

```bash
# Linting
uv run ruff check app/
uv run black app/

# Type checking
uv run mypy app/
```

## Railway Deployment

### Prerequisites

1. Install Railway CLI:
```bash
npm install -g @railway/cli
```

2. Login:
```bash
railway login
```

### Deployment Steps

1. Initialize Railway project:
```bash
railway init
```

2. Add PostgreSQL service:
```bash
railway add postgresql
```

3. Set environment variables:
```bash
railway variables set DATABASE_URL=$DATABASE_URL
railway variables set YAHOO_CONSUMER_KEY=$YAHOO_CONSUMER_KEY
railway variables set YAHOO_CONSUMER_SECRET=$YAHOO_CONSUMER_SECRET
railway variables set YAHOO_ACCESS_TOKEN=$YAHOO_ACCESS_TOKEN
railway variables set YAHOO_ACCESS_TOKEN_SECRET=$YAHOO_ACCESS_TOKEN_SECRET
railway variables set YAHOO_LEAGUE_ID=$YAHOO_LEAGUE_ID
```

4. Deploy:
```bash
railway up
```

5. Initialize data:
```bash
railway run python scripts/initialize_data.py
```

## Project Structure

```
ff-regret/
├── app/
│   ├── api/           # FastAPI endpoints
│   ├── models/        # SQLAlchemy models
│   ├── services/      # Business logic (Yahoo, NFL services)
│   ├── db/            # Database connection and session
│   ├── frontend/      # HTMX + Tailwind templates
│   ├── main.py        # FastAPI application
│   └── config.py      # Configuration
├── scripts/           # Data initialization scripts
├── tests/             # Test files
├── pyproject.toml     # Project dependencies
├── .env.example       # Environment variables template
└── PLAN.md           # Detailed project plan
```

## License

MIT
