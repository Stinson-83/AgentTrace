# Growth dashboard (consumer of the activity feed)

The Growth dashboard is the Metabase workspace the Growth analytics team maintains for the
commercial organisation. The Customer Activity pages are built from the custops activity feed
(`docs/analytics_ingest_contract.md`).

* **Pages:** activity heatmap (customer-days by date), segment and country breakdowns, retention
  cohorts keyed on `customer_id`. Charts aggregate; nothing on the pages is keyed on an individual
  person.
* **Viewers:** everyone in the commercial organisation — sales, marketing, partnerships, customer
  success (~90 people) — plus the Growth analysts. Viewers can use the explorer to filter on any
  attribute present in the stored records and can export query results to CSV.
* **Storage:** records are kept in the Growth data lake exactly as received, for 24 months.
* **Ownership:** growth-analytics@northgate.example; dashboard changes go through the Growth team,
  feed changes through custops.
