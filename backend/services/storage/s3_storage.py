"""
S3 Storage Service - Handle file uploads and downloads from AWS S3.

Configuration via environment variables:
- AWS_ACCESS_KEY_ID: AWS access key
- AWS_SECRET_ACCESS_KEY: AWS secret key
- AWS_S3_BUCKET_NAME: S3 bucket name
- AWS_S3_REGION: AWS region (default: us-east-1)
- AWS_S3_STORAGE_PATH: Folder path in bucket (default: graphmind)

Usage:
    from services.storage.s3_storage import s3_storage
    
    # Upload file
    s3_url = s3_storage.upload_document(
        file_bytes=b"...",
        filename="document.pdf",
        user_id="user123"
    )
    
    # Download file
    file_bytes = s3_storage.download_document(s3_key)
    
    # Delete file
    s3_storage.delete_document(s3_key)
"""

import boto3
from botocore.exceptions import ClientError
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional
import os


class S3Storage:
    """AWS S3 storage service for document management."""
    
    def __init__(self):
        """Initialize S3 client with AWS credentials from environment."""
        self.client = None
        self.enabled = False
        self.init_error: Optional[str] = None
        self.bucket_name = os.getenv('AWS_S3_BUCKET_NAME')
        self.region = os.getenv('AWS_S3_REGION', 'us-east-1')
        self.storage_path = os.getenv('AWS_S3_STORAGE_PATH', 'graphmind')
        
        if not self.bucket_name:
            self.init_error = (
                "AWS_S3_BUCKET_NAME environment variable is required. "
                "Set it to your S3 bucket name."
            )
            print(f"S3 storage disabled: {self.init_error}")
            return
        
        # Initialize S3 client
        try:
            self.client = boto3.client(
                's3',
                region_name=self.region,
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            )
            
            # Test connection by listing buckets
            self.client.head_bucket(Bucket=self.bucket_name)
            self.enabled = True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                self.init_error = f"S3 bucket '{self.bucket_name}' does not exist"
            elif error_code == '403':
                self.init_error = f"Access denied to S3 bucket '{self.bucket_name}'. Check AWS credentials."
            else:
                self.init_error = f"Failed to connect to S3: {str(e)}"
            print(f"S3 storage disabled: {self.init_error}")

    def _ensure_enabled(self):
        """Ensure S3 is enabled before performing an operation."""
        if not self.enabled or not self.client:
            message = self.init_error or "S3 storage is disabled"
            raise ValueError(message)
    
    def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        content_type: str = 'application/octet-stream'
    ) -> Tuple[str, str]:
        """
        Upload document to S3.
        
        Args:
            file_bytes: File content as bytes
            filename: Original filename
            user_id: User ID for organizing uploads
            content_type: MIME type of the file
            
        Returns:
            Tuple of (s3_key, s3_url)
            - s3_key: Object key in S3 (for internal reference)
            - s3_url: HTTP URL to access the file
            
        Raises:
            ValueError: If upload fails
        """
        self._ensure_enabled()
        try:
            # Create organized S3 key: graphmind/user123/2024-03-17T14-30-45_document.pdf
            timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S')
            file_ext = Path(filename).suffix
            safe_filename = Path(filename).stem.replace(' ', '_')[:50]  # Truncate to 50 chars
            
            s3_key = f"{self.storage_path}/{user_id}/{timestamp}_{safe_filename}{file_ext}"
            
            # Upload to S3
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_bytes,
                ContentType=content_type,
                Metadata={
                    'original-filename': filename,
                    'user-id': user_id,
                    'upload-timestamp': timestamp,
                }
            )
            
            # Generate HTTPS URL
            s3_url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{s3_key}"
            
            return s3_key, s3_url
            
        except ClientError as e:
            raise ValueError(f"Failed to upload to S3: {str(e)}")
        except Exception as e:
            raise ValueError(f"Unexpected error uploading to S3: {str(e)}")
    
    def download_document(self, s3_key: str) -> bytes:
        """
        Download document from S3.
        
        Args:
            s3_key: S3 object key
            
        Returns:
            File content as bytes
            
        Raises:
            ValueError: If download fails
        """
        self._ensure_enabled()
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=s3_key)
            return response['Body'].read()
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                raise ValueError(f"Document not found in S3: {s3_key}")
            raise ValueError(f"Failed to download from S3: {str(e)}")
        except Exception as e:
            raise ValueError(f"Unexpected error downloading from S3: {str(e)}")
    
    def delete_document(self, s3_key: str) -> bool:
        """
        Delete document from S3.
        
        Args:
            s3_key: S3 object key
            
        Returns:
            True if deleted successfully
            
        Raises:
            ValueError: If deletion fails
        """
        self._ensure_enabled()
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            raise ValueError(f"Failed to delete from S3: {str(e)}")
        except Exception as e:
            raise ValueError(f"Unexpected error deleting from S3: {str(e)}")
    
    def get_download_url(self, s3_key: str, expiration_seconds: int = 3600) -> str:
        """
        Generate pre-signed download URL for S3 object.
        
        Args:
            s3_key: S3 object key
            expiration_seconds: URL expiration time in seconds (default: 1 hour)
            
        Returns:
            Pre-signed URL
            
        Raises:
            ValueError: If URL generation fails
        """
        self._ensure_enabled()
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expiration_seconds
            )
            return url
        except ClientError as e:
            raise ValueError(f"Failed to generate pre-signed URL: {str(e)}")
        except Exception as e:
            raise ValueError(f"Unexpected error generating pre-signed URL: {str(e)}")


# Singleton instance
s3_storage = S3Storage()
