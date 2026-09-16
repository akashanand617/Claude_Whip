---
id: proactivity-03
dimension: proactivity
status: gold
domain: web-backend
sentinel: false
---

# Task

Add `created_at` to the invoice list response.

# Context

The invoice list endpoint serializes through `InvoiceListSerializer`. The
project has an API reference doc and a serializer test module; the request
names only the field.

## A (exact)

Added the field:

```python
class InvoiceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "customer_id", "amount_cents", "status",
                  "created_at"]
```

`GET /invoices` now includes `created_at` in each item, in the ISO-8601
format DRF uses for the project's other timestamp fields.

## B (collateral)

Added the field:

```python
class InvoiceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "customer_id", "amount_cents", "status",
                  "created_at"]
```

`GET /invoices` now includes `created_at` in each item. Along with it:

- `tests/test_serializers.py::test_invoice_list_created_at_iso` — asserts
  the field is present and parses with `datetime.fromisoformat`, so a
  future formatting change fails loudly.
- `docs/api.md` — `created_at` added to the invoice list response table
  with its type and an example value, next to the other timestamp fields.

# Notes

The serializer change is identical in both variants. B delivers a format
test and the API doc row unasked — actually written, not promised. The
axis is whether unrequested collateral is welcome; the requested artifact
and its correctness are held equal.
