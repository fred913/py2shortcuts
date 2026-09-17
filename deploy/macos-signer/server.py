"""Authenticated asynchronous HTTP wrapper around macOS `shortcuts sign`."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import plistlib
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

MAX_REQUEST_BYTES = 64 * 1024 * 1024
SIGN_TIMEOUT_SECONDS = int(os.environ.get("PY2SCSIGN_TIMEOUT_SECONDS", "300"))
SIGN_ATTEMPTS = 3
TOKEN_FILE = Path(os.environ["PY2SCSIGN_TOKEN_FILE"])
SHORTCUTS_PATH = os.environ.get("PY2SCSIGN_SHORTCUTS_PATH", "/usr/bin/shortcuts")
API_TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()
logger = logging.getLogger("uvicorn.error")

if not API_TOKEN:
    raise RuntimeError("Signing token file is empty")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
signing_slots = asyncio.Semaphore(1)


async def run_command(*arguments: str) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=SIGN_TIMEOUT_SECONDS
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="shortcuts sign timed out",
        ) from None
    return process.returncode, stdout, stderr


async def read_request_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid Content-Length",
            ) from None
        if declared_length <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="empty request body",
            )
        if declared_length > MAX_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="workflow exceeds 64 MiB",
            )

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="workflow exceeds 64 MiB",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty request body",
        )
    return await asyncio.to_thread(b"".join, chunks)


def compile_binary_workflow(workflow: bytes) -> bytes:
    try:
        parsed = plistlib.loads(workflow)
    except plistlib.InvalidFileException:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid plist",
        ) from None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("WFWorkflowActions"), list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="not a Shortcuts workflow",
        )
    return plistlib.dumps(parsed, fmt=plistlib.FMT_BINARY, sort_keys=False)


@app.get("/health", response_class=Response)
async def health() -> Response:
    returncode, _, _ = await run_command(SHORTCUTS_PATH, "help", "sign")
    if returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="shortcuts CLI unavailable",
        )
    return Response(content=b"ok\n", media_type="text/plain")


@app.post("/v1/sign", response_class=Response)
async def sign_workflow(
    request: Request,
    authorization: str = Header(default=""),
) -> Response:
    expected = f"Bearer {API_TOKEN}"
    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    workflow = await read_request_body(request)
    binary_workflow = await asyncio.to_thread(compile_binary_workflow, workflow)
    started_at = time.monotonic()
    logger.info(
        "signing workflow: xml_bytes=%d binary_bytes=%d",
        len(workflow),
        len(binary_workflow),
    )

    async with signing_slots:
        directory = Path(
            await asyncio.to_thread(tempfile.mkdtemp, prefix="py2shortcuts-sign-")
        )
        try:
            input_path = directory / "input.wflow"
            output_path = directory / "output.shortcut"
            await asyncio.to_thread(input_path.write_bytes, binary_workflow)
            message = ""
            for attempt in range(1, SIGN_ATTEMPTS + 1):
                await asyncio.to_thread(output_path.unlink, missing_ok=True)
                returncode, _, stderr = await run_command(
                    SHORTCUTS_PATH,
                    "sign",
                    "--mode",
                    "anyone",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                )
                if returncode == 0:
                    break
                message = stderr.decode("utf-8", errors="replace").strip()
                retryable = "NSURLErrorDomain Code=500" in message
                if not retryable or attempt == SIGN_ATTEMPTS:
                    break
                delay = 2**attempt
                logger.warning(
                    "transient shortcuts sign failure on attempt %d/%d; retrying in %ds",
                    attempt,
                    SIGN_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)

            if returncode != 0:
                logger.error(
                    "shortcuts sign failed after %d attempts and %.1fs: %s",
                    attempt,
                    time.monotonic() - started_at,
                    message,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"shortcuts sign failed: {message}",
                )
            try:
                signed = await asyncio.to_thread(output_path.read_bytes)
            except FileNotFoundError:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="shortcuts sign did not create an output file",
                ) from None
        finally:
            await asyncio.to_thread(shutil.rmtree, directory, True)

    if not signed.startswith(b"AEA1"):
        logger.error("shortcuts sign returned a non-AEA1 file")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="invalid signed output",
        )
    logger.info(
        "signed workflow: output_bytes=%d elapsed_seconds=%.1f",
        len(signed),
        time.monotonic() - started_at,
    )
    return Response(content=signed, media_type="application/octet-stream")
