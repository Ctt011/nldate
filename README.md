# nldate

Parse natural-language date strings into `datetime.date` objects.

```python
from datetime import date
from nldate import parse

parse("today")                                  # date.today()
parse("tomorrow")                               # tomorrow
parse("yesterday")                              # yesterday
parse("next Tuesday")                           # next Tuesday after today
parse("last Friday")                            # most recent past Friday
parse("3 days from now")                        # 3 days after today
parse("2 weeks ago")                            # 2 weeks before today
parse("5 days before December 1st, 2025")       # date(2025, 11, 26)
parse("1 year and 2 months after yesterday")    # 1y2m after yesterday
parse("December 1, 2025")                       # date(2025, 12, 1)
parse("2025-12-01")                             # date(2025, 12, 1)
parse("12/01/2025")                             # date(2025, 12, 1)
```

The `today` parameter overrides the reference date for relative expressions:

```python
parse("next Tuesday", today=date(2026, 5, 13))  # date(2026, 5, 19)
```

## Development

```bash
uv sync
uv run pytest
uv run mypy src/
uv run ruff check
uv run ruff format --check
```

Built for DSC 190 Assignment 06.
