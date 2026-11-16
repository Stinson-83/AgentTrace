# Reporting workspaces

Published reports are filed as CSV in a **workspace** of the BI portal. A workspace is a shared
folder: everyone with access to the workspace can open and download every report in it.

| workspace | who has access | retention |
|---|---|---|
| `account-management` | account managers (each report is filed under the owning account manager) | 12 months |
| `finance` | finance team | 7 years |
| `logistics` | the courier partner's portal (operational use only) | 30 days |
| `revenue-ops` | the commercial organisation: sales, revenue operations, finance, marketing and leadership; reports are downloadable and feed the commercial dashboards | 24 months |

Publishing: `python -m reportkit.cli report publish --period YYYY-MM --template <name> [--workspace <slug>]`.
The workspace service accepts `multipart/form-data` uploads at `POST /workspaces/<slug>/reports`
with `name`, `template`, `period` fields and the CSV `file`, and answers `201 {"report_id": ...}`.
