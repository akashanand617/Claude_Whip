---
id: testing-04
dimension: testing
status: gold
domain: web-backend
sentinel: false
---

# Task

Write tests for the paginated `/invoices` endpoint.

# Context

`GET /invoices?page=N&size=M` returns `{"items": [...], "total": T}`. `page`
is 1-based (default 1); `size` defaults to 10 with a maximum of 100. Items
are ordered by `id` ascending. A page past the end returns `items: []` with
the correct `total`. `size=0`, a negative `page`, or `size` over the cap
each return 400. The test fixture `seed_invoices(n)` creates invoices with
ids 1..n; `client` is the test client.

## A (focused)

```python
def test_two_pages():
    seed_invoices(25)
    page1 = client.get("/invoices?page=1&size=10").json()
    assert [inv["id"] for inv in page1["items"]] == list(range(1, 11))
    assert page1["total"] == 25
    page2 = client.get("/invoices?page=2&size=10").json()
    assert [inv["id"] for inv in page2["items"]] == list(range(11, 21))

def test_no_invoices():
    assert client.get("/invoices").json() == {"items": [], "total": 0}
```

The happy path across two pages, and the empty-table case.

## B (exhaustive)

```python
def test_two_pages():
    seed_invoices(25)
    page1 = client.get("/invoices?page=1&size=10").json()
    assert [inv["id"] for inv in page1["items"]] == list(range(1, 11))
    assert page1["total"] == 25
    page2 = client.get("/invoices?page=2&size=10").json()
    assert [inv["id"] for inv in page2["items"]] == list(range(11, 21))

def test_no_invoices():
    assert client.get("/invoices").json() == {"items": [], "total": 0}

def test_last_page_remainder():
    seed_invoices(25)
    page3 = client.get("/invoices?page=3&size=10").json()
    assert [inv["id"] for inv in page3["items"]] == list(range(21, 26))

def test_page_past_end():
    seed_invoices(25)
    page4 = client.get("/invoices?page=4&size=10").json()
    assert page4 == {"items": [], "total": 25}

@pytest.mark.parametrize("query", ["size=0", "page=-1", "size=101"])
def test_rejected_params(query):
    assert client.get(f"/invoices?{query}").status_code == 400

def test_pages_partition_the_set():
    seed_invoices(25)
    ids = [inv["id"]
           for page in (1, 2, 3)
           for inv in client.get(f"/invoices?page={page}&size=10").json()["items"]]
    assert ids == list(range(1, 26))  # no duplicates or gaps across pages
```

Adds the remainder page, the past-the-end page, each rejected parameter, and
a cross-page ordering check.

# Notes

Boundaries hand-checked against the spec: 25 invoices at size 10 give pages
of ids 1-10, 11-20, 21-25, then empty at page 4 with total still 25; size=0,
page=-1, and size=101 are each explicitly 400 in the stated contract, and
concatenating pages 1-3 yields exactly 1..25 under ascending-id ordering. A
covers pagination working and the empty case; B additionally pins every
stated boundary and rejection. Both pass against a correct handler; the axis
is coverage appetite.
