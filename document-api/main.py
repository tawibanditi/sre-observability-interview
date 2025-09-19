import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
import magic
from config import get_settings
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from telemetry import increment_counter, init_observability, record_histogram_value

app = FastAPI(title="Document API", version="1.0.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UPLOADS_DIR = Path("/app/uploads")
UPLOADS_DIR.mkdir(exist_ok=True)

init_observability()

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    increment_counter("health_check_requests", 1)
    return {"status": "healthy", "service": "document-api"}


async def summarise_document_using_llm(file_path):
    """Summarise the document using a large language model."""
    
    # Track LLM processing start time
    start_time = time.time()
    
    try:
        # Call to real LLM API would go here - lets simulate with a sleep to fake the expensive LLM call
        await asyncio.sleep(10)
        
        # Calculate processing duration
        processing_time = time.time() - start_time
        
        # Track successful LLM processing
        increment_counter("llm_processing_total", 1, {"status": "success"})
        
        # Track LLM processing duration
        record_histogram_value("llm_processing_duration_seconds", processing_time)
        
        return "This is a summary of the document."
        
    except Exception as e:
        # Calculate processing duration even on failure
        processing_time = time.time() - start_time
        
        # Track failed LLM processing
        increment_counter("llm_processing_total", 1, {"status": "failed"})
        
        # Track LLM processing duration (even for failures)
        record_histogram_value("llm_processing_duration_seconds", processing_time)
        
        # Re-raise the exception
        raise


@app.put("/clients/{client_id}/upload-document")
async def upload_document(
    client_id: str, file: UploadFile = File(...), settings=Depends(get_settings)
):
    """Upload a document and store its metadata for a specific client."""
    file_path = None
    start_time = time.time()
    
    try:
        content = await file.read()
        file_size = len(content)
        file_type = magic.from_buffer(content, mime=True)

        # File validation metrics
        increment_counter("file_validation_total", 1, {
            "validation_type": "mime_type_check",
            "status": "passed"
        })
        
        # File size validation
        if file_size > 0:
            increment_counter("file_validation_total", 1, {
                "validation_type": "file_size_check",
                "status": "passed"
            })
        else:
            increment_counter("file_validation_total", 1, {
                "validation_type": "file_size_check",
                "status": "failed"
            })
        
        # Filename validation
        if file.filename and len(file.filename) > 0:
            increment_counter("file_validation_total", 1, {
                "validation_type": "filename_check",
                "status": "passed"
            })
        else:
            increment_counter("file_validation_total", 1, {
                "validation_type": "filename_check",
                "status": "failed"
            })

        # Active clients tracking
        increment_counter("active_clients_total", 1, {"client_id": client_id})
        
        # Document uploads by client
        increment_counter("document_uploads_by_client", 1, {"client_id": client_id})
        
        # File type distribution
        increment_counter("document_uploads_by_type", 1, {"file_type": file_type})
        
        # Document size distribution
        record_histogram_value("document_size_bytes", file_size, {"client_id": client_id})

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{client_id}_{timestamp}_{file.filename}"
        file_path = UPLOADS_DIR / safe_filename

        with open(file_path, "wb") as f:
            f.write(content)

        # Process with LLM
        summary = await summarise_document_using_llm(file_path)
        
        # Metadata completeness tracking
        increment_counter("metadata_completeness", 1, {
            "field": "summary",
            "status": "present"
        })
        
        # Track other metadata fields
        if file.filename:
            increment_counter("metadata_completeness", 1, {
                "field": "filename",
                "status": "present"
            })
        else:
            increment_counter("metadata_completeness", 1, {
                "field": "filename",
                "status": "missing"
            })
            
        if file.content_type:
            increment_counter("metadata_completeness", 1, {
                "field": "content_type",
                "status": "present"
            })
        else:
            increment_counter("metadata_completeness", 1, {
                "field": "content_type",
                "status": "missing"
            })
            
        if file_size > 0:
            increment_counter("metadata_completeness", 1, {
                "field": "file_size",
                "status": "present"
            })
        else:
            increment_counter("metadata_completeness", 1, {
                "field": "file_size",
                "status": "missing"
            })

        metadata = {
            "client_id": client_id,
            "filename": file.filename,
            "file_size": file_size,
            "file_type": file_type,
            "content_type": file.content_type,
            "file_path": str(file_path),
            "summary": summary,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.data_store_url}/clients/{client_id}/documents",
                json=metadata,
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"Failed to store metadata: {response.text}")
                # Document upload failure
                increment_counter("document_uploads_total", 1, {"status": "failed"})
                # HTTP error tracking
                increment_counter("http_errors_total", 1, {
                    "status_code": "500",
                    "endpoint": "/clients/{client_id}/upload-document",
                    "service": "data-store"
                })
                raise HTTPException(
                    status_code=500, detail="Failed to store document metadata"
                )

            stored_metadata = response.json()

        # Document upload success
        increment_counter("document_uploads_total", 1, {"status": "success"})
        
        # Client document count tracking
        increment_counter("client_document_count", 1, {"client_id": client_id})
        
        # API request success tracking
        increment_counter("api_requests_total", 1, {
            "endpoint": "/clients/{client_id}/upload-document",
            "method": "PUT",
            "status_code": "200"
        })
        
        logger.info(
            f"Successfully uploaded document: {file.filename} for client: {client_id}"
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": "Document uploaded successfully",
                "client_id": client_id,
                "document_id": stored_metadata["id"],
                "metadata": stored_metadata,
            },
        )

    except httpx.RequestError as e:
        logger.error(f"Error communicating with data-store: {str(e)}")
        # Document upload failure
        increment_counter("document_uploads_total", 1, {"status": "failed"})
        # API request failure tracking
        increment_counter("api_requests_total", 1, {
            "endpoint": "/clients/{client_id}/upload-document",
            "method": "PUT",
            "status_code": "503"
        })
        # HTTP error tracking
        increment_counter("http_errors_total", 1, {
            "status_code": "503",
            "endpoint": "/clients/{client_id}/upload-document",
            "service": "data-store"
        })
        # Exception tracking
        increment_counter("exceptions_total", 1, {
            "exception_type": "httpx.RequestError",
            "service": "document-api",
            "operation": "data_store_communication"
        })
        raise HTTPException(status_code=503, detail="Data store service unavailable")
    except Exception as e:
        logger.error(f"Error uploading document: {str(e)}")
        # Document upload failure
        increment_counter("document_uploads_total", 1, {"status": "failed"})
        # API request failure tracking
        increment_counter("api_requests_total", 1, {
            "endpoint": "/clients/{client_id}/upload-document",
            "method": "PUT",
            "status_code": "500"
        })
        # HTTP error tracking
        increment_counter("http_errors_total", 1, {
            "status_code": "500",
            "endpoint": "/clients/{client_id}/upload-document",
            "service": "document-api"
        })
        # Exception tracking
        increment_counter("exceptions_total", 1, {
            "exception_type": type(e).__name__,
            "service": "document-api",
            "operation": "document_upload"
        })
        raise HTTPException(status_code=500, detail="Failed to upload document")
    finally:
        # Track request duration
        request_duration = time.time() - start_time
        record_histogram_value("api_request_duration_seconds", request_duration, {
            "endpoint": "/clients/{client_id}/upload-document",
            "method": "PUT"
        })
        
        if file_path and file_path.exists():
            file_path.unlink()

