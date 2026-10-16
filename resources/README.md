# Postal-code reference data

`postal_code3_tw_source.json` is the Taiwan 3-digit postal-code CodeSystem
published by the Ministry of Health and Welfare TW Core Implementation Guide.
Its metadata identifies Chunghwa Post as the data owner and contains all 368
administrative areas.

- Source: https://twcore.mohw.gov.tw/ig/twcore/0.1.1/CodeSystem-postal-code3-tw.json
- Bundled source version: 2015-01-22
- Downloaded: 2026-10-16

The application uses this file only as a non-persisted fallback when a mail
record has no postal code. Explicitly entered postal codes always take priority.
