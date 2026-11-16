# CRM contact export (`export-crm`)

The CRM (HubSpot) is the system of record for customer contact details, so the nightly import job
picks up `data/exports/crm/crm-contacts.csv`: one row per customer with the full profile
(`serializers.customer_record`), optionally filtered by segment. The CRM import maps the columns it
knows and ignores the rest; the file is produced on the custops box and collected by the CRM
connector over the internal file share.
