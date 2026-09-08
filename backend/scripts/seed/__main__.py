"""Allow `python -m scripts.seed` from the backend directory."""

from .seed import main

if __name__ == "__main__":
    raise SystemExit(main())
