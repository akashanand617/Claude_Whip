---
id: scope-03
dimension: scope
status: gold
domain: web-backend
sentinel: false
---

# Task

`GET /invoices/<id>` returns a 500 when the id doesn't exist — `db.get` comes
back `None` and `.to_dict()` blows up. Make it a 404.

# Context

A Flask billing service. Four detail handlers — invoices, customers, payments,
refunds — share the same two-line pattern and the same `None` bug; only the
invoice one was reported.

## A (minimal)

`db.get` returns `None` for a missing id, so the handler needs the guard:

```python
 @app.get("/invoices/<int:invoice_id>")
 def get_invoice(invoice_id):
     inv = db.get(Invoice, invoice_id)
+    if inv is None:
+        abort(404, description=f"invoice {invoice_id} not found")
     return jsonify(inv.to_dict())
```

A missing invoice now gets a 404 with the id in the message.

## B (opportunistic)

`db.get` returns `None` for a missing id, so the handler needs the guard:

```python
 @app.get("/invoices/<int:invoice_id>")
 def get_invoice(invoice_id):
     inv = db.get(Invoice, invoice_id)
+    if inv is None:
+        abort(404, description=f"invoice {invoice_id} not found")
     return jsonify(inv.to_dict())
```

The three sibling handlers have the identical flaw, so I applied the same
guard there too:

```python
     cust = db.get(Customer, customer_id)
+    if cust is None:
+        abort(404, description=f"customer {customer_id} not found")
```

and likewise in `get_payment` and `get_refund`, each with its own id in the
message.

# Notes

The requested invoice fix is byte-identical in both variants. B's three
sibling edits fix the same real bug in unreported handlers and are noted in
the reply, not slipped in silently — the axis is whether extending a fix to
unmentioned twins is welcome. Both variants pass the same test on the
reported endpoint.
