"""Agent Consensus for ZAP - voting-based response aggregation."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from zap.identity import DID


@dataclass
class Query:
    """A consensus query."""

    id: str
    content: str
    submitter: DID
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(cls, content: str, submitter: DID) -> Query:
        """Create a new query with auto-generated ID."""
        id_hash = hashlib.blake2b(
            f"{content}:{submitter}:{time.time()}".encode(),
            digest_size=32,
        ).hexdigest()
        return cls(id=id_hash, content=content, submitter=submitter)


@dataclass
class Response:
    """A response to a consensus query."""

    id: str
    query_id: str
    content: str
    responder: DID
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0
    signature: bytes = b""

    @classmethod
    def create(
        cls,
        query_id: str,
        content: str,
        responder: DID,
        confidence: float = 1.0,
    ) -> Response:
        """Create a new response with auto-generated ID."""
        id_hash = hashlib.blake2b(
            f"{query_id}:{content}:{responder}:{time.time()}".encode(),
            digest_size=32,
        ).hexdigest()
        return cls(
            id=id_hash,
            query_id=query_id,
            content=content,
            responder=responder,
            confidence=confidence,
        )


@dataclass
class Vote:
    """A vote for a response."""

    voter: DID
    response_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConsensusResult:
    """Result of a consensus check."""

    response: Response | None
    votes: int
    total_voters: int
    confidence: float


@dataclass
class ConsensusConfig:
    """Configuration for agent consensus."""

    threshold: float = 0.5  # Required vote fraction
    min_responses: int = 1  # Minimum responses before consensus check
    min_votes: int = 3  # Minimum votes before consensus check
    timeout_secs: int = 60  # Query timeout


class AgentConsensus:
    """
    Agent Consensus Engine.

    Implements a voting-based consensus mechanism for AI agent responses.
    Agents submit responses to queries, and other agents vote on them.
    Consensus is reached when a response has majority votes.

    Example:
        >>> consensus = AgentConsensus()
        >>>
        >>> # Submit a query
        >>> query = Query.create("What is 2+2?", agent_did)
        >>> consensus.submit_query(query)
        >>>
        >>> # Submit responses
        >>> response = Response.create(query.id, "4", agent_did)
        >>> consensus.submit_response(response)
        >>>
        >>> # Vote for responses
        >>> consensus.vote(query.id, response.id, voter_did)
        >>>
        >>> # Check for consensus
        >>> result = consensus.try_consensus(query.id)
        >>> if result.response:
        ...     print(f"Consensus: {result.response.content}")
    """

    def __init__(self, config: ConsensusConfig | None = None):
        self.config = config or ConsensusConfig()
        self._queries: dict[str, Query] = {}
        self._responses: dict[str, dict[str, Response]] = {}  # query_id -> {response_id -> response}
        self._votes: dict[str, dict[str, list[DID]]] = {}  # query_id -> {response_id -> voters}
        self._finalized: dict[str, str] = {}  # query_id -> response_id

    def submit_query(self, query: Query) -> None:
        """Submit a new query for consensus."""
        if query.id in self._queries:
            raise ValueError(f"Query already exists: {query.id}")

        self._queries[query.id] = query
        self._responses[query.id] = {}
        self._votes[query.id] = {}

    def submit_response(self, response: Response) -> None:
        """Submit a response to a query."""
        if response.query_id not in self._queries:
            raise ValueError(f"Query not found: {response.query_id}")

        if response.query_id in self._finalized:
            raise ValueError(f"Query already finalized: {response.query_id}")

        self._responses[response.query_id][response.id] = response
        self._votes[response.query_id][response.id] = []

    def vote(self, query_id: str, response_id: str, voter: DID) -> None:
        """Cast a vote for a response."""
        if query_id not in self._queries:
            raise ValueError(f"Query not found: {query_id}")

        if query_id in self._finalized:
            raise ValueError(f"Query already finalized: {query_id}")

        if response_id not in self._responses.get(query_id, {}):
            raise ValueError(f"Response not found: {response_id}")

        voters = self._votes[query_id][response_id]
        if any(str(v) == str(voter) for v in voters):
            raise ValueError(f"Already voted: {voter}")

        voters.append(voter)

    def try_consensus(self, query_id: str) -> ConsensusResult:
        """Try to reach consensus on a query."""
        if query_id not in self._queries:
            raise ValueError(f"Query not found: {query_id}")

        # Already finalized?
        if query_id in self._finalized:
            response_id = self._finalized[query_id]
            response = self._responses[query_id][response_id]
            votes = len(self._votes[query_id][response_id])
            total = self._count_total_voters(query_id)
            return ConsensusResult(
                response=response,
                votes=votes,
                total_voters=total,
                confidence=votes / total if total > 0 else 0.0,
            )

        responses = self._responses.get(query_id, {})
        votes = self._votes.get(query_id, {})

        # Check minimum responses
        if len(responses) < self.config.min_responses:
            return ConsensusResult(
                response=None,
                votes=0,
                total_voters=0,
                confidence=0.0,
            )

        # Count total voters
        total_voters = self._count_total_voters(query_id)
        if total_voters < self.config.min_votes:
            return ConsensusResult(
                response=None,
                votes=0,
                total_voters=total_voters,
                confidence=0.0,
            )

        # Find response with most votes
        vote_counts = {
            resp_id: len(voters) for resp_id, voters in votes.items()
        }

        if not vote_counts:
            return ConsensusResult(
                response=None,
                votes=0,
                total_voters=total_voters,
                confidence=0.0,
            )

        best_response_id = max(vote_counts, key=vote_counts.get)  # type: ignore
        best_votes = vote_counts[best_response_id]
        confidence = best_votes / total_voters

        # Check if threshold reached
        if confidence >= self.config.threshold:
            self._finalized[query_id] = best_response_id
            return ConsensusResult(
                response=responses[best_response_id],
                votes=best_votes,
                total_voters=total_voters,
                confidence=confidence,
            )

        return ConsensusResult(
            response=None,
            votes=best_votes,
            total_voters=total_voters,
            confidence=confidence,
        )

    def is_finalized(self, query_id: str) -> bool:
        """Check if a query has reached consensus."""
        return query_id in self._finalized

    def get_result(self, query_id: str) -> ConsensusResult | None:
        """Get the consensus result for a finalized query."""
        if query_id not in self._finalized:
            return None
        return self.try_consensus(query_id)

    def _count_total_voters(self, query_id: str) -> int:
        """Count unique voters for a query."""
        all_voters: set[str] = set()
        for voters in self._votes.get(query_id, {}).values():
            for voter in voters:
                all_voters.add(str(voter))
        return len(all_voters)
