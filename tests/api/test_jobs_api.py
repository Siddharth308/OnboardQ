import io
import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select

from app.db.models import Job
from app.services import jobs as job_service

MESSY_CSV = (
    b"Emp ID;Full Name;Work Email;Joined;Salary\n"
    b"E001;Asha Rao;asha@acme.com;03/04/21;1000\n"
    b"E002;Ravi Kumar;ravi@acme.com;2021-04-05;\n"
    b"E003;Meera Iyer;meera@acme.com;2020-11-01;2500\n"
)


def _file(name: str, data: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, data, "text/csv")}


async def _upload(client: AsyncClient, name: str = "staff.csv", data: bytes = MESSY_CSV) -> str:
    response = await client.post("/v1/jobs", files=_file(name, data))
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


async def test_upload_returns_202_and_job_is_processed_in_background(client: AsyncClient) -> None:
    response = await client.post("/v1/jobs", files=_file("staff.csv", MESSY_CSV))

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "UPLOADED"  # state at the moment the response was built
    uuid.UUID(body["id"])

    # The background task has run by the time the request returns, so the final state is visible.
    final = (await client.get(f"/v1/jobs/{body['id']}")).json()
    assert final["status"] == "AWAITING_REVIEW"
    assert final["row_count"] == 3
    assert final["column_count"] == 5


async def test_profile_endpoint_returns_column_stats(client: AsyncClient) -> None:
    job_id = await _upload(client)

    response = await client.get(f"/v1/jobs/{job_id}/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["delimiter"] == ";"
    assert body["encoding"] == "utf-8"
    columns = {c["name"]: c for c in body["columns"]}
    assert columns["Salary"]["null_rate"] == round(1 / 3, 4)
    assert columns["Joined"]["inferred_type"] == "string"
    assert columns["Full Name"]["sample_values"] == ["A***", "R***", "M***"]
    assert columns["Work Email"]["sample_values"][0] == "***@acme.com"


async def test_profile_and_mapping_never_contain_raw_pii(client: AsyncClient) -> None:
    job_id = await _upload(client)

    profile = await client.get(f"/v1/jobs/{job_id}/profile")
    mapping = await client.get(f"/v1/jobs/{job_id}/mapping")

    for response in (profile, mapping):
        assert "asha@acme.com" not in response.text
        assert "Asha Rao" not in response.text


async def test_mapping_endpoint_returns_rule_proposal(client: AsyncClient) -> None:
    job_id = await _upload(client)

    response = await client.get(f"/v1/jobs/{job_id}/mapping")

    assert response.status_code == 200
    body = response.json()
    assert body["target_schema"] == "employee_equity"
    assert body["method"] == "rules"
    by_target = {m["target_field"]: m for m in body["mappings"]}
    assert by_target["employee_id"]["source_columns"] == ["Emp ID"]
    assert by_target["email"]["source_columns"] == ["Work Email"]
    assert by_target["date_of_joining"]["source_columns"] == ["Joined"]
    assert "options_granted" in body["missing_required_fields"]
    assert "Full Name" in body["unmapped_source_columns"]


async def test_list_schemas(client: AsyncClient) -> None:
    response = await client.get("/v1/schemas")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()]
    assert "employee_equity" in names


async def test_unknown_target_schema_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/jobs",
        files=_file("staff.csv", MESSY_CSV),
        data={"target_schema": "no_such_schema"},
    )

    assert response.status_code == 422
    assert response.json()["title"] == "Unknown target schema"


async def test_get_job_returns_status(client: AsyncClient) -> None:
    job_id = await _upload(client)

    response = await client.get(f"/v1/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == job_id


async def test_upload_xlsx(client: AsyncClient) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Staff #", "Grant"])
    sheet.append(["S-1", 100])
    buffer = io.BytesIO()
    workbook.save(buffer)

    job_id = await _upload(client, "staff.xlsx", buffer.getvalue())

    job = (await client.get(f"/v1/jobs/{job_id}")).json()
    assert job["status"] == "AWAITING_REVIEW"
    assert job["column_count"] == 2


async def test_unsupported_extension_returns_problem_json_415(client: AsyncClient) -> None:
    response = await client.post("/v1/jobs", files=_file("payload.exe", b"MZ"))

    assert response.status_code == 415
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 415
    assert body["instance"] == "/v1/jobs"


async def test_oversized_upload_is_rejected_with_413(client: AsyncClient) -> None:
    too_big = b"a,b\n" + b"1,2\n" * (11 * 1024 * 1024 // 4)

    response = await client.post("/v1/jobs", files=_file("big.csv", too_big))

    assert response.status_code == 413
    assert response.json()["status"] == 413


async def test_bad_target_schema_returns_422_without_echoing_input(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/jobs",
        files=_file("staff.csv", MESSY_CSV),
        data={"target_schema": "Drop Table; --"},
    )

    assert response.status_code == 422
    assert response.json()["title"] == "Validation failed"
    assert "Drop Table" not in response.text  # errors do not echo the submitted value


async def test_unknown_job_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_empty_csv_is_marked_failed_with_reason(client: AsyncClient) -> None:
    job_id = await _upload(client, "empty.csv", b"")

    job = (await client.get(f"/v1/jobs/{job_id}")).json()
    assert job["status"] == "FAILED"
    assert job["error_reason"] == "The file has no header row."

    assert (await client.get(f"/v1/jobs/{job_id}/profile")).status_code == 409
    assert (await client.get(f"/v1/jobs/{job_id}/mapping")).status_code == 409


async def test_rerunning_pipeline_on_finished_job_is_a_no_op(
    client: AsyncClient, app: FastAPI
) -> None:
    job_id = await _upload(client)
    job_uuid = uuid.UUID(job_id)

    async with app.state.session_factory() as session:
        before = (await session.execute(select(Job).where(Job.id == job_uuid))).scalar_one()
        updated_before = before.updated_at

    await job_service.run_pipeline(
        job_uuid, app.state.settings, app.state.session_factory, app.state.registry
    )

    async with app.state.session_factory() as session:
        after = (await session.execute(select(Job).where(Job.id == job_uuid))).scalar_one()
    assert after.status == "AWAITING_REVIEW"
    assert after.updated_at == updated_before
