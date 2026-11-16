import json

from custops.export_service import write_crm_contacts, write_subject_export
from custops.serializers import customer_record, export_bundle


def test_customer_record_has_full_profile(store):
    rec = customer_record(store.get_customer("cus_1002"))
    assert rec["customer_id"] == "cus_1002" and rec["display_name"] == "Lucía Fernández"
    assert {"email", "phone", "date_of_birth", "tax_reference", "country", "segment", "currency", "created_at"} <= set(rec)


def test_subject_export_bundle(store, tmp_path):
    path = write_subject_export(store, "cus_1009", tmp_path)
    bundle = json.loads(path.read_text())
    assert bundle["schema"] == "custops.subject-export/1"
    assert bundle["customer"]["customer_id"] == "cus_1009"
    assert bundle["transaction_count"] == len(bundle["transactions"]) == len(store.transactions_for("cus_1009"))
    assert export_bundle(store.get_customer("cus_1009"), [], "2025-01-01T00:00:00Z")["transaction_count"] == 0


def test_crm_contact_export(store, tmp_path):
    import csv
    path = write_crm_contacts(store, tmp_path, segment="smb")
    rows = list(csv.DictReader(path.open()))
    assert path.name == "crm-contacts-smb.csv" and len(rows) == 4 and "tax_reference" in rows[0] and rows[0]["segment"] == "smb"