@app.get("/clients/{client_id}/documents/{document_id}")
async def retrieve_document_metadata(
    client_id: str, document_id: int, settings=Depends(get_settings)
):
    """Retrieve document metadata by client ID and document ID."""
    start_time = time.time()
    
    # Track active clients on document retrieval
    increment_counter("active_clients_total", 1, {"client_id": client_id})
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.data_store_url}/clients/{client_id}/documents/{document_id}",
                timeout=30.0,
            )

            if response.status_code == 404:
                # API request not found tracking
                increment_counter("api_requests_total", 1, {
                    "endpoint": "/clients/{client_id}/documents/{document_id}",
                    "method": "GET",
                    "status_code": "404"
                })
                # HTTP error tracking for not found
                increment_counter("http_errors_total", 1, {
                    "status_code": "404",
                    "endpoint": "/clients/{client_id}/documents/{document_id}",
                    "service": "data-store"
                })
                raise HTTPException(status_code=404, detail="Document not found")
            elif response.status_code != 200:
                logger.error(f"Failed to retrieve metadata: {response.text}")
                # API request error tracking
                increment_counter("api_requests_total", 1, {
                    "endpoint": "/clients/{client_id}/documents/{document_id}",
                    "method": "GET",
                    "status_code": "500"
                })
                # HTTP error tracking
                increment_counter("http_errors_total", 1, {
                    "status_code": "500",
                    "endpoint": "/clients/{client_id}/documents/{document_id}",
                    "service": "data-store"
                })
                raise HTTPException(
                    status_code=500, detail="Failed to retrieve document metadata"
                )

            metadata = response.json()

        # API request success tracking
        increment_counter("api_requests_total", 1, {
            "endpoint": "/clients/{client_id}/documents/{document_id}",
            "method": "GET",
            "status_code": "200"
        })

        logger.info(
            f"Retrieved metadata for document ID: {document_id} (client: {client_id})"
        )
        return metadata

    except httpx.RequestError as e:
        logger.error(f"Error communicating with data-store: {str(e)}")
        # API request error tracking
        increment_counter("api_requests_total", 1, {
            "endpoint": "/clients/{client_id}/documents/{document_id}",
            "method": "GET",
            "status_code": "503"
        })
        # HTTP error tracking
        increment_counter("http_errors_total", 1, {
            "status_code": "503",
            "endpoint": "/clients/{client_id}/documents/{document_id}",
            "service": "data-store"
        })
        # Exception tracking
        increment_counter("exceptions_total", 1, {
            "exception_type": "httpx.RequestError",
            "service": "document-api",
            "operation": "data_store_communication"
        })
        raise HTTPException(status_code=503, detail="Data store service unavailable")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving document metadata: {str(e)}")
        # API request error tracking
        increment_counter("api_requests_total", 1, {
            "endpoint": "/clients/{client_id}/documents/{document_id}",
            "method": "GET",
            "status_code": "500"
        })
        # HTTP error tracking
        increment_counter("http_errors_total", 1, {
            "status_code": "500",
            "endpoint": "/clients/{client_id}/documents/{document_id}",
            "service": "document-api"
        })
        # Exception tracking
        increment_counter("exceptions_total", 1, {
            "exception_type": type(e).__name__,
            "service": "document-api",
            "operation": "document_retrieval"
        })
        raise HTTPException(
            status_code=500, detail="Failed to retrieve document metadata"
        )
    finally:
        # Track request duration
        request_duration = time.time() - start_time
        record_histogram_value("api_request_duration_seconds", request_duration, {
            "endpoint": "/clients/{client_id}/documents/{document_id}",
            "method": "GET"
        })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
