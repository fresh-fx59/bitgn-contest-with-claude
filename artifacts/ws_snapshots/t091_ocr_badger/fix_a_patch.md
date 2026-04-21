# Fix A — PCM search case-fold retry wrapper

Apply to `src/bitgn_contest_agent/adapter/pcm_tracing.py`.

## Imports block

Add `re` import and the `_LOWER_TOKEN_RE` regex constant:

```python
import re
```

```python
# A single alphanumeric token, all-lowercase, optionally with _ or -. Used
# to gate the case-fold retry in search() — we only retry patterns that
# look like a proper-noun the LLM fed us in lowercase (e.g. "badger").
# Anything with regex metacharacters, spaces, or mixed case is left alone.
_LOWER_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
```

## Replace search() method (around line 173)

```python
def search(self, req: "pcm_pb2.SearchRequest") -> Any:
    resp = self._traced(req, self._runtime.search)
    # PROD PCM search is case-sensitive substring match. Agents often
    # feed entity aliases in lowercase ("badger") while workspace
    # content is title-cased ("Badger"), producing zero-hit false
    # negatives. Retry once with Title case when the pattern is a
    # single lowercase proper-noun-shaped token; merge results.
    pattern = getattr(req, "pattern", "") or ""
    if list(getattr(resp, "matches", []) or []):
        return resp
    if not _LOWER_TOKEN_RE.match(pattern):
        return resp
    titled = pattern[:1].upper() + pattern[1:]
    retry_req = type(req)()
    if hasattr(retry_req, "CopyFrom"):
        retry_req.CopyFrom(req)
    else:
        for attr in ("root", "pattern", "limit"):
            if hasattr(req, attr):
                setattr(retry_req, attr, getattr(req, attr))
    retry_req.pattern = titled
    retry_resp = self._traced(retry_req, self._runtime.search)
    return retry_resp if list(getattr(retry_resp, "matches", []) or []) else resp
```
