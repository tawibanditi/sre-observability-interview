import logging

import models
from database import engine, get_db
from fastapi import Depends, FastAPI, HTTPException
from models import DocumentMetadata
from schemas import DocumentMetadataCreate, DocumentMetadataResponse
from sqlalchemy.orm import Session

# Import telemetry functions
from telemetry import increment_counter, init_observability, record_histogram_value

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Data Store API", version="1.0.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize observability
init_observability()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "data-store"}


@app.post("/clients/{client_id}/documents", response_model=DocumentMetadataResponse)
async def create_client_document_metadata(
    client_id: str, document: DocumentMetadataCreate, db: Session = Depends(get_db)
):
    """Store document metadata for a specific client"""
    try:
        # Track database operation start
        increment_counter("database_operations_total", 1, {
            "operation": "insert",
            "table": "document_metadata",
            "status": "started"
        })
        
        document_data = document.dict()
        document_data["client_id"] = client_id

        db_document = DocumentMetadata(**document_data)
        db.add(db_document)
        db.commit()
        db.refresh(db_document)

        # Track successful database operation
        increment_counter("database_operations_total", 1, {
            "operation": "insert",
            "table": "document_metadata",
            "status": "success"
        })

        logger.info(
            f"Stored metadata for document: {db_document.filename} (client: {client_id})"
        )
        return db_document
    except Exception as e:
        logger.error(f"Error storing document metadata: {str(e)}")
        
        # Track failed database operation
        increment_counter("database_operations_total", 1, {
            "operation": "insert",
            "table": "document_metadata",
            "status": "failed"
        })
        
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to store document metadata")


@app.get(
    "/clients/{client_id}/documents/{document_id}",
    response_model=DocumentMetadataResponse,
)
async def get_document_metadata(
    client_id: str, document_id: int, db: Session = Depends(get_db)
):
    """Retrieve document metadata by client ID and document ID"""
    try:
        # Track database operation start
        increment_counter("database_operations_total", 1, {
            "operation": "select",
            "table": "document_metadata",
            "status": "started"
        })
        
        document = (
            db.query(DocumentMetadata)
            .filter(
                DocumentMetadata.client_id == client_id, DocumentMetadata.id == document_id
            )
            .first()
        )
        
        if not document:
            # Track not found database operation
            increment_counter("database_operations_total", 1, {
                "operation": "select",
                "table": "document_metadata",
                "status": "not_found"
            })
            raise HTTPException(status_code=404, detail="Document not found")

        # Track successful database operation
        increment_counter("database_operations_total", 1, {
            "operation": "select",
            "table": "document_metadata",
            "status": "success"
        })

        return document
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving document metadata: {str(e)}")
        
        # Track failed database operation
        increment_counter("database_operations_total", 1, {
            "operation": "select",
            "table": "document_metadata",
            "status": "failed"
        })
        
        raise HTTPException(status_code=500, detail="Failed to retrieve document metadata")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
