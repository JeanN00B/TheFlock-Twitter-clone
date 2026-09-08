"""Sanitized errors exposed by the tweet application boundary."""


class TweetValidationError(Exception):
    """Invalid public input represented only by field names."""

    def __init__(self, fields: set[str] | dict[str, object]) -> None:
        allowed = {"text", "page_size", "cursor", "tweet_id", "body", "feed", "username"}
        names = set(fields)
        if not names or not names <= allowed:
            raise ValueError("invalid tweet validation fields")
        self.fields = {field: "invalid" for field in names}
        super().__init__(self.fields)


class InvalidFeedCursor(TweetValidationError):
    """Invalid opaque feed boundary without exposing its contents."""

    def __init__(self) -> None:
        super().__init__({"cursor"})


class TweetNotFound(Exception):
    """The active tweet does not exist."""


class TweetForbidden(Exception):
    """The actor does not own the active tweet."""
