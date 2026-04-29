# ESP32 and relay top-up order

```text
+----------------+-----------------------------+
| field          | value                       |
+----------------+-----------------------------+
| record_type    | bill                        |
| bill_id        | bill.house_mesh_esp32_topup |
| alias          | house_mesh_esp32_topup      |
| purchased_on   | 2026-02-06                  |
| total_eur      | 22                          |
| counterparty   | 深圳市海云电子                     |
| project        | House Mesh                  |
| related_entity | Foundry                     |
+----------------+-----------------------------+
```

## Line Items

```text
+---+---------------------+-----+----------+----------+
| # | item                | qty | unit_eur | line_eur |
+---+---------------------+-----+----------+----------+
| 1 | ESP32-C3 dev boards | 2   | 8        | 16       |
| 2 | relay modules       | 1   | 6        | 6        |
+---+---------------------+-----+----------+----------+
|   | TOTAL               |     |          | 22       |
+---+---------------------+-----+----------+----------+
```

## Notes

A later top-up when the first batch stopped being enough for experiments and replacements.
