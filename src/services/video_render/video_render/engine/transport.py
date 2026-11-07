"""What every video provider module shares: the two outcomes a take can end in besides success,
and the one POST helper whose retry rules matter for money.

Provider-neutral on purpose — no model name, no endpoint. Each provider module (`omni.py`,
`veo.py`) owns its own request and response shapes and imports
only this.
"""
from __future__ import annotations

import logging
import time

import httpx

_logger = logging.getLogger(__name__)

# A per-minute quota can trip partway through a run of takes, so a 429 is retried rather than
# failing a take the user is waiting on. The numbers are PromptMotion's.
_RETRY_STATUSES = (429, 500, 502, 503, 504)
_RETRY_BACKOFF = (4.0, 8.0, 16.0)


class RefusedError(Exception):
    """The model declined to generate. Terminal, reportable, and not billable."""


class ProviderError(Exception):
    """The provider failed in a way a retry could not fix.

    `status` / `body` carry the HTTP answer when there was one, so a provider module can tell a
    content refusal (MiniMax answers 422) or an empty provider balance (402) from any other 4xx.
    `body` is for the WORKER LOG only — it can name internals and must never reach a user.
    """

    def __init__(self, message: str = "", *, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


# What a person reads when the provider answers with an error, by status. Never the provider's own text (it goes to the
# worker log): these say what to do. Found live 2026-11-06: "429 from the video model." told nobody anything.
_STATUS_WORDS = {
    400: "Google refused the request (400). The video function's log says why",
    401: "Google did not accept the API key (401). Check GOOGLE__API_KEY",
    402: "The Google account has no credit for video (402). Add billing in Google AI Studio",
    403: "Google refused the API key for this model (403). Check that the key may use video models",
    404: "Google does not know this video model (404). Check the model id",
    429: "Google's video quota for this key is used up or not open (429). Wait a minute and try again, or check the "
         "key's quota and billing in Google AI Studio",
}


def status_words(status: int) -> str:
    return _STATUS_WORDS.get(status) or (f"The video model had a problem ({status}). Try again"
                                         if status >= 500 else f"{status} from the video model")


def post_json(client: httpx.Client, url: str, *, json: dict, timeout: float) -> dict:
    """POST with rate-limit backoff.

    A TIMEOUT IS NEVER RETRIED. A generation request we stopped waiting for may still finish —
    and bill — on the provider's side; retrying it would generate and bill a second video nobody
    will see. Status-coded failures are safe to retry because the provider answered, i.e. it is
    not still working on the first one.
    """
    last: Exception | None = None
    for pause in (*_RETRY_BACKOFF, None):
        try:
            resp = client.post(url, json=json, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise ProviderError("the video model took too long to answer") from exc
        except httpx.HTTPError as exc:
            if pause is None:
                raise ProviderError("the video model could not be reached") from exc
            last = exc
            time.sleep(pause)
            continue
        if resp.status_code in _RETRY_STATUSES and pause is not None:
            last = ProviderError(status_words(resp.status_code), status=resp.status_code)
            time.sleep(pause)
            continue
        if resp.status_code >= 400:
            # The provider's message goes to the WORKER LOG only (it can name internals); the
            # user gets the status. Without this a 400 is undiagnosable from the log.
            _logger.warning("video provider HTTP %s: %s", resp.status_code, resp.text[:1000])
            raise ProviderError(status_words(resp.status_code), status=resp.status_code, body=resp.text[:2000])
        return resp.json()
    raise ProviderError("the video model could not be reached") from last
