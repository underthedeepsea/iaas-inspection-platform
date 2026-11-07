"""Bounded serial synthetic queries; no arbitrary blocking-I/O cancellation."""
import math
from time import monotonic, sleep
from . import mapping_simulation as sim
from .mapping_services import MappingInputError

QUERY_TIMEOUT_SECONDS = 2
MAX_ATTEMPTS = 2
SECONDS_PER_REQUEST = 5
RETRY_DELAY_SECONDS = 1
_DEFAULT_WAIT = object()


class QueryBudgetExceeded(MappingInputError):
    """The shared fetch time/call allowance cannot admit more work."""


class QueryBudget:
    def __init__(self, planned_requests, *, clock=None):
        if type(planned_requests) is not int or planned_requests < 0:
            raise MappingInputError('Planned request count must be a nonnegative integer.')
        self.clock = monotonic if clock is None else clock
        self.planned_requests = planned_requests
        self.calls = 0
        self.call_limit = MAX_ATTEMPTS * planned_requests
        self.started_at = self.clock()
        self.deadline = self.started_at + SECONDS_PER_REQUEST * planned_requests

    def check_complete(self):
        # Completion exactly at the total allowance is legal; new work is not.
        if self.clock() > self.deadline:
            raise QueryBudgetExceeded('Synthetic fetch elapsed budget exceeded.')

    def enter_attempt(self):
        now = self.clock()
        if now >= self.deadline or self.calls >= self.call_limit:
            raise QueryBudgetExceeded('Synthetic fetch has no remaining query budget.')
        self.calls += 1
        return min(now + QUERY_TIMEOUT_SECONDS, self.deadline)

    def wait(self, error):
        # Server-owned one-second retry delay leaves one second per request
        # after two full two-second attempts. Synthetic RetryAfter overrides it.
        delay = getattr(error, 'retry_after', None)
        if delay is None:
            delay = RETRY_DELAY_SECONDS
        try:
            valid_delay = type(delay) in (int, float) and math.isfinite(delay) and delay >= 0
        except OverflowError:
            valid_delay = False
        if not valid_delay:
            raise MappingInputError('Invalid synthetic RetryAfter delay.')
        if self.calls >= self.call_limit or delay >= self.deadline - self.clock():
            raise QueryBudgetExceeded('Synthetic retry wait exceeds remaining budget.')
        sleep(delay)
        self.check_complete()


class QueryAttemptsExhausted(MappingInputError):
    def __init__(self, cause, attempts):
        self.attempts = attempts
        self.cause_code = 'TIMEOUT' if isinstance(cause, sim.SimulatedTimeout) else '429'
        super().__init__(f'Synthetic query failed after {attempts} attempts: {self.cause_code}.')


def execute(spec, *, retry_wait=_DEFAULT_WAIT, clock=None, attempt_fixture=None, budget=None):
    """Use the fetch budget, or a one-request allowance for standalone calls.

    An explicit retry_wait callback remains supported for existing offline
    callers. Its elapsed time still consumes the same budget.
    """
    if retry_wait is not _DEFAULT_WAIT and not callable(retry_wait):
        raise MappingInputError('Explicit retry scheduling callback required.')
    if budget is None:
        budget = QueryBudget(1, clock=clock)
    elif clock is not None and clock is not budget.clock:
        raise MappingInputError('A query must use its shared budget clock.')
    clock = budget.clock
    for attempt in range(1, MAX_ATTEMPTS + 1):
        deadline = budget.enter_attempt()
        try:
            raw = sim.query(spec, deadline=deadline, clock=clock,
                            attempt_fixture=attempt_fixture)
            # Also reject adapters that return late without checking cooperatively.
            if clock() >= deadline:
                raise sim.SimulatedTimeout('Synthetic query returned after its deadline.')
            budget.check_complete()
            return raw
        except (sim.SimulatedTimeout, sim.SimulatedRateLimited) as exc:
            budget.check_complete()
            if attempt == MAX_ATTEMPTS:
                raise QueryAttemptsExhausted(exc, attempt) from exc
            if retry_wait is _DEFAULT_WAIT:
                budget.wait(exc)
            else:
                retry_wait(attempt, exc)
                budget.check_complete()
