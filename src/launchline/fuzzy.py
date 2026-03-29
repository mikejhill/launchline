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

        q_idx = 0
        score = 0
        prev_match_idx = -2

        for c_idx, c_char in enumerate(candidate_lower):
            if q_idx < len(query_lower) and c_char == query_lower[q_idx]:
                score += 1
                # Contiguous character bonus
                if c_idx == prev_match_idx + 1:
                    score += 2
                # Word-boundary bonus
                if c_idx == 0 or candidate_lower[c_idx - 1] in " -_./\\":
                    score += 3
                prev_match_idx = c_idx
                q_idx += 1

        if q_idx < len(query_lower):
            return None

        return score
