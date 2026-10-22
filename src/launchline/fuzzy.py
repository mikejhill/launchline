"""Fuzzy substring matching with scoring.

Provides :class:`FuzzyMatcher`, which scores how well a short query
string matches against a longer candidate string using an ordered,
non-contiguous character-matching algorithm with bonuses for runs and
word-boundary alignment.
"""

from __future__ import annotations


class FuzzyMatcher:
    """Fuzzy substring matching with scoring.

    All methods are static; the class serves as a logical namespace.
    """

    @staticmethod
    def score(query: str, candidate: str) -> int | None:
        """Score how well *query* fuzzy-matches *candidate*.

        All characters in *query* must appear in *candidate* in order (not
        necessarily contiguous).  Higher scores indicate better matches, with
        bonuses for contiguous runs and word-boundary alignment.

        Args:
            query: The search string.
            candidate: The string to match against.

        Returns:
            An integer score (higher is better), or ``None`` if the query does
            not match the candidate.
        """
        if not query:
            return 0

        query_lower = query.lower()
        candidate_lower = candidate.lower()

        # A complete prefix consists of one contiguous run.
        if candidate_lower.startswith(query_lower):
            boundary_count = (
                0
                if query_lower.isalnum()
                else sum(char in " -_./\\" for char in query_lower[:-1])
            )
            return 3 * len(query_lower) + 1 + 3 * boundary_count

        start = 0
        previous_end = -1
        score = 0
        for char in query_lower:
            index = candidate_lower.find(char, start)
            if index < 0:
                return None
            score += 1
            if index == previous_end:
                score += 2
            if index == 0 or candidate_lower[index - 1] in " -_./\\":
                score += 3
            start = index + 1
            previous_end = start
        return score
