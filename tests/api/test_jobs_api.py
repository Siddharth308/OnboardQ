import io
import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select

from app.db.models import Job

MESSY_CSV = (
    b"Emp ID;Full Name;Work Email;Joined;Salary\n"
    b"E001;Asha Rao;asha@acme.com;03/04/21;1000\n"
    b"E002;Ravi Kumar;ravi@acme.com;2021-04-05;\n"
    b"E003;Meera Iyer;meera@acme.com;2020-11-01;2500\n"
)


def _csv(name: str, data: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, data, "text/csv")}


async def test_upload_csv_returns_201_and_job(client: AsyncClient) -> None:
    response = await client.post("/v1/jobs", files=_csv("staff.csv", MESSY_CSV))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PROFILING"
    assert body["filename"] == "staff.csv"
    assert body["row_count"] == 3
    assert body["column_count"] == 5
    uuid.UUID(body["id"])  # raises if not a valid id


async def test_profile_endpoint_returns_column_stats(client: AsyncClient) -> None:
    job = (await client.post("/v1/jobs", files=_csv("staff.csv", MESSY_CSV))).json()

    response = await client.get(f"/v1/jobs/{job['id']}/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["delimiter"] == ";"
    assert body["encoding"] == "utf-8"
    columns = {c["name"]: c for c in body["columns"]}
    assert columns["Salary"]["null_rate"] == round(1 / 3, 4)
    assert columns["Joined"]["inferred_type"] == "string"
    assert columns["Full Name"]["sample_values"] == ["A***", "R***", "M***"]
    assert columns["Work Email"]["sample_values"][0] == "***@acme.com"


async def test_profile_never_contains_raw_pii(client: AsyncClient) -> None:
    job = (await client.post("/v1/jobs", files=_csv("staff.csv", MESSY_CSV))).json()

    response = await client.get(f"/v1/jobs/{job['id']}/profile")

    assert "asha@acme.com" not in response.text
    assert "Asha Rao" not in response.text


async def test_get_job_returns_status(client: AsyncClient) -> None:
    job = (await client.post("/v1/jobs", files=_csv("staff.csv", MESSY_CSV))).json()

    response = await client.get(f"/v1/jobs/{job['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == job["id"]


async def test_upload_xlsx(client: AsyncClient) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Staff #", "Grant"])
    sheet.append(["S-1", 100])
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = await client.post(
        "/v1/jobs",
        files={
            "file": (
                "staff.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["column_count"] == 2


async def test_unsupported_extension_returns_problem_json_415(client: AsyncClient) -> None:
    response = await client.post("/v1/jobs", files=_csv("payload.exe", b"MZ"))

    assert response.status_code == 415
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 415
    assert body["instance"] == "/v1/jobs"


async def test_oversized_upload_is_rejected_with_413(client: AsyncClient) -> None:
    # The fixture app uses the default 10 MB limit. A 11 MB body exceeds it.
    too_big = b"a,b\n" + b"1,2\n" * (11 * 1024 * 1024 // 4)

    response = await client.post("/v1/jobs", files=_csv("big.csv", too_big))

    assert response.status_code == 413
    assert response.json()["status"] == 413


async def test_bad_target_schema_returns_422_without_echoing_input(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/jobs",
        files=_csv("staff.csv", MESSY_CSV),
        data={"target_schema": "Drop Table; --"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Validation failed"
    assert "Drop Table" not in response.text  # errors do not echo the submitted value


async def test_unknown_job_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_empty_csv_is_rejected_and_job_is_marked_failed(
    client: AsyncClient, app: FastAPI
) -> None:
    response = await client.post("/v1/jobs", files=_csv("empty.csv", b""))

    assert response.status_code == 422
    assert response.json()["title"] == "Empty file"
    async with app.state.session_factory() as session:
        job = (await session.execute(select(Job))).scalar_one()
    assert job.status == "FAILED"
    assert job.error_reason is not None

    profile = await client.get(f"/v1/jobs/{job.id}/profile")
    assert profile.status_code == 409
    assert profile.json()["status"] == 409
