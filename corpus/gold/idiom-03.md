---
id: idiom-03
dimension: idiom
status: gold
domain: web-backend
sentinel: false
---

# Task

Add a `fetchWithRetry(url, attempts)` wrapper to `api-client.js` that retries
a failed request with a delay between tries.

# Context

The service file is written entirely in `.then()` promise chains with
anonymous `function` expressions — there is no `async`/`await` anywhere in
it. A `delay(ms)` helper returning a promise and a `RETRY_MS` constant
already exist in the file.

## A (conform)

A `.then()` chain, matching the rest of `api-client.js`:

```js
function fetchWithRetry(url, attempts) {
    return fetch(url)
        .then(function (res) {
            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }
            return res.json();
        })
        .catch(function (err) {
            if (attempts <= 1) {
                throw err;
            }
            return delay(RETRY_MS).then(function () {
                return fetchWithRetry(url, attempts - 1);
            });
        });
}
```

Slots in beside the other request helpers with no other changes to the file.

## B (modernize)

`async`/`await` with `try`/`catch`:

```js
async function fetchWithRetry(url, attempts) {
    try {
        const res = await fetch(url);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        return await res.json();
    } catch (err) {
        if (attempts <= 1) {
            throw err;
        }
        await delay(RETRY_MS);
        return fetchWithRetry(url, attempts - 1);
    }
}
```

The file's first `async` function — callers still receive a promise, so
existing `.then()` call sites are unaffected.

# Notes

Identical semantics, verified path by path: network failures and non-ok
statuses both route to the retry branch (B's `return await res.json()` keeps
JSON parse failures retryable, matching A's chain), the last attempt
rethrows, and both return the parsed body. Only the promise idiom differs;
both are correct professional JS.
